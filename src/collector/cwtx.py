# -*- coding: utf-8 -*-
"""央视《朝闻天下》每日文字总结采集（早间 08:30 运行，取当天最新一期）。"""
from __future__ import annotations

import re
from datetime import datetime, time as dtime
from typing import List, Optional

import requests

from src.collector.xwlb import _parse_items
from src.config import Settings
from src.models import NewsItem

API = "https://api.cntv.cn/NewVideo/getVideoListByColumn"
COLUMN_ID = "TOPC1451558496100826"  # 朝闻天下
MARK = "本期节目主要内容"
EP_RE = re.compile(r"《朝闻天下》\s*(\d{8})\s*(\d{2}):(\d{2})")


def _edition_minutes(title: str) -> Optional[int]:
    m = EP_RE.search(title or "")
    if not m:
        return None
    return int(m.group(2)) * 60 + int(m.group(3))


def _parse_brief(body: str) -> List[str]:
    """朝闻天下提要为分号分隔（无数字编号），统一按分号切分。"""
    out = []
    for seg in re.split(r"[；;]", body):
        seg = seg.strip().strip("。. ")
        if len(seg) >= 2:
            out.append(seg)
    return out


def collect_cwtx(session, settings: Settings, now: datetime) -> List[NewsItem]:
    cfg = settings["collector"].get("cwtx", {})
    if not cfg.get("enabled", False):
        return []
    params = {
        "id": cfg.get("column_id", COLUMN_ID),
        "n": "100",
        "sort": "desc",
        "p": "1",
        "bd": now.strftime("%Y%m%d"),
        "mode": "2",
        "serviceId": "tvcctv",
    }
    try:
        resp = requests.get(API, params=params, timeout=15, headers={"User-Agent": settings["collector"]["user_agent"]})
        resp.raise_for_status()
        data = resp.json()
        lst = data.get("data", {}).get("list", [])
    except Exception:  # noqa: BLE001
        return []

    episodes = [it for it in lst if it.get("title", "").startswith("《朝闻天下》")]
    episodes.sort(key=lambda it: _edition_minutes(it.get("title", "")) or -1, reverse=True)
    if not episodes:
        return []
    ep = episodes[0]
    brief = ep.get("brief", "") or ""
    idx = brief.find(MARK)
    body = brief[idx + len(MARK):] if idx >= 0 else brief
    body = body.lstrip("：: \n\t")
    end = body.find("（《朝闻天下》")
    if end > 0:
        body = body[:end]

    m = EP_RE.search(ep.get("title", "") or "")
    pub = datetime.combine(now.date(), dtime(6, 0))
    if m:
        try:
            pub = datetime.combine(now.date(), dtime(int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass

    items: List[NewsItem] = []
    for title in _parse_brief(body):
        items.append(
            NewsItem(
                url=ep.get("url", ""),
                title=title,
                summary=title,
                published_at=pub,
                source="央视网·朝闻天下",
                channel="cwtx",
                category="",
            )
        )
    return items
