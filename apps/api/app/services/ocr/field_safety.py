from __future__ import annotations

import logging
import re
from typing import Any

MAX_QUESTION_NO_LENGTH = 20
MAX_SECTION_INDEX_RAW_LENGTH = 100

_SECTION_INDEX_PATTERN = re.compile(r"^\s*([一二三四五六七八九十百]+|\d{1,3})\s*[、.．)]")


def normalize_section_index_raw(value: Any) -> str:
    """Keep section identifiers short even when OCR returns the full heading."""
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""

    match = _SECTION_INDEX_PATTERN.search(text)
    if match:
        return match.group(1)

    return text[:MAX_SECTION_INDEX_RAW_LENGTH]


def clamp_storage_text(
    value: Any,
    max_length: int,
    *,
    field_name: str,
    logger: logging.Logger | None = None,
    context: str = "",
) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= max_length:
        return text

    if logger:
        logger.warning(
            "Storage field truncated field=%s max_length=%s context=%s value_preview=%s",
            field_name,
            max_length,
            context,
            text[:80],
        )
    return text[:max_length]


def question_no_would_be_truncated(raw_value: Any) -> bool:
    text = str(raw_value or "").strip()
    if not text:
        return False
    text = text.replace("（", "(").replace("）", ")").strip()
    if re.search(r"(\d{1,3})(?:\s*[.．、题)]|$)", text):
        return False
    compact = re.sub(r"\s+", "", text)
    return len(compact) > MAX_QUESTION_NO_LENGTH
