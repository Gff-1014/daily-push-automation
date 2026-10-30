# -*- coding: utf-8 -*-
"""补录近期已用/热门阅读文章到 state.reading_used，避免上线去重后立刻撞重复。

做法：
1. 显式补录今天（2026-10-20 早间）实际发出的 NPR Tech 文章；
2. 把早间/晚间各新闻源当前的前 3 篇一并标记为已用（近期最可能重复的热门文章）。

用法：python scripts/backfill_reading_used.py [--dry-run]
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
from src.cet4.fetch import make_session  # noqa: E402
from src.cet4.reading import _feed_urls, fetch_rss  # noqa: E402

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
    feeds = cfg.get("reading", {}).get("feeds", {})
    session = make_session("Mozilla/5.0", 20)

    sid, skey = _credentials()
    cli = CosRestClient(bucket, region, sid, skey)
    state = json.loads(cli.get_object(key))
    used = list(state.get("reading_used", []))
    added: list[str] = []

    def add(key: str) -> None:
        if key and key not in used:
            used.append(key)
            added.append(key)

    # 1) 今天早间实际发出的文章（NPR Tech 首篇）
    tech_url = feeds.get("npr_tech", "")
    if tech_url:
        try:
            items = fetch_rss(session, tech_url, limit=3)
            if items:
                add(items[0].get("link") or items[0].get("title"))
                print(f"[补录] 今日早间实际文章：{items[0].get('title')[:60]}")
        except Exception as exc:  # noqa: BLE001
            print(f"[补录] 读取 npr_tech 失败：{exc!r}")

    # 2) 早间 + 晚间各源当前前 3 篇
    for slot in ("morning", "evening"):
        for url in _feed_urls(cfg, slot):
            try:
                items = fetch_rss(session, url, limit=3)
            except Exception as exc:  # noqa: BLE001
                print(f"[补录] {slot} 源失败 {url[:50]}: {exc!r}")
                continue
            for it in items:
                add(it.get("link") or it.get("title"))
    print(f"共补录 {len(added)} 篇，reading_used 现有 {len(used)} 篇")
    if dry_run:
        print("[dry-run] 未写入")
        return 0

    state["reading_used"] = used[-300:]
    cli.put_object(key, json.dumps(state, ensure_ascii=False))
    local = ROOT / "data" / "cet4" / "state.json"
    local.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已写入 COS 与本地 state.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
