# -*- coding: utf-8 -*-
"""财联社采集：重要快讯（telegraph）+ 资讯文章（depth）。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import List, Optional

from src.config import Settings
from src.fetch import get_text
from src.models import NewsItem


def _sign(qs: str) -> str:
    return hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()


def _build_url(base: str, params: dict) -> str:
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return f"{base}?{qs}&sign={_sign(qs)}"


def _parse_time(value) -> Optional[datetime]:
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def collect_cls(session, settings: Settings) -> List[NewsItem]:
    cfg = settings["collector"]["cls"]
    items: List[NewsItem] = []
    common = {"app": cfg["app"], "os": cfg["os"], "sv": cfg["sv"]}

    # 1) 重要快讯（telegraph）
    try:
        params = dict(common, name="telegraph")
        url = _build_url(cfg["telegraph_url"], params)
        text = get_text(
            session,
            url,
            retries=settings["collector"]["retries"],
            timeout=settings["collector"]["timeout"],
            referer="https://www.cls.cn/telegraph",
        )
        data = json.loads(text)
        roll = data.get("data", {}).get("roll_data", [])
        levels = set(cfg.get("telegraph_levels", ["A", "B"]))
        flags = set(cfg.get("keep_flags", ["is_top"]))
        for it in roll:
            title = (it.get("title") or "").strip()
            level = it.get("level") or ""
            is_keep_flag = any(it.get(f) for f in flags)
            if level not in levels and not is_keep_flag:
                continue
            if not title:
                title = (it.get("brief") or "").strip()[:60]
            items.append(
                NewsItem(
                    url=f"https://www.cls.cn/detail/{it.get('id')}",
                    title=title,
                    summary=(it.get("brief") or it.get("content") or "").strip(),
                    published_at=_parse_time(it.get("ctime")),
                    source="财联社",
                    channel="telegraph",
                    category="",
                    extra={"level": level, "reading_num": it.get("reading_num")},
                )
            )
    except Exception:  # noqa: BLE001
        pass

    # 2) 资讯文章（depth）
    try:
        url = _build_url(cfg["depth_url"], common)
        text = get_text(
            session,
            url,
            retries=settings["collector"]["retries"],
            timeout=settings["collector"]["timeout"],
            referer="https://www.cls.cn/",
        )
        data = json.loads(text)
        depth = data.get("data", {}).get("depth_list", [])
        for it in depth:
            title = (it.get("title") or "").strip()
            link = (it.get("external_link") or "").strip()
            if not link:
                link = f"https://www.cls.cn/detail/{it.get('id')}"
            if not title:
                continue
            items.append(
                NewsItem(
                    url=link,
                    title=title,
                    summary=(it.get("brief") or "").strip(),
                    published_at=_parse_time(it.get("ctime")),
                    source="财联社",
                    channel="depth",
                    category="",
                    extra={"reading_num": it.get("reading_num"), "source": it.get("source")},
                )
            )
    except Exception:  # noqa: BLE001
        pass
    return items
