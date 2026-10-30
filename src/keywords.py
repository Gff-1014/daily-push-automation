# -*- coding: utf-8 -*-
"""关键词重要度评分（config/keywords.json）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from src.config import ROOT
from src.models import NewsItem


class KeywordScorer:
    def __init__(self, path: str | Path = ROOT / "config" / "keywords.json") -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.tiers: Dict[str, float] = {str(k): float(v) for k, v in data.get("tiers", {}).items()}
        self.cap = float(data.get("score_cap", 30))
        self.words: List[Tuple[str, str]] = []  # (word, tier)
        self.marker_words: List[str] = []
        for w in data.get("words", []):
            word, tier = str(w.get("word", "")).strip(), str(w.get("tier", ""))
            if word:
                self.words.append((word, tier))
                if w.get("category") == "新词标记":
                    self.marker_words.append(word)

    def score(self, item: NewsItem, match_chars: int = 500) -> Tuple[float, List[str]]:
        text = item.title + "。" + (item.summary or "")[:match_chars]
        marker_hit = any(m in text for m in self.marker_words)
        total = 0.0
        hit_words: List[str] = []
        for word, tier in self.words:
            if word in text:
                hit_words.append(word)
                weight = float(self.tiers.get(tier, 2))
                if marker_hit and tier != "重大":
                    weight = max(weight, float(self.tiers.get("重大", 10)))
                total += weight
        return min(total, self.cap) / self.cap, hit_words
