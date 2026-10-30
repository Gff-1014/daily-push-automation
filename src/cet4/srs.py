# -*- coding: utf-8 -*-
"""SRS 间隔复习：0(当天回测) → 1 → 2 → 4 → 7 → 15 → 30 天。"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from src.cet4.state import VocabState


def intervals_of(cfg: Dict[str, Any]) -> List[int]:
    return [int(x) for x in cfg.get("srs_intervals", [0, 1, 2, 4, 7, 15, 30])]


def due_words(state: VocabState, today: date, cap: int) -> List[str]:
    return state.due_reviews(today, cap)


def mark_learned(state: VocabState, word: str, today: date) -> None:
    state.mark_learned(word, today)


def mark_reviewed(state: VocabState, word: str, today: date, intervals: List[int]) -> None:
    state.mark_reviewed(word, today, intervals)
