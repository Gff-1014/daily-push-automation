# -*- coding: utf-8 -*-
"""最终评分、门槛过滤、板块排序与上限。"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Tuple

from src.categories import MAIN_CATEGORIES, SUB_CATEGORIES
from src.config import Settings
from src.heat import fetch_heat
from src.keywords import KeywordScorer
from src.models import NewsItem

SECTION_KEYS = MAIN_CATEGORIES + ["次类", "杂类"]


def _section_key(category: str) -> str:
    if category in MAIN_CATEGORIES:
        return category
    if category in SUB_CATEGORIES:
        return "次类"
    return "杂类"


def _item_text_for_heat(item: NewsItem, limit: int = 300) -> str:
    return (item.title + "。" + (item.summary or "")[:limit])[:limit + 200]


def apply_heat_scores(items: List[NewsItem], session, settings: Settings) -> bool:
    platforms, available = fetch_heat(session, settings)
    if not available:
        return False
    weights = {k: float(v) for k, v in settings["heat"]["weights"].items()}
    if "全网" not in weights and "全网" in platforms:
        weights["全网"] = sum(weights.values())
    raw = []
    for it in items:
        text = _item_text_for_heat(it)
        keywords = [k for k in (it.keywords or []) if k]
        total = 0.0
        for plat, lst in platforms.items():
            best_rank = None
            for entry in lst:
                word = entry["word"] or ""
                if not word:
                    continue
                if _heat_match(word, text, keywords):
                    best_rank = entry["rank"] if best_rank is None else min(best_rank, entry["rank"])
            if best_rank is not None:
                contrib = max(0.0, 1.0 - (best_rank - 1) / 50.0)
                total += weights.get(plat, 0.0) * contrib
        raw.append(total)
    max_raw = max(raw) if raw else 0.0
    for it, v in zip(items, raw):
        it.heat_score = v / max_raw if max_raw > 0 else 0.0
    return True


def _heat_match(word: str, text: str, keywords: list) -> bool:
    """热词与新闻匹配：包含匹配 或 关键词双向包含。"""
    if word in text:
        return True
    for kw in keywords:
        if not kw:
            continue
        if kw in word or word in kw:
            return True
        # 关键实体片段（>=2 字）出现在热词中
        if len(kw) >= 2 and kw[:2] in word:
            return True
    return False


def apply_keyword_scores(items: List[NewsItem], scorer: KeywordScorer, settings: Settings) -> None:
    match_chars = int(settings["keyword"].get("match_chars", 500))
    for it in items:
        it.keyword_score, _ = scorer.score(it, match_chars)


def final_score(item: NewsItem, weights: Dict[str, float]) -> float:
    return 100.0 * (
        weights["w_llm"] * (item.llm_score / 10.0)
        + weights["w_heat"] * item.heat_score
        + weights["w_keyword"] * item.keyword_score
    )


def select_pushed(
    items: List[NewsItem],
    session,
    settings: Settings,
    slot: str,
    scorer: KeywordScorer,
) -> Tuple[List[NewsItem], List[Tuple[str, List[NewsItem]]], bool]:
    """计算最终分 → 门槛过滤 → 板块排序 → 上限截取。返回 (速览候选, 分板块列表, 热度是否可用)。"""
    heat_ok = apply_heat_scores(items, session, settings)
    apply_keyword_scores(items, scorer, settings)

    scoring = settings["scoring"]
    if heat_ok:
        weights = {"w_llm": scoring["w_llm"], "w_heat": scoring["w_heat"], "w_keyword": scoring["w_keyword"]}
    else:
        fb = scoring.get("heat_fallback_weights", {"w_llm": 0.80, "w_keyword": 0.20})
        weights = {"w_llm": fb["w_llm"], "w_heat": 0.0, "w_keyword": fb["w_keyword"]}

    for it in items:
        bonus = float(scoring.get("source_bonus", {}).get(it.source, 0.0))
        it.final_score = round(min(final_score(it, weights) + bonus, 100.0), 1)

    thresholds = settings["slots"][slot]["thresholds"]
    caps = settings["caps"]
    sections: Dict[str, List[NewsItem]] = {k: [] for k in SECTION_KEYS}
    for it in items:
        key = _section_key(it.category)
        if it.final_score < float(thresholds.get(key, 60)):
            continue
        sections[key].append(it)

    ordered: List[Tuple[str, List[NewsItem]]] = []
    passed: List[NewsItem] = []
    for key in SECTION_KEYS:
        lst = sections[key]
        passed.extend(lst)
        lst.sort(key=lambda x: (x.final_score, x.published_at or datetime.min), reverse=True)
        cap = int(caps.get(key, 10))
        ordered.append((key, lst[:cap]))

    speed_list = sorted(passed, key=lambda x: x.final_score, reverse=True)[: int(settings["output"].get("speed_count", 10))]
    return speed_list, ordered, heat_ok
