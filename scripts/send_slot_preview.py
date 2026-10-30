# -*- coding: utf-8 -*-
"""预览测试：按当前正式状态生成推送邮件，发到指定邮箱。

特点：只读正式状态（优先 COS），在本进程临时副本上推进，不写回（不影响正式推送）。

用法：
    python scripts/send_slot_preview.py evening                # 单封晚间预览
    python scripts/send_slot_preview.py morning --date 2026-10-16
    python scripts/send_slot_preview.py --pair                 # 早晚各一封（晚间接在早间之后）
    python scripts/send_slot_preview.py evening --to a@b.com
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.cet4.cne import build_cne  # noqa: E402
from src.cet4.config import load_cet4_config  # noqa: E402
from src.cet4.listening import build_listening  # noqa: E402
from src.cet4.notifier import send_email  # noqa: E402
from src.cet4.plan import build_plan  # noqa: E402
from src.cet4.reading import build_reading  # noqa: E402
from src.cet4.render import render_email, word_lookup  # noqa: E402
from src.cet4.state import GROUPS, make_vocab_state  # noqa: E402
from src.cet4.words import group_map, load_words  # noqa: E402


def _load_real_state(cfg: dict) -> tuple:
    """读取正式状态：优先云端 COS（权威），失败回退本地 state.json。"""
    cos = cfg.get("cos", {}) or {}
    bucket = cos.get("bucket") or os.environ.get("COS_BUCKET", "")
    if not bucket:
        raise SystemExit("请在 .env 中配置 COS_BUCKET 后再预览")
    try:
        sys.path.insert(0, str(ROOT / "deploy"))
        from deploy_media_proxy import _credentials  # noqa: PLC0415
        from src.cet4.cos_client import CosRestClient  # noqa: PLC0415

        sid, skey = _credentials()
        cli = CosRestClient(bucket, cos.get("region", "ap-guangzhou"), sid, skey)
        raw = cli.get_object(cos.get("key", "cet4/state.json"))
        if raw:
            return json.loads(raw), "COS"
    except Exception as exc:  # noqa: BLE001
        print(f"[状态] 读取 COS 失败，改用本地文件：{exc!r}")
    path = Path(cfg["state_file"])
    return json.loads(path.read_text(encoding="utf-8")), "本地文件"


def _make_scratch_state(cfg: dict, real_state: dict):
    """构造临时状态对象：推进只落在临时文件，不影响正式状态。"""
    tmp_dir = tempfile.mkdtemp(prefix="cet4_preview_")
    scratch_cfg = {**cfg, "state_file": str(Path(tmp_dir) / "state.json"), "cos": {}}
    state = make_vocab_state(scratch_cfg)
    state.data.update(real_state)
    return scratch_cfg, state


def main() -> int:
    parser = argparse.ArgumentParser(description="生成并发送单次推送预览（不写状态）")
    parser.add_argument("slot", nargs="?", default="evening", choices=["morning", "evening"])
    parser.add_argument("--pair", action="store_true", help="早晚各发一封（晚间接在早间之后）")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--to", default=os.environ.get("MAIL_TO", ""), help="收件邮箱（默认取 MAIL_TO）")
    parser.add_argument("--config", default=str(ROOT / "config" / "cet4.yaml"))
    args = parser.parse_args()

    cfg = load_cet4_config(args.config)
    items = load_words(cfg)
    groups = group_map(items)
    lookup = word_lookup(items)
    real_state, source = _load_real_state(cfg)
    scratch_cfg, state = _make_scratch_state(cfg, real_state)
    today = date.fromisoformat(args.date)
    print(f"[状态] 来源：{source} | 游标：{real_state.get('cursors')}")

    slots = ["morning", "evening"] if args.pair else [args.slot]
    sent = 0
    for slot in slots:
        plan = build_plan(scratch_cfg, state, groups, today, slot)
        listening = build_listening(scratch_cfg, today, slot)
        reading = build_reading(scratch_cfg, today, slot, state)
        cne = build_cne(scratch_cfg, plan, today, slot, state)
        total_new = sum(len(v) for v in plan["new"].values())
        learned_total = sum(state.cursor(g) for g in GROUPS) + total_new
        subject, body = render_email(scratch_cfg, plan, reading, listening, cne, lookup, learned_total)

        counts = {g: len(plan["new"][g]) for g in GROUPS}
        print(f"预览 {args.date} {slot}：新词 {counts} 合计 {sum(counts.values())} 词 | 复习 {len(plan['review'])} 个")
        print(f"主题：{subject}")

        os.environ["MAIL_TO"] = args.to  # 仅本次进程内覆盖，不修改 .env
        ok = send_email(subject, body, scratch_cfg)
        print(("发送成功 → " if ok else "发送失败 → ") + args.to)
        sent += 1 if ok else 0

        # 在临时副本上推进（相当于该时段已推送），使下一时段衔接真实
        from src.cet4.plan import commit_plan  # noqa: PLC0415

        commit_plan(scratch_cfg, state, plan)
        if cne and cne.get("prompt"):
            state.record_cne(cne["prompt"])
        if reading and (reading.get("url") or reading.get("title")):
            state.record_reading(reading.get("url") or reading.get("title"))
    return 0 if sent == len(slots) else 1


if __name__ == "__main__":
    sys.exit(main())
