# -*- coding: utf-8 -*-
"""四级备考进度分析：剩余词数、按剩余天数均摊的每日需求量、按固定节奏推完所需天数。

用法：python scripts/cet4_progress.py [YYYY-MM-DD]
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deploy"))

from deploy_media_proxy import _credentials  # noqa: E402
from src.cet4.config import load_cet4_config  # noqa: E402
from src.cet4.cos_client import CosRestClient  # noqa: E402
from src.cet4.plan import simulate  # noqa: E402
from src.cet4.state import GROUPS  # noqa: E402
from src.cet4.words import group_map, load_words  # noqa: E402

def main() -> int:
    today = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    cfg = load_cet4_config("config/cet4.yaml")
    cos = cfg.get("cos", {}) or {}
    bucket = cos.get("bucket", "")
    key = cos.get("key", "cet4/state.json")
    region = cos.get("region", "ap-guangzhou")
    if not bucket:
        print("请在 .env 中配置 COS_BUCKET 后重试")
        return 1
    items = load_words(cfg)
    groups = group_map(items)
    totals = {g: len(groups[g]) for g in GROUPS}

    sid, skey = _credentials()
    cli = CosRestClient(bucket, region, sid, skey)
    state = json.loads(cli.get_object(key))
    cursors = state["cursors"]
    remaining = {g: totals[g] - cursors[g] for g in GROUPS}
    start = date.fromisoformat(state["started_on"])
    end = date.fromisoformat(cfg["end_date"])
    final_days = int(cfg.get("final_review_days", 14))
    nd = (end - start).days + 1 - final_days          # 新词期天数
    day_no = (today - start).days + 1
    new_word_end = end - timedelta(days=final_days)

    print(f"今天：{today} | 第 {day_no} 天 | 新词期共 {nd} 天（{start} → {new_word_end}）")
    print(f"最近一次推送：{state.get('last_run')}")
    print()
    print(f"{'组别':<8}{'已推':>7}{'总量':>7}{'剩余':>7}{'进度':>8}")
    for g in GROUPS:
        pct = cursors[g] / totals[g] * 100
        print(f"{g:<8}{cursors[g]:>7}{totals[g]:>7}{remaining[g]:>7}{pct:>7.1f}%")
    print(
        f"{'合计':<8}{sum(cursors.values()):>7}{sum(totals.values()):>7}"
        f"{sum(remaining.values()):>7}{sum(cursors.values()) / sum(totals.values()) * 100:>7.1f}%"
    )
    print()

    rows = simulate(cfg, groups, max(day_no, 15), start)
    q15 = rows[14]["quota"]
    q_now = rows[day_no - 1]["quota"] if day_no <= len(rows) else None
    print(f"第 15 天（{start + timedelta(days=14)}）每日配额：{q15} = {sum(q15.values())} 词")
    if q_now:
        print(f"第 {day_no} 天（{today}）每日配额：{q_now} = {sum(q_now.values())} 词")
    print()

    total_remaining = sum(remaining.values())
    for label, days in (("含今天", nd - day_no + 1), ("从明天起", nd - day_no)):
        per = {g: math.ceil(remaining[g] / days) if remaining[g] else 0 for g in GROUPS}
        detail = " / ".join(f"{g} {per[g]}" for g in GROUPS)
        print(f"剩余 {days} 个推送日（{label}）：每天需 {sum(per.values())} 词（{detail}），平均 {total_remaining / days:.1f} 词/天")
    print()

    for label, rate in (
        ("按第 15 天节奏", q15),
        ("按今天节奏", q_now or {"四级大纲词": 34, "基础词": 16, "基础补强": 6}),
    ):
        total_rate = sum(rate.values())
        days_needed = max(math.ceil(remaining[g] / rate[g]) for g in GROUPS if rate[g])
        finish = today + timedelta(days=days_needed - 1)
        print(f"{label}（每天 {total_rate} 词：{'/'.join(str(rate[g]) for g in GROUPS)}）：需 {days_needed} 天，约 {finish} 推完")
    return 0


if __name__ == "__main__":
    sys.exit(main())
