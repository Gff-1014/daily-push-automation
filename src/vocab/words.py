# -*- coding: utf-8 -*-
"""词库加载与每日新词调度（100 天倒排 + 组内游标）。"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from src.vocab.state import GROUPS, VocabState


def load_words(cfg: Dict[str, Any]) -> List[dict]:
    path = Path(cfg["words_file"])
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def group_map(items: List[dict]) -> Dict[str, List[dict]]:
    """按分类分组，保持 words.json 顺序（即出队顺序）。"""
    out: Dict[str, List[dict]] = {g: [] for g in GROUPS}
    for it in items:
        out.setdefault(it.get("group", ""), []).append(it)
    return out


def daily_quota(cfg: Dict[str, Any], state: VocabState, totals: Dict[str, int], today: date) -> Dict[str, int]:
    """按剩余天数自动均摊：今日配额 = ceil(剩余词数 / 剩余可推新词天数)。"""
    nd = state.new_word_days()
    dn = state.day_no(today)
    if dn > nd:
        return {g: 0 for g in GROUPS}
    rem_days = nd - dn + 1
    quota: Dict[str, int] = {}
    for g in GROUPS:
        remaining = max(0, totals.get(g, 0) - state.cursor(g))
        quota[g] = min(remaining, math.ceil(remaining / rem_days)) if remaining else 0
    return quota


def split_quota(quota: Dict[str, int], morning_ratio: float) -> tuple:
    """把每日配额拆成早间 / 晚间两份。"""
    morning: Dict[str, int] = {}
    evening: Dict[str, int] = {}
    for g in GROUPS:
        total = int(quota.get(g, 0))
        m = min(total, math.floor(total * morning_ratio + 0.5))
        morning[g] = m
        evening[g] = total - m
    return morning, evening


def take_new_words(group_map: Dict[str, List[dict]], state: VocabState, quota: Dict[str, int]) -> Dict[str, List[dict]]:
    """从各组游标处取当日新词。"""
    out: Dict[str, List[dict]] = {}
    for g in GROUPS:
        n = int(quota.get(g, 0))
        start = state.cursor(g)
        out[g] = group_map[g][start : start + n]
    return out
