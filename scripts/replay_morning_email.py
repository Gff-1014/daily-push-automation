# -*- coding: utf-8 -*-
"""用新版本重放指定日期的早间邮件并发送（不改动真实学习状态）。

用法:
    python scripts/replay_morning_email.py 2026-08-28

说明:
    - 从 COS 拉取真实状态，克隆到临时文件，保证新词/复习选择与真实进度一致；
    - 阅读部分重新抓取当日新闻 + LLM 改写翻译（可能因内容不同略有差异）；
    - 发送成功后真实状态不写入任何变更。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deploy.deploy_vocab import _credentials, _load_dotenv  # noqa: E402
from src.cos_client import CosRestClient  # noqa: E402
from src.vocab.config import load_vocab_config  # noqa: E402
from src.vocab.notifier import send_email  # noqa: E402
from src.vocab.plan import build_plan  # noqa: E402
from src.vocab.reading import build_reading  # noqa: E402
from src.vocab.render import render_email, word_lookup  # noqa: E402
from src.vocab.state import VocabState  # noqa: E402
from src.vocab.words import group_map, load_words  # noqa: E402

STATE_KEY = "vocab/state.json"


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python scripts/replay_morning_email.py YYYY-MM-DD")
        return 1
    replay_date = date.fromisoformat(sys.argv[1])

    cfg = load_vocab_config()
    env = _load_dotenv()
    bucket = (cfg.get("cos", {}) or {}).get("bucket", "") or env.get("COS_BUCKET", "")
    if not bucket:
        print("[回测] 请在 .env 中配置 COS_BUCKET 后重试")
        return 1
    cli = CosRestClient(
        bucket,
        "ap-guangzhou",
        env.get("TENCENTCLOUD_SECRET_ID", ""),
        env.get("TENCENTCLOUD_SECRET_KEY", ""),
    )
    raw = cli.get_object(STATE_KEY)
    if not raw:
        print("[回测] COS 无状态，无法重放")
        return 1
    cloud_state = json.loads(raw)

    tmp = Path(tempfile.mkdtemp(prefix="vocab_replay_"))
    tmp_state = tmp / "state.json"
    clone = dict(cloud_state)
    day_plan = clone.get("day_plan") or {}
    if day_plan.get("date") == replay_date.isoformat():
        # 回退游标到当天早间推送前，保证新词选择与真实早间一致
        mt = day_plan.get("morning_taken", {})
        cursors = {g: int(clone["cursors"].get(g, 0)) - int(mt.get(g, 0)) for g in clone["cursors"]}
        clone["cursors"] = cursors
    clone.pop("day_plan", None)
    clone.pop("pending_body", None)
    tmp_state.write_text(json.dumps(clone, ensure_ascii=False), encoding="utf-8")
    replay_cfg = {**cfg, "state_file": str(tmp_state)}

    items = load_words(cfg)
    groups = group_map(items)
    lookup = word_lookup(items)
    state = VocabState(replay_cfg)

    plan = build_plan(replay_cfg, state, groups, replay_date, "morning")
    # 回退当天早间新词的 learned 记录（标题计数与复习状态与真实早间一致）
    morning_words = {it["word"] for v in plan["new"].values() for it in v}
    state.data["learned"] = {k: v for k, v in state.data.get("learned", {}).items() if k not in morning_words}
    reading = build_reading(cfg, replay_date, "morning")
    total_new = sum(len(v) for v in plan["new"].values())
    learned_total = sum(state.cursor(g) for g in ["6研共有", "6级独有", "考研独有", "小初共有"]) + total_new
    subject, body = render_email(replay_cfg, plan, reading, lookup, learned_total)

    print("标题:", subject)
    print("新词:", total_new, "| 阅读词数:", len(reading.get("article", "").split()), "| 翻译可用:", bool(reading.get("translation") and "不可用" not in reading.get("translation", "")))
    print("发送中 ...")
    ok = send_email(subject, body, cfg)
    shutil.rmtree(tmp, ignore_errors=True)
    print("发送成功" if ok else "发送失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
