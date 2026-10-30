# -*- coding: utf-8 -*-
"""数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class NewsItem:
    url: str
    title: str
    summary: str = ""
    published_at: Optional[datetime] = None
    source: str = ""
    channel: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    # 评分与输出字段
    category: str = ""
    llm_score: float = 0.0
    heat_score: float = 0.0
    keyword_score: float = 0.0
    final_score: float = 0.0
    keywords: List[str] = field(default_factory=list)
    one_line_summary: str = ""

    def sort_text(self) -> str:
        """进入 LLM 的文本（标题 + 正文摘要截断）。"""
        return self.title


@dataclass
class RunResult:
    slot: str
    run_at: datetime
    window_start: datetime
    window_end: datetime
    collected: List[NewsItem] = field(default_factory=list)
    merged: List[NewsItem] = field(default_factory=list)
    pushed: List[NewsItem] = field(default_factory=list)
    heat_available: bool = True
    warnings: List[str] = field(default_factory=list)
