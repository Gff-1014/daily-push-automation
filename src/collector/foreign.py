# -*- coding: utf-8 -*-
"""早间国外新闻源：新华网国际 + 环球网 + 参考消息。"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.config import Settings
from src.fetch import get_text
from src.models import NewsItem


def _parse_ckxx_time(text: str) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def collect_xinhua(session, settings: Settings) -> List[NewsItem]:
    """新华网国际：静态 HTML，发布时间取 URL 中的日期。"""
    cfg = settings["collector"]["foreign"]
    url = cfg["xinhua_world"]
    items: List[NewsItem] = []
    try:
        text = get_text(session, url, retries=settings["collector"]["retries"], timeout=settings["collector"]["timeout"])
    except Exception:  # noqa: BLE001
        return items
    soup = BeautifulSoup(text, "html.parser")
    seen = set()
    pat = re.compile(r"/20\d{6}/")
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if pat.search(href) and href not in seen:
            seen.add(href)
            title = "".join(a.get_text()).strip()
            if not title:
                continue
            m = re.search(r"/(20\d{6})/", href)
            pub = None
            if m:
                try:
                    pub = datetime.strptime(m.group(1), "%Y%m%d")
                except ValueError:
                    pub = None
            items.append(NewsItem(url=href, title=title, source="新华网", channel="world", category="国际", published_at=pub))
    return items


def collect_huanqiu(session, settings: Settings) -> List[NewsItem]:
    """环球网国际：解析页面内嵌的 SEO 数据容器。"""
    cfg = settings["collector"]["foreign"]
    url = cfg["huanqiu_world"]
    items: List[NewsItem] = []
    try:
        text = get_text(session, url, retries=settings["collector"]["retries"], timeout=settings["collector"]["timeout"])
    except Exception:  # noqa: BLE001
        return items
    soup = BeautifulSoup(text, "html.parser")
    container = soup.select_one(".data-container")
    if not container:
        return items
    for item in container.select(".item"):
        aid = item.select_one(".item-aid")
        title = item.select_one(".item-title")
        ttime = item.select_one(".item-time")
        if not aid or not title:
            continue
        title_text = title.get_text().strip()
        if not title_text:
            continue
        pub = None
        try:
            if ttime:
                ts = int(float(ttime.get_text().strip())) / 1000
                pub = datetime.fromtimestamp(ts)
        except (ValueError, TypeError, OSError):
            pass
        items.append(
            NewsItem(
                url=f"{url}article/{aid.get_text().strip()}",
                title=title_text,
                source="环球网",
                channel="world",
                category="国际",
                published_at=pub,
            )
        )
    return items


def collect_cankao(session, settings: Settings) -> List[NewsItem]:
    """参考消息：channel list.json（pchome 子频道）。"""
    cfg = settings["collector"]["foreign"]
    items: List[NewsItem] = []
    base = "https://ckxxapp.ckxx.net/json/channel/"
    for ch in cfg.get("cankao_channels", []):
        alias = ch.get("alias")
        name = ch.get("name", alias)
        try:
            text = get_text(
                session,
                f"{base}{alias}/list.json",
                retries=settings["collector"]["retries"],
                timeout=settings["collector"]["timeout"],
            )
            data = json.loads(text)
            lst = data.get("list", [])
            for it in lst:
                d = it.get("data") or {}
                title = (d.get("title") or "").strip()
                link = (d.get("url") or "").strip()
                if not title or not link:
                    continue
                items.append(
                    NewsItem(
                        url=link,
                        title=title,
                        summary=(d.get("description") or d.get("txt") or "").strip()[:500],
                        published_at=_parse_ckxx_time(d.get("createtime") or d.get("publishTime") or ""),
                        source="参考消息",
                        channel=alias,
                        category="国际" if name == "国际" else "",
                    )
                )
        except Exception:  # noqa: BLE001
            continue
    return items
