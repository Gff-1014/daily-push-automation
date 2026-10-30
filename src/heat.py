# -*- coding: utf-8 -*-
"""运行时热度：聚合数据全网热搜榜为主，百度/B站直连兜底。"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

import requests

from src.config import Settings

WORD_KEYS = ("title", "word", "name", "keyword", "hotword", "topic")
HOT_KEYS = ("hotscore", "hot_score", "hot", "num", "heat", "value", "score")
PLATFORM_KEYS = ("platform", "source", "src", "type", "channel")


def _extract_word(item: dict) -> str:
    for k in WORD_KEYS:
        if item.get(k):
            return str(item[k]).strip()
    return ""


def _extract_hot(item: dict) -> float:
    for k in HOT_KEYS:
        v = item.get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.replace(".", "", 1).isdigit():
            return float(v)
    return 0.0


def _extract_platform(item: dict) -> str:
    for k in PLATFORM_KEYS:
        v = item.get(k)
        if v:
            s = str(v)
            for p in ("微博", "百度", "抖音", "B站", "bilibili", "头条", "快手", "知乎"):
                if p.lower() in s.lower():
                    return {"bilibili": "B站"}.get(p, p)
    return ""


def fetch_juhe(settings: Settings) -> List[dict]:
    key = settings.juhe_api_key
    if not key:
        return []
    resp = requests.get(
        settings["heat"]["juhe_url"],
        params={"key": key},
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("error_code") not in (None, 0):
        return []
    result = data.get("result", {})
    lst = result.get("list") if isinstance(result, dict) else result
    if not isinstance(lst, list):
        return []
    return lst


def fetch_baidu_direct(session) -> List[dict]:
    """百度实时热榜直连兜底。"""
    url = "https://top.baidu.com/api/board?platform=wise&tab=realtime"
    resp = session.get(url, timeout=12)
    resp.raise_for_status()
    data = resp.json()
    out = []
    for card in data.get("data", {}).get("cards", []):
        for content in card.get("content", []):
            word = content.get("word") or content.get("query") or ""
            if word:
                out.append({"word": word, "hot": content.get("hotScore", 0), "platform": "百度"})
    return out


def fetch_bilibili_direct() -> List[dict]:
    """B站热门榜直连兜底（先取 buvid cookie）。"""
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    try:
        s.get("https://api.bilibili.com/x/frontend/finger/spi", timeout=10)
        resp = s.get("https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all", timeout=12)
        resp.raise_for_status()
        data = resp.json()
        out = []
        for it in data.get("data", {}).get("list", [])[:50]:
            out.append({"word": it.get("title", ""), "hot": it.get("stat", {}).get("like", 0), "platform": "B站"})
        return out
    except Exception:  # noqa: BLE001
        return []


def fetch_heat(session, settings: Settings) -> Tuple[Dict[str, List[dict]], bool]:
    """返回 {平台: [{word, rank, hot}]} 与是否可用。"""
    platforms = {p: [] for p in settings["heat"]["platforms"]}
    platforms["全网"] = []
    items: List[dict] = []
    provider = settings["heat"].get("provider", "juhe")
    try:
        if provider == "juhe":
            items = fetch_juhe(settings)
        if not items:
            items = fetch_baidu_direct(session)
            items.extend(fetch_bilibili_direct())
    except Exception:  # noqa: BLE001
        items = []

    if not items:
        return platforms, False

    for rank, it in enumerate(items, start=1):
        word = _extract_word(it)
        if not word:
            continue
        plat = _extract_platform(it) or ""
        if plat and plat in platforms:
            platforms[plat].append({"word": word, "rank": rank, "hot": _extract_hot(it)})
        else:
            # 无平台字段：进入「全网」桶（权重为各平台之和）
            platforms["全网"].append({"word": word, "rank": rank, "hot": _extract_hot(it)})

    available = [p for p, v in platforms.items() if v]
    return platforms, bool(available)


def top_hot_words(session, settings: Settings, limit: int = 10) -> List[str]:
    """全网热搜话题（今日热搜板块）：优先聚合数据原始榜单，失败走直连兜底。"""
    items: List[dict] = []
    try:
        if settings["heat"].get("provider", "juhe") == "juhe":
            items = fetch_juhe(settings)
        if not items:
            items = fetch_baidu_direct(session)
            items.extend(fetch_bilibili_direct())
    except Exception:  # noqa: BLE001
        items = []
    words: List[str] = []
    for it in items:
        w = _extract_word(it)
        if w and w not in words:
            words.append(w)
        if len(words) >= limit:
            break
    return words[:limit]
