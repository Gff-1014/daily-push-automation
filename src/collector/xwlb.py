# -*- coding: utf-8 -*-
"""央视《新闻联播》每日文字总结采集（晚间 20:30 运行，19:00 播出后页面已发布）。"""
from __future__ import annotations

import re
from datetime import datetime, time as dtime
from typing import List

from bs4 import BeautifulSoup

from src.config import Settings
from src.fetch import get_text
from src.models import NewsItem

DAY_URL = "https://tv.cctv.com/lm/xwlb/day/{date}.shtml"
MARK = "本期节目主要内容"


def _parse_items(body: str) -> List[str]:
    """把提要文本拆成条目：顶层数字条目 + 快讯子条目。"""
    parts = re.split(r"\d{1,2}\.\s*", body)
    out: List[str] = []
    for seg in parts:
        seg = seg.strip().strip("；;。")
        if len(seg) < 2:
            continue
        subs = re.split(r"[（(]\d{1,2}[）)]\s*", seg)
        if len(subs) > 1:
            # 形如「国内联播快讯：（1）xxx；（2）yyy」：跳过前缀，子条目各自成条
            for s in subs[1:]:
                s = s.strip().strip("；;。")
                if s:
                    out.append(s)
        else:
            out.append(seg)
    return out


def collect_xwlb(session, settings: Settings, now: datetime) -> List[NewsItem]:
    cfg = settings["collector"].get("xwlb", {})
    if not cfg.get("enabled", False):
        return []
    date_str = now.strftime("%Y%m%d")
    day_url = DAY_URL.format(date=date_str)
    try:
        text = get_text(
            session,
            day_url,
            retries=settings["collector"]["retries"],
            timeout=settings["collector"]["timeout"],
        )
    except Exception:  # noqa: BLE001
        return []  # 当日页面未发布（如播出延迟），静默跳过

    soup = BeautifulSoup(text, "html.parser")
    links = [a["href"] for a in soup.find_all("a", href=True) if "VIDE" in a["href"]]
    if not links:
        return []

    episode_url = links[0]
    try:
        ep_text = get_text(
            session,
            episode_url,
            retries=settings["collector"]["retries"],
            timeout=settings["collector"]["timeout"],
        )
    except Exception:  # noqa: BLE001
        return []

    ep_soup = BeautifulSoup(ep_text, "html.parser")
    full_text = " ".join(ep_soup.get_text().split())
    idx = full_text.find(MARK)
    if idx < 0:
        return []
    body = full_text[idx + len(MARK):]
    end = body.find("《新闻联播》")
    if end > 0:
        body = body[:end]

    items: List[NewsItem] = []
    pub = datetime.combine(now.date(), dtime(19, 0))
    for title in _parse_items(body):
        items.append(
            NewsItem(
                url=episode_url,
                title=title,
                summary=title,
                published_at=pub,
                source="央视网·新闻联播",
                channel="xwlb",
                category="",
            )
        )
    return items
