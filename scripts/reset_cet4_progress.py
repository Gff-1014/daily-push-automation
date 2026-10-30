# -*- coding: utf-8 -*-
"""重置四级备考推送进度：游标回退到第 15 天末，只保留前 15 天已推单词的 SRS 记录。

用途：重新分配剩余单词（例：58 天每天 75 词推完）。

用法：
    python scripts/reset_cet4_progress.py --dry-run    # 只看差异，不写入
    python scripts/reset_cet4_progress.py              # 写入 COS + 本地 state.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deploy"))

from deploy_media_proxy import _credentials  # noqa: E402
from src.cet4.config import load_cet4_config  # noqa: E402
from src.cet4.cos_client import CosRestClient  # noqa: E402
from src.cet4.state import GROUPS  # noqa: E402
from src.cet4.words import group_map, load_words  # noqa: E402

LOCAL_STATE = ROOT / "data" / "cet4" / "state.json"

# 第 15 天（2026-09-12）结束时的游标
RESET_CURSORS = {"四级大纲词": 510, "基础词": 240, "基础补强": 105}


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    cfg = load_cet4_config(ROOT / "config" / "cet4.yaml")
    cos = cfg.get("cos", {}) or {}
    bucket = cos.get("bucket", "")
    key = cos.get("key", "cet4/state.json")
    region = cos.get("region", "ap-guangzhou")
    if not bucket:
        print("请在 .env 中配置 COS_BUCKET 后重试")
        return 1
    groups = group_map(load_words(cfg))
    totals = {g: len(groups[g]) for g in GROUPS}

    sid, skey = _credentials()
    cli = CosRestClient(bucket, region, sid, skey)
    old = json.loads(cli.get_object(key))
    old_learned = old.get("learned", {})

    keep: dict = {}
    for g in GROUPS:
        for it in groups[g][: RESET_CURSORS[g]]:
            w = it["word"]
            rec = old_learned.get(w)
            keep[w] = rec if rec else {
                "learned_on": old["started_on"],
                "reviews": 0,
                "last_review": old["started_on"],
                "next_review": old["started_on"],
            }

    new_state = {
        "started_on": old["started_on"],
        "cursors": dict(RESET_CURSORS),
        "learned": keep,
        "email_failures": 0,
        "paused": False,
        "pending_body": None,
        "day_plan": None,
        "last_run": old.get("last_run"),
        "cne_used": old.get("cne_used", []),
    }

    print("游标：", old["cursors"], "→", new_state["cursors"])
    print(f"learned：{len(old_learned)} → {len(keep)} 个词（保留前 15 天已推单词）")
    remaining = {g: totals[g] - new_state["cursors"][g] for g in GROUPS}
    print("剩余（含今天未推部分）：", remaining, "合计", sum(remaining.values()))
    print("day_plan：", old.get("day_plan"), "→ None（今天按新配额重新计算）")
    print("cne_used 保留：", len(new_state["cne_used"]), "条")

    if dry_run:
        print("\n[dry-run] 未写入")
        return 0

    payload = json.dumps(new_state, ensure_ascii=False)
    cli.put_object(key, payload)
    LOCAL_STATE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_STATE.write_text(json.dumps(new_state, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n已写入 COS 与本地 state.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
