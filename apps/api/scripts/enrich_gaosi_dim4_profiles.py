from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.llm.moonshot_client import MoonshotClient  # noqa: E402
from app.services.parser.reference_standard import GAOSI_QUESTION_DATA_FILE_NAME  # noqa: E402


DEFAULT_DATA_PATH = ROOT / "app" / "services" / "parser" / GAOSI_QUESTION_DATA_FILE_NAME
DIM4_ALLOWED_VALUES = {
    "strategy_role": {"none", "supporting", "core"},
    "template_fit": {"direct", "adapted", "reframed", "non_routine"},
    "breakthrough_type": {"none", "local_trick", "strategy_shift", "constructive", "exploratory_search"},
    "strategy_shift_count": {"0", "1", "2", "3+"},
    "construction_requirement": {"none", "simple_setup", "case_construction", "custom_construction"},
    "exploration_space": {"none", "bounded", "branched", "open"},
    "representation_reframe": {"none", "minor", "structural", "creative"},
    "transfer_distance": {"near", "medium", "far"},
    "path_openness": {"single", "multiple_paths", "multiple_answers"},
    "dead_end_risk": {"low", "medium", "high"},
    "image_dependency": {"none", "helpful", "required"},
    "reference_level": {"L1", "L2", "L3", "L4", "L5"},
}


SYSTEM_PROMPT = """你是小学数学题目级参考库标注员。
请只为 dim4「建模解题复杂度」生成可审计画像。dim4 先识别题目所属知识点，再判断它在该知识点内部处于 L1-L5 哪个解题组织复杂度等级。
dim4 不评知识广度、年级、是否奥数/竞赛、计算量、题干长度或完整逻辑链长度。
只返回一个 JSON 对象，不要 Markdown，不要解释。"""


USER_PROMPT_TEMPLATE = """请为下面这道高思导引参考题生成 dim4 建模解题画像。

参考信息：
- 年级：{grade}
- 书名：{book_name}
- 讲次：{lecture_no} {lecture_title}
- 篇章：{section_label}
- 题号：{question_no}
- 星级：{star_level}
- OCR 置信度：{ocr_confidence}
- 是否含图：{has_diagram}
- 本地结构画像：{structure_profile_json}

题目：
{question_text}

dim4 知识点内部 L1-L5 口径：
- L1：读懂后可直接建立一个基础关系，解题结构几乎不需要组织。
- L2：需要一次简单转化、一步方程、一次图表取数或轻度条件整理。
- L3：需要整理多条条件，建立常见数量关系、表格、方程、比例关系或简单方案比较。
- L4：需要多阶段、多对象、多关系、多方案、状态变化、倒推或分类框架。
- L5：需要自建整体解题结构，并结合隐藏条件、全局比较/回查、构造、试探、分类或换角度推进。

输出字段必须严格为：
{{
  "knowledge_point": "该题所属具体知识点",
  "strategy_role": "none/supporting/core",
  "template_fit": "direct/adapted/reframed/non_routine",
  "breakthrough_type": "none/local_trick/strategy_shift/constructive/exploratory_search",
  "strategy_shift_count": "0/1/2/3+",
  "construction_requirement": "none/simple_setup/case_construction/custom_construction",
  "exploration_space": "none/bounded/branched/open",
  "representation_reframe": "none/minor/structural/creative",
  "transfer_distance": "near/medium/far",
  "path_openness": "single/multiple_paths/multiple_answers",
  "dead_end_risk": "low/medium/high",
  "global_strategy_required": 0,
  "image_dependency": "none/helpful/required",
  "reference_level": "L1/L2/L3/L4/L5",
  "profile_confidence": 0.0,
  "auto_calibration_allowed": true,
  "evidence_summary": "一句话说明它在该知识点内部为何属于该 L 档",
  "profile_warning": ""
}}

如果题目依赖图形、OCR 文本残缺或你无法稳定判断，请降低 profile_confidence，并把 auto_calibration_allowed 设为 false。"""


def _load_json(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array")
    return [item for item in payload if isinstance(item, dict)]


def _extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.S)
    if fenced:
        cleaned = fenced.group(1)
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("LLM response is not a JSON object")
    return payload


def _choice(payload: Dict[str, Any], key: str, default: str = "") -> str:
    value = str(payload.get(key, default) or "").strip()
    return value if value in DIM4_ALLOWED_VALUES[key] else default


def _zero_one(value: Any) -> int:
    return 1 if value in (1, "1", True) else 0


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def _normalize_profile(payload: Dict[str, Any], *, has_diagram: bool, ocr_confidence: float) -> Dict[str, Any]:
    confidence = _confidence(payload.get("profile_confidence"))
    auto_allowed = payload.get("auto_calibration_allowed", True) is not False
    if has_diagram or (ocr_confidence and ocr_confidence < 0.65):
        auto_allowed = False
        confidence = min(confidence, 0.64)

    return {
        "knowledge_point": str(payload.get("knowledge_point", "") or "").strip(),
        "strategy_role": _choice(payload, "strategy_role", "none"),
        "template_fit": _choice(payload, "template_fit", "direct"),
        "breakthrough_type": _choice(payload, "breakthrough_type", "none"),
        "strategy_shift_count": _choice(payload, "strategy_shift_count", "0"),
        "construction_requirement": _choice(payload, "construction_requirement", "none"),
        "exploration_space": _choice(payload, "exploration_space", "none"),
        "representation_reframe": _choice(payload, "representation_reframe", "none"),
        "transfer_distance": _choice(payload, "transfer_distance", "near"),
        "path_openness": _choice(payload, "path_openness", "single"),
        "dead_end_risk": _choice(payload, "dead_end_risk", "low"),
        "global_strategy_required": _zero_one(payload.get("global_strategy_required")),
        "image_dependency": _choice(payload, "image_dependency", "none"),
        "reference_level": _choice(payload, "reference_level", "L1"),
        "profile_confidence": confidence,
        "auto_calibration_allowed": auto_allowed,
        "evidence_summary": str(payload.get("evidence_summary", "") or "").strip(),
        "profile_warning": str(payload.get("profile_warning", "") or "").strip(),
        "profile_source": "llm_enriched",
    }


def _needs_profile(entry: Dict[str, Any], overwrite: bool) -> bool:
    profiles = entry.get("dimension_profiles")
    if not isinstance(profiles, dict):
        return True
    dim4_profile = profiles.get("dim4")
    if overwrite or not isinstance(dim4_profile, dict):
        return True
    return dim4_profile.get("profile_source") == "local_structure_skeleton"


async def _enrich_one(client: MoonshotClient, entry: Dict[str, Any], max_tokens: int) -> Dict[str, Any]:
    ocr_confidence = _confidence(entry.get("ocr_confidence"))
    profiles = entry.get("dimension_profiles")
    structure_profile = profiles.get("structure", {}) if isinstance(profiles, dict) else {}
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_PROMPT_TEMPLATE.format(
                grade=entry.get("grade", ""),
                book_name=entry.get("book_name", ""),
                lecture_no=entry.get("lecture_no", ""),
                lecture_title=entry.get("lecture_title", ""),
                section_label=entry.get("section_label", ""),
                question_no=entry.get("question_no", ""),
                star_level=entry.get("star_level", ""),
                ocr_confidence=entry.get("ocr_confidence", ""),
                has_diagram=entry.get("has_diagram", False),
                structure_profile_json=json.dumps(
                    structure_profile,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                question_text=entry.get("question_text", ""),
            ),
        },
    ]
    response = await client.chat(
        messages,
        temperature=0.1,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    profile = _normalize_profile(
        _extract_json_object(response),
        has_diagram=bool(entry.get("has_diagram", False)),
        ocr_confidence=ocr_confidence,
    )
    profiles = entry.get("dimension_profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    profiles["dim4"] = profile
    entry["dimension_profiles"] = profiles
    return entry


async def enrich_entries(args: argparse.Namespace) -> List[Dict[str, Any]]:
    entries = _load_json(args.input)
    candidates = [
        entry
        for entry in entries[args.offset :]
        if str(entry.get("question_text", "")).strip() and _needs_profile(entry, args.overwrite)
    ]
    if args.limit > 0:
        candidates = candidates[: args.limit]

    if args.dry_run:
        print(f"dry run: {len(candidates)} entries would be enriched")
        return entries

    client = MoonshotClient(
        model=args.model or settings.CLAUDE_MODEL,
        base_url=args.base_url or settings.LLM_BASE_URL,
        temperature=0.1,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
    )
    semaphore = asyncio.Semaphore(args.concurrency)

    async def run(entry: Dict[str, Any]) -> None:
        async with semaphore:
            await _enrich_one(client, entry, args.max_tokens)

    await asyncio.gather(*(run(entry) for entry in candidates))
    return entries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich GaoSi question references with dim4 strategy profiles.")
    parser.add_argument("--input", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0, help="0 means all pending entries.")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--max-tokens", type=int, default=1600)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    entries = asyncio.run(enrich_entries(args))
    if args.dry_run:
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    profiled_count = sum(
        1
        for entry in entries
        if isinstance(entry.get("dimension_profiles"), dict)
        and isinstance(entry["dimension_profiles"].get("dim4"), dict)
    )
    print(f"wrote {args.output}")
    print(f"dim4 profiles: {profiled_count}/{len(entries)}")


if __name__ == "__main__":
    main()
