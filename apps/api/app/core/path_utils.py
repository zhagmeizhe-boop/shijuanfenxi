from __future__ import annotations

from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[2]


def resolve_runtime_path(raw_path: str | Path) -> Path:
    path = Path(str(raw_path or ""))
    if path.is_absolute():
        return path

    normalized = str(raw_path or "").replace("\\", "/").lstrip("./")
    return (API_ROOT / normalized).resolve()


def normalize_database_url(database_url: str) -> str:
    if not database_url.startswith("sqlite"):
        return database_url

    prefix, separator, raw_path = database_url.partition(":///")
    if not separator or raw_path == ":memory:":
        return database_url

    sqlite_path = Path(raw_path)
    if sqlite_path.is_absolute():
        return database_url

    resolved = resolve_runtime_path(raw_path)
    return f"{prefix}:///{resolved.as_posix()}"

