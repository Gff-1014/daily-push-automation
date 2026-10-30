# -*- coding: utf-8 -*-
"""前 15 天推送量与"除去前 15 天"后的剩余词数分析。

用法：python scripts/cet4_first15_analysis.py [前N天，默认15]
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.cet4.config import load_cet4_config  # noqa: E402
from src.cet4.plan import simulate  # noqa: E402
from src.cet4.state import GROUPS  # noqa: E402
from src.cet4.words import group_map, load_words  # noqa: E402


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    cfg = load_cet4_config("config/cet4.yaml")
    items = load_words(cfg)
    groups = group_map(items)
    totals = {g: len(groups[g]) for g in GROUPS}
    start = date(2026, 8, 29)
    rows = simulate(cfg, groups, n, start)

    cum = {g: 0 for g in GROUPS}
    print(f"{'天数':>4}  {'日期':<12}  {'大纲/基础/补强':>14}  {'当日':>4}  {'累计':>5}")
    for r in rows:
        q = r["quota"]
        for g in GROUPS:
            cum[g] += q[g]
        detail = f"{q['四级大纲词']}/{q['基础词']}/{q['基础补强']}"
        print(f"{r['day']:>4}  {r['date']:<12}  {detail:>14}  {sum(q.values()):>4}  {r['learned_total']:>5}")

    print()
    print(f"前 {n} 天累计推送：{cum} 合计 {sum(cum.values())}")
    rest = {g: totals[g] - cum[g] for g in GROUPS}
    print(f"除去前 {n} 天后的剩余：{rest} 合计 {sum(rest.values())}")
    # 新词期天数 = 开始日到考试日总天数 - 冲刺复习天数
    end = date.fromisoformat(cfg["end_date"])
    final_days = int(cfg.get("final_review_days", 14))
    new_word_days = (end - start).days + 1 - final_days
    left_days = new_word_days - n
    total_rest = sum(rest.values())
    day_from = start + __import__("datetime").timedelta(days=n)
    day_to = start + __import__("datetime").timedelta(days=new_word_days - 1)
    print(f"第 {n + 1} 天（{day_from}）→ 第 {new_word_days} 天（{day_to}），共 {left_days} 个新词日")
    print(f"这段时间平均需要：{total_rest / left_days:.1f} 词/天（第 15 天节奏为 57 词/天）")
    days_at_57 = max(1, -(-total_rest // 57))
    print(f"若按第 15 天节奏 57 词/天推：需 {days_at_57} 天，约 {day_from + __import__('datetime').timedelta(days=days_at_57 - 1)} 推完")
    return 0


if __name__ == "__main__":
    sys.exit(main())
