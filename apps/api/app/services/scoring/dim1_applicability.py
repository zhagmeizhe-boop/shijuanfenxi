"""
dim1 applicability gating.

Current rule:
- only explicit calculation questions are applicable
- bare-formula fill blanks are applicable
- non-calculation application/solution/comprehensive questions do not enter dim1
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Tuple

from app.services.ocr.base import QuestionType

BLANK_PATTERN = re.compile(r"_{2,}|（\s*）|\(\s*\)|\[\s*\]|□|▢")
FORMULA_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*[+\-*/×xX÷]\s*\d+(?:\.\d+)?")
EXPLICIT_CALCULATION_PATTERN = re.compile(
    r"^\s*(?:\d+[、.．]\s*)?(?:计算|直接写得数|得数|口算|列式计算|简便计算|脱式计算|竖式计算|验算)"
)
OPERATOR_PATTERN = re.compile(r"[+\-*/×xX÷=]")
CHINESE_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def _normalize_question_type(question_type: Any) -> str:
    if isinstance(question_type, QuestionType):
        return question_type.value
    if hasattr(question_type, "value"):
        return str(question_type.value).strip().lower()
    return str(question_type or "").strip().lower()


def is_bare_calculation_fill_blank(raw_text: str) -> bool:
    text = (raw_text or "").strip()
    if not text or not BLANK_PATTERN.search(text):
        return False

    compact = re.sub(r"\s+", "", text)
    if "=" not in compact and "＝" not in compact:
        return False
    return bool(FORMULA_PATTERN.search(compact))


def _looks_like_explicit_calculation(raw_text: str) -> bool:
    normalized = " ".join(str(raw_text or "").split())
    if not normalized:
        return False

    if EXPLICIT_CALCULATION_PATTERN.search(normalized):
        return True

    operator_count = len(OPERATOR_PATTERN.findall(normalized))
    chinese_count = len(CHINESE_CHAR_PATTERN.findall(normalized))
    return operator_count >= 2 and chinese_count <= 18


def evaluate_dim1_applicability(
    question_type: Any,
    raw_text: str,
    dim1_feature: Dict[str, Any] | None = None,
    applicable_dimensions: Iterable[str] | None = None,
) -> Tuple[bool, str]:
    normalized_type = _normalize_question_type(question_type)
    normalized_text = " ".join(str(raw_text or "").split())

    explicit_calculation = (
        normalized_type == QuestionType.CALCULATION.value
        or is_bare_calculation_fill_blank(normalized_text)
        or _looks_like_explicit_calculation(normalized_text)
    )
    if explicit_calculation:
        return True, "题面属于显式计算任务或裸算式填空，dim1 适用。"

    return False, "题面不属于计算题或裸算式填空，dim1 不适用。"
