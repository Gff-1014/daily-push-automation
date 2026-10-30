# -*- coding: utf-8 -*-
"""采集编排：多源采集 → 窗口过滤 → 去重合并。"""
from __future__ import annotations

from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from src.collector.cctv import collect_cctv
from src.collector.cls import collect_cls
from src.collector.cwtx import collect_cwtx
from src.collector.foreign import collect_cankao, collect_huanqiu, collect_xinhua
from src.collector.normalize import fingerprint, normalize_title
from src.collector.xwlb import collect_xwlb
from src.config import Settings
from src.models import NewsItem


def window_bounds(slot_cfg: dict, now: datetime) -> Tuple[datetime, datetime]:
    """按配置取窗口起点：早间=前一天 20:30，晚间=当天 08:30，两端无缝覆盖完整 24 小时。"""
    hh, mm = map(int, str(slot_cfg.get("window_start", "08:30")).split(":"))
    if slot_cfg.get("window_prev_day"):
        start = (now - timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    else:
        start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return start, now


def _in_window(item: NewsItem, start: datetime, end: datetime) -> bool:
    if item.published_at is None:
        return True  # 无时间戳的来自最新列表，视为窗口内
    return start <= item.published_at <= end + timedelta(minutes=5)


def collect_all(session, settings: Settings, slot: str, now: Optional[datetime] = None) -> Tuple[List[NewsItem], List[str]]:
    cfg = settings["slots"][slot]
    now = now or datetime.now()
    warnings: List[str] = []
    items: List[NewsItem] = []

    items.extend(collect_cctv(session, settings))
    items.extend(collect_cls(session, settings))
    if cfg.get("cwtx"):
        before = len(items)
        items.extend(collect_cwtx(session, settings, now))
        warnings.append(f"朝闻天下新增 {len(items) - before} 条")
    if cfg.get("xwlb"):
        before = len(items)
        items.extend(collect_xwlb(session, settings, now))
        warnings.append(f"新闻联播新增 {len(items) - before} 条")
    if cfg.get("foreign_sources"):
        before = len(items)
        items.extend(collect_xinhua(session, settings))
        items.extend(collect_huanqiu(session, settings))
        items.extend(collect_cankao(session, settings))
        warnings.append(f"国外源新增 {len(items) - before} 条")

    start, end = window_bounds(settings["slots"][slot], now)
    filtered = [it for it in items if _in_window(it, start, end)]
    warnings.append(f"采集原始 {len(items)} 条，窗口内 {len(filtered)} 条")

    # 财联社仅保留 政治/经济/科技 类内容：分类交给 LLM，先按关键词粗筛太重，这里保留全部
    # （分类在 LLM 阶段完成；财联社条目全部进入后续流程）
    return filtered, warnings


def _title_similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def filter_xwlb_duplicates(items: List[NewsItem], xwlb_items: List[NewsItem], threshold: float = 0.82) -> Tuple[List[NewsItem], int]:
    """过滤与《新闻联播》重复的条目（标题高度相似或互相包含）。"""
    if not xwlb_items:
        return items, 0
    refs = [normalize_title(it.title) for it in xwlb_items if it.title]
    refs = [r for r in refs if len(r) >= 4]
    if not refs:
        return items, 0
    kept: List[NewsItem] = []
    skipped = 0
    for it in items:
        na = normalize_title(it.title)
        if not na:
            kept.append(it)
            continue
        dup = False
        for ref in refs:
            if ref in na or (len(ref) >= 6 and na in ref):
                dup = True
                break
            if SequenceMatcher(None, na, ref).ratio() >= threshold:
                dup = True
                break
        if dup:
            skipped += 1
        else:
            kept.append(it)
    return kept, skipped


def merge_items(
    items: List[NewsItem],
    settings: Settings,
    recent_fingerprints: Optional[Dict[str, str]] = None,
    recent_titles: Optional[List[str]] = None,
) -> Tuple[List[NewsItem], List[str]]:
    """去重合并：指纹合并 + 疑似复查；跨运行指纹/高相似标题跳过。"""
    warnings: List[str] = []
    recent_fingerprints = recent_fingerprints or {}
    recent_titles = recent_titles or []
    by_fp: Dict[str, NewsItem] = {}
    cross_run_skipped = 0

    for it in items:
        fp = fingerprint(it.title, it.url)
        if fp in recent_fingerprints:
            cross_run_skipped += 1
            continue
        if fp in by_fp:
            exist = by_fp[fp]
            if len(it.summary) > len(exist.summary):
                it.extra["merged_with"] = exist.url
                by_fp[fp] = it
            else:
                exist.extra.setdefault("merged_with", it.url)
            continue
        by_fp[fp] = it

    merged = list(by_fp.values())

    # 跨运行：与近 10 天已推送标题做高相似比对（>=0.86 视为同一事件）
    if recent_titles:
        kept: List[NewsItem] = []
        for it in merged:
            if any(_title_similarity(it.title, t) >= 0.86 for t in recent_titles):
                cross_run_skipped += 1
                continue
            kept.append(it)
        merged = kept

    # 运行内疑似重合复查：高相似标题对（LLM 复查）
    use_llm = settings["dedup"].get("use_llm_review", True)
    if use_llm and len(merged) <= 400:
        dup_pairs: List[Tuple[int, int]] = []
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                if _title_similarity(merged[i].title, merged[j].title) >= settings["dedup"].get("fuzzy_min_similarity", 0.72):
                    dup_pairs.append((i, j))
        if dup_pairs:
            from src.llm import review_duplicates  # 延迟导入避免循环

            confirmed = review_duplicates(merged, dup_pairs, settings)
            if confirmed:
                drop_idx = set()
                for i, j in confirmed:
                    drop_idx.add(j)
                    merged[i].extra.setdefault("merged_with", merged[j].url)
                merged = [it for k, it in enumerate(merged) if k not in drop_idx]
                warnings.append(f"LLM 复查确认合并 {len(confirmed)} 组")
    if cross_run_skipped:
        warnings.append(f"跨运行去重跳过 {cross_run_skipped} 条")
    return merged, warnings
