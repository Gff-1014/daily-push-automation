# -*- coding: utf-8 -*-
"""预览新版阅读渲染：下划线+脚标、字号、词距（不发邮件）。"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.vocab.config import load_vocab_config  # noqa: E402
from src.vocab.plan import build_plan  # noqa: E402
from src.vocab.reading import build_reading  # noqa: E402
from src.vocab.render import render_email, word_lookup  # noqa: E402
from src.vocab.state import VocabState  # noqa: E402
from src.vocab.words import group_map, load_words  # noqa: E402


def main() -> int:
    cfg = load_vocab_config()
    tmp = Path(tempfile.mkdtemp()) / "state.json"
    tmp.write_text(
        json.dumps(
            {
                "started_on": "2026-08-27",
                "cursors": {"6研共有": 41, "6级独有": 7, "考研独有": 4, "小初共有": 19},
                "learned": {},
                "email_failures": 0,
                "paused": False,
                "pending_body": None,
                "day_plan": None,
                "last_run": None,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cfg["state_file"] = str(tmp)
    items = load_words(cfg)
    groups = group_map(items)
    lookup = word_lookup(items)
    state = VocabState(cfg)
    plan = build_plan(cfg, state, groups, date(2026, 8, 28), "morning")
    reading = build_reading(cfg, date(2026, 8, 28), "morning")
    total_new = sum(len(v) for v in plan["new"].values())
    learned = sum(state.cursor(g) for g in ["6研共有", "6级独有", "考研独有", "小初共有"]) + total_new
    subject, html = render_email(cfg, plan, reading, lookup, learned)
    print("SUBJECT:", subject)
    print("翻译可用:", "不可用" not in (reading.get("translation") or ""))
    print("文章词数:", len(reading.get("article", "").split()))
    print("文章字号24px:", "font-size:24px" in html)
    print("词距word-spacing:", "word-spacing:0.3em" in html)
    m = re.search(r"三、今日阅读.*?<div style=\"font-size:24px;line-height:1.9;word-spacing:0.3em;\">(.*?)</div>", html, re.S)
    if m:
        seg = m.group(1)
        print("--- 文章开头 900 字符（含标注）---")
        print(seg[:900])
        print("...")
        print("u 标签数:", seg.count("<u "), "| sup 标签数:", seg.count("<sup"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
