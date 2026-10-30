# -*- coding: utf-8 -*-
"""央视网采集：news.cctv.com JSONP 频道接口 + military 数据接口。"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import List, Optional

from src.config import Settings
from src.fetch import get_text
from src.models import NewsItem

_JSONP = re.compile(r"^\w+\((.*)\)$", re.S)


def _parse_time(text: str) -> Optional[datetime]:
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S+08:00",
    ):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return None


def collect_cctv(session, settings: Settings, foreign_only: bool = False) -> List[NewsItem]:
    """采集央视网各频道。foreign_only 仅取国际频道（早间国外源的一部分）。"""
    cfg = settings["collector"]["cctv"]
    base = cfg["base"]
    max_items = settings["collector"].get("max_items_per_channel", 80)
    items: List[NewsItem] = []
    for channel, categories in cfg["channels"].items():
        if foreign_only and channel != "world":
            continue
        url = f"{base}{channel}_1.jsonp"
        try:
            text = get_text(session, url, retries=settings["collector"]["retries"], timeout=settings["collector"]["timeout"])
            m = _JSONP.match(text)
            if not m:
                continue
            data = json.loads(m.group(1))
            lst = data.get("data", {}).get("list", [])[:max_items]
            for it in lst:
                title = (it.get("title") or "").strip()
                link = (it.get("url") or "").strip()
                if not title or not link:
                    continue
                items.append(
                    NewsItem(
                        url=link,
                        title=title,
                        summary=(it.get("brief") or "").strip(),
                        published_at=_parse_time(it.get("focus_date") or ""),
                        source="央视网",
                        channel=channel,
                        category=categories[0] if categories else "",
                    )
                )
        except Exception:  # noqa: BLE001
            continue  # 单频道失败不影响整体

    if not foreign_only:
        try:
            text = get_text(
                session,
                cfg["military_url"],
                retries=settings["collector"]["retries"],
                timeout=settings["collector"]["timeout"],
            )
            data = json.loads(text)
            roll = data.get("rollData") if isinstance(data, dict) else None
            if isinstance(roll, list):
                for it in roll[:max_items]:
                    title = (it.get("title") or "").strip()
                    link = (it.get("url") or "").strip()
                    if not title or not link:
                        continue
                    items.append(
                        NewsItem(
                            url=link,
                            title=title,
                            summary=(it.get("description") or it.get("brief") or "").strip(),
                            published_at=_parse_time(it.get("dateTime") or it.get("time") or ""),
                            source="央视网",
                            channel="military",
                            category=cfg["military_category"],
                        )
                    )
        except Exception:  # noqa: BLE001
            pass
    return items
