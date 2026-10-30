# -*- coding: utf-8 -*-
"""三大板块纯文字输出。"""
from __future__ import annotations

from datetime import datetime
from typing import List, Tuple

from src.models import NewsItem

SLOT_LABEL = {"morning": "早间", "evening": "晚间"}
SECTION_LABELS = {
    "政治": "政治",
    "经济": "经济",
    "科技": "科技",
    "生活": "生活",
    "国际": "国际",
    "社会": "社会",
    "次类": "次类新闻（文化教育 / 军事国防 / 生态环境 合并整理）",
    "杂类": "杂类新闻",
}


def format_summary(
    slot: str,
    window_start: datetime,
    window_end: datetime,
    speed_list: List[NewsItem],
    sections: List[Tuple[str, List[NewsItem]]],
    *,
    include_links: bool = True,
    hot_topics: list = None,
) -> str:
    label = SLOT_LABEL.get(slot, slot)
    lines: List[str] = []
    lines.append(f"{window_end.month}月{window_end.day}日新闻与热点（{label}）")
    lines.append(f"采集时间：{window_start:%Y-%m-%d %H:%M} 至 {window_end:%Y-%m-%d %H:%M}")
    lines.append("")

    if hot_topics:
        lines.append("今日热点")
        for idx, topic in enumerate(hot_topics, 1):
            lines.append(f"{idx}. {topic}")
        lines.append("")

    if speed_list:
        lines.append("今日要闻速览")
        for idx, it in enumerate(speed_list, 1):
            lines.append(f"{idx}. {it.one_line_summary or it.title}")
        lines.append("")

    main_sections = [s for s in sections if s[0] in ("政治", "经济", "科技", "生活", "国际", "社会")]
    other_sections = [s for s in sections if s[0] not in ("政治", "经济", "科技", "生活", "国际", "社会")]

    if main_sections:
        lines.append("一、主类新闻")
        for key, lst in main_sections:
            lines.append(f"（{SECTION_LABELS[key]}）")
            if not lst:
                lines.append("今日无相关新闻")
            else:
                lines.append(f"概述：本时段{key}类新闻共 {len(lst)} 条，要点如下：")
                for idx, it in enumerate(lst, 1):
                    lines.append(f"{idx}. {it.title}：{it.one_line_summary}")
            lines.append("")

    for idx, (key, lst) in enumerate(other_sections, start=2 if main_sections else 1):
        lines.append(f"{'一' if idx == 1 else '二' if idx == 2 else '三'}、{SECTION_LABELS[key]}")
        if not lst:
            lines.append("今日无相关新闻")
        else:
            for i, it in enumerate(lst, 1):
                tag = f"（{it.category}）" if key == "次类" and it.category in ("文化教育", "军事国防", "生态环境") else ""
                lines.append(f"{i}. {it.title}{tag}：{it.one_line_summary}")
        lines.append("")

    if include_links:
        lines.append("附：原始新闻链接")
        n = 1
        for _, lst in sections:
            for it in lst:
                lines.append(f"{n}. {it.title} —— {it.source} · {it.url}")
                n += 1
    return "\n".join(lines)
