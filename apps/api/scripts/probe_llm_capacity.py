from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import math
import mimetypes
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.ocr.vision_llm_provider import (  # noqa: E402
    VISION_JSON_RESPONSE_FORMAT,
    VISION_PAGE_SYSTEM_PROMPT,
    VISION_PAGE_USER_PROMPT,
)
from app.services.parser.prompts import (  # noqa: E402
    QUESTION_ANALYSIS_SYSTEM_PROMPT,
    QUESTION_ANALYSIS_USER_PROMPT_TEMPLATE,
)


LADDER = [1, 2, 4, 8, 12, 16, 24, 32, 48, 64, 96]
MIXED_CASES = [(3, 8), (5, 10), (8, 16)]
RATE_LIMIT_HEADERS = (
    "retry-after",
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-tokens",
)


@dataclass
class RequestResult:
    ok: bool
    kind: str
    status_code: int | None
    latency_seconds: float
    error_type: str
    error_message: str
    prompt_tokens: int
    completion_tokens: int
    rate_limit_headers: dict[str, str]


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key] = value
    return values


def setting(name: str, env_file_values: dict[str, str], default: str = "") -> str:
    return os.getenv(name) or env_file_values.get(name) or default


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = math.ceil((pct / 100.0) * len(ordered)) - 1
    return ordered[max(0, min(index, len(ordered) - 1))]


def sample_question_text() -> str:
    return """
某校六年级组织数学综合能力测试。第 1 题：
甲、乙两车同时从 A、B 两地相向而行。甲车每小时行 48 千米，乙车每小时行 42 千米。
两车相遇后继续前进，甲车到达 B 地后立即返回，乙车到达 A 地后也立即返回。
已知两车第二次相遇地点距离 A 地 36 千米，求 A、B 两地相距多少千米。

第 2 题：
如图，一个长方形被两条线段分成若干部分。已知左上角三角形面积为 12 平方厘米，
右下角三角形面积为 20 平方厘米，中间阴影部分与两个空白三角形等高。
请根据图形关系求阴影部分面积，并说明需要用到的面积关系。

第 3 题：
某商店进了一批文具，第一天卖出总数的 25%，第二天卖出剩下的 40%，
第三天又卖出 36 件，这时还剩下原来总数的 30%。这批文具原来有多少件？

第 4 题：
一个数列按如下规律排列：1，3，6，10，15，21，...
如果把这个数列每 5 项分为一组，第 20 组第 3 个数是多少？请分析规律和计算过程。
""".strip()


def build_question_payload(model: str, max_tokens: int, request_index: int) -> dict[str, Any]:
    user_prompt = QUESTION_ANALYSIS_USER_PROMPT_TEMPLATE.format(
        question_no=str((request_index % 25) + 1),
        page_no=str((request_index % 5) + 1),
        question_type="application",
        has_image="否",
        ocr_warnings="无",
        sub_item_candidates="无",
        parse_audit_summary="视觉 OCR 已识别题号、题干和题型；无明显截断。",
        question_text=sample_question_text(),
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": QUESTION_ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }


def find_vision_image(search_root: Path) -> Path:
    preferred = sorted(search_root.glob("**/vision_pages/page_*.jpg"))
    if preferred:
        return preferred[0]
    candidates = sorted(
        [
            *search_root.glob("**/*.jpg"),
            *search_root.glob("**/*.jpeg"),
            *search_root.glob("**/*.png"),
        ]
    )
    if not candidates:
        raise FileNotFoundError(f"No vision image found under {search_root}")
    return candidates[0]


def image_to_data_url(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(path))
    mime_type = mime_type or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def build_vision_payload(model: str, max_tokens: int, image_path: Path, request_index: int) -> dict[str, Any]:
    with Image.open(image_path) as image:
        width, height = image.size
    prompt_text = (
        VISION_PAGE_USER_PROMPT.replace("{page_no}", str((request_index % 5) + 1))
        .replace("{width}", str(width))
        .replace("{height}", str(height))
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": VISION_PAGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": VISION_JSON_RESPONSE_FORMAT,
    }


async def post_once(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    kind: str,
) -> RequestResult:
    started = time.perf_counter()
    status_code: int | None = None
    rate_headers: dict[str, str] = {}
    try:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        status_code = response.status_code
        rate_headers = {
            key: response.headers[key]
            for key in RATE_LIMIT_HEADERS
            if key in response.headers
        }
        response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        return RequestResult(
            ok=True,
            kind=kind,
            status_code=status_code,
            latency_seconds=time.perf_counter() - started,
            error_type="",
            error_message="",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            rate_limit_headers=rate_headers,
        )
    except Exception as exc:
        return RequestResult(
            ok=False,
            kind=kind,
            status_code=status_code,
            latency_seconds=time.perf_counter() - started,
            error_type=exc.__class__.__name__,
            error_message=str(exc)[:500],
            prompt_tokens=0,
            completion_tokens=0,
            rate_limit_headers=rate_headers,
        )


def summarize_results(
    *,
    mode: str,
    concurrency: int,
    question_count: int,
    vision_count: int,
    results: list[RequestResult],
) -> dict[str, Any]:
    latencies = [item.latency_seconds for item in results]
    successes = [item for item in results if item.ok]
    status_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    for item in results:
        status_key = str(item.status_code or "exception")
        status_counts[status_key] = status_counts.get(status_key, 0) + 1
        if item.error_type:
            error_counts[item.error_type] = error_counts.get(item.error_type, 0) + 1

    total = len(results)
    timeout_count = sum(1 for item in results if "Timeout" in item.error_type)
    summary = {
        "mode": mode,
        "concurrency": concurrency,
        "question_count": question_count,
        "vision_count": vision_count,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "total": total,
        "success_count": len(successes),
        "failed_count": total - len(successes),
        "success_rate": round(len(successes) / total if total else 0.0, 4),
        "429_count": status_counts.get("429", 0),
        "5xx_count": sum(count for code, count in status_counts.items() if code.isdigit() and 500 <= int(code) <= 599),
        "timeout_count": timeout_count,
        "timeout_rate": round(timeout_count / total if total else 0.0, 4),
        "avg_latency": round(statistics.mean(latencies), 3) if latencies else 0.0,
        "p50_latency": round(percentile(latencies, 50), 3),
        "p95_latency": round(percentile(latencies, 95), 3),
        "max_latency": round(max(latencies), 3) if latencies else 0.0,
        "prompt_tokens": sum(item.prompt_tokens for item in results),
        "completion_tokens": sum(item.completion_tokens for item in results),
        "status_counts": status_counts,
        "error_counts": error_counts,
        "rate_limit_headers_seen": [
            item.rate_limit_headers for item in results if item.rate_limit_headers
        ][:5],
    }
    summary["stable"] = (
        summary["success_rate"] >= 0.95
        and summary["429_count"] == 0
        and summary["timeout_rate"] <= 0.02
        and summary["p95_latency"] <= 90
    )
    return summary


def should_stop(summary: dict[str, Any]) -> bool:
    return (
        summary["429_count"] > 0
        or summary["timeout_rate"] > 0.02
        or summary["success_rate"] < 0.95
        or summary["p95_latency"] > 90
        or summary["5xx_count"] >= 2
    )


async def run_case(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    model: str,
    mode: str,
    question_count: int,
    vision_count: int,
    question_max_tokens: int,
    vision_max_tokens: int,
    image_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tasks = []
    for index in range(question_count):
        payload = build_question_payload(model, question_max_tokens, index)
        tasks.append(
            post_once(
                client,
                base_url=base_url,
                api_key=api_key,
                payload=payload,
                kind="question",
            )
        )
    for index in range(vision_count):
        payload = build_vision_payload(model, vision_max_tokens, image_path, index)
        tasks.append(
            post_once(
                client,
                base_url=base_url,
                api_key=api_key,
                payload=payload,
                kind="vision",
            )
        )

    results = await asyncio.gather(*tasks)
    summary = summarize_results(
        mode=mode,
        concurrency=question_count + vision_count,
        question_count=question_count,
        vision_count=vision_count,
        results=results,
    )
    details = [
        {
            "ok": item.ok,
            "kind": item.kind,
            "status_code": item.status_code,
            "latency_seconds": round(item.latency_seconds, 3),
            "error_type": item.error_type,
            "error_message": item.error_message,
            "prompt_tokens": item.prompt_tokens,
            "completion_tokens": item.completion_tokens,
            "rate_limit_headers": item.rate_limit_headers,
        }
        for item in results
    ]
    return summary, details


def write_outputs(output_dir: Path, summaries: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(
        json.dumps({"summaries": summaries, "details": details}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    fieldnames = [
        "mode",
        "concurrency",
        "question_count",
        "vision_count",
        "success_count",
        "failed_count",
        "success_rate",
        "429_count",
        "5xx_count",
        "timeout_count",
        "timeout_rate",
        "avg_latency",
        "p50_latency",
        "p95_latency",
        "max_latency",
        "prompt_tokens",
        "completion_tokens",
        "stable",
        "status_counts",
        "error_counts",
    ]
    with (output_dir / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for summary in summaries:
            row = {key: summary.get(key) for key in fieldnames}
            row["status_counts"] = json.dumps(row["status_counts"], ensure_ascii=False)
            row["error_counts"] = json.dumps(row["error_counts"], ensure_ascii=False)
            writer.writerow(row)


async def run_probe(args: argparse.Namespace) -> int:
    env_values = load_env_file(Path(args.env_file))
    base_url = setting("LLM_BASE_URL", env_values, "https://one-api.aixuexi.com/v1")
    model = setting("CLAUDE_MODEL", env_values, "claude-sonnet-4-5")
    api_key = (
        setting("ANTHROPIC_API_KEY", env_values)
        or setting("MOONSHOT_API_KEY", env_values)
        or setting("OPENAI_API_KEY", env_values)
    )
    if not api_key:
        raise RuntimeError("No API key found in env file or environment")

    image_path = Path(args.image_path) if args.image_path else find_vision_image(Path(args.uploads_dir))
    output_dir = Path(args.output_dir)
    summaries: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []

    timeout = httpx.Timeout(connect=20.0, read=args.request_timeout, write=60.0, pool=args.request_timeout)
    limits = httpx.Limits(max_connections=max(args.max_concurrency, 32), max_keepalive_connections=max(args.max_concurrency, 32))
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        for mode in args.modes:
            cases: list[tuple[int, int, int]]
            if mode == "question":
                cases = [(level, level, 0) for level in LADDER if level <= args.max_concurrency]
            elif mode == "vision":
                cases = [(level, 0, level) for level in LADDER if level <= args.max_concurrency]
            elif mode == "mixed":
                cases = [(question + vision, question, vision) for vision, question in MIXED_CASES if question + vision <= args.max_concurrency]
            else:
                raise ValueError(f"Unsupported mode: {mode}")

            for concurrency, question_count, vision_count in cases:
                print(
                    json.dumps(
                        {
                            "event": "case_start",
                            "mode": mode,
                            "concurrency": concurrency,
                            "question_count": question_count,
                            "vision_count": vision_count,
                            "model": model,
                            "base_url": base_url,
                            "image_path": str(image_path),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                summary, case_details = await run_case(
                    client=client,
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    mode=mode,
                    question_count=question_count,
                    vision_count=vision_count,
                    question_max_tokens=args.question_max_tokens,
                    vision_max_tokens=args.vision_max_tokens,
                    image_path=image_path,
                )
                summaries.append(summary)
                details.extend(
                    {
                        "mode": mode,
                        "concurrency": concurrency,
                        "request_index": index,
                        **item,
                    }
                    for index, item in enumerate(case_details)
                )
                write_outputs(output_dir, summaries, details)
                print(json.dumps({"event": "case_done", **summary}, ensure_ascii=False), flush=True)

                if should_stop(summary):
                    print(
                        json.dumps(
                            {
                                "event": "mode_stop",
                                "mode": mode,
                                "concurrency": concurrency,
                                "reason": "stop threshold reached",
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    break

                if args.cooldown_seconds > 0:
                    await asyncio.sleep(args.cooldown_seconds)

    write_outputs(output_dir, summaries, details)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe OpenAI-compatible LLM concurrency capacity.")
    parser.add_argument("--env-file", default="/app/.env")
    parser.add_argument("--uploads-dir", default="/app/uploads")
    parser.add_argument("--image-path", default="")
    parser.add_argument("--output-dir", default="/app/tmp_llm_capacity_probe")
    parser.add_argument("--max-concurrency", type=int, default=96)
    parser.add_argument("--modes", nargs="+", default=["question", "vision", "mixed"], choices=["question", "vision", "mixed"])
    parser.add_argument("--cooldown-seconds", type=float, default=30.0)
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--question-max-tokens", type=int, default=2800)
    parser.add_argument("--vision-max-tokens", type=int, default=12000)
    return parser.parse_args()


def main() -> int:
    return asyncio.run(run_probe(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
