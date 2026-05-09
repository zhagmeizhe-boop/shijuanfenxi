from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class OCRLine:
    text: str
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass
class QuestionAnchor:
    line_index: int
    question_no: str
    question_label_raw: str
    line: OCRLine
    force_use_label: bool = False
    recovery_reason: str = ""


@dataclass
class ReadingZone:
    zone_key: str
    lines: List[OCRLine]
    left: int
    top: int
    right: int
    bottom: int
    layout_type: str

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass
class SectionBlock:
    zone_key: str
    section_index_raw: str
    heading_text: str
    lines: List[OCRLine]
    left: int
    top: int
    right: int
    bottom: int
    declared_count: Optional[int]
    layout_type: str
    is_headingless_prefix: bool = False

    @property
    def bbox(self) -> Dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": max(self.right - self.left, 1),
            "height": max(self.bottom - self.top, 1),
        }
