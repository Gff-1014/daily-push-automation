# -*- coding: utf-8 -*-
"""四级备考推送：CLI + 腾讯云 SCF 入口。

用法:
    python -m src.cet4.main morning --date 2026-08-29           # dry-run 打印正文
    python -m src.cet4.main morning --date 2026-08-29 --commit   # 只提交状态不发邮件
    python -m src.cet4.main morning --date 2026-08-29 --send     # 发送邮件并提交状态
    python -m src.cet4.main morning --date 2026-08-29 --config config/cet4.test.yaml  # 测试配置
    python -m src.cet4.main --preview 100                        # 100 天配额预览
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from src.cet4.cne import build_cne
from src.cet4.config import CONFIG_FILE, load_cet4_config
from src.cet4.listening import build_listening
from src.cet4.notifier import send_alert, send_email
from src.cet4.plan import build_plan, commit_plan, simulate
from src.cet4.reading import build_reading
from src.cet4.render import render_email, render_plain, word_lookup
from src.cet4.state import GROUPS, make_vocab_state
from src.cet4.words import group_map, load_words


def _handle_failure(cfg, state, pending) -> int:
    n = state.register_email_failure()
    limit = int(cfg.get("email", {}).get("alert_after_failures", 3))
    if n >= limit:
        send_alert("四级单词邮件连续发送失败。", cfg)
        state.pause()
        print(f"[告警] 已连续 {n} 次失败，系统暂停")
    state.save()
    return 1


def _send_pending(cfg, state) -> int:
    pending = state.pending()
    if not pending:
        print("[邮件] 无待发送推送")
        return 0
    if send_email(pending["subject"], pending["body"], cfg):
        print("[邮件] 补发成功")
        state.clear_pending()
        state.reset_failures()
        state.save()
        return 0
    print("[邮件] 补发失败")
    return _handle_failure(cfg, state, pending)


def run_slot(
    cfg,
    state,
    groups,
    lookup,
    today,
    slot,
    *,
    send: bool,
    commit_only: bool,
    no_reading: bool = False,
) -> int:
    """生成 → 渲染 → 发送 → 提交/失败处理。send=False 时只打印。"""
    if state.paused:
        print(f"[{slot}] 系统暂停中，跳过（运行 resume 恢复）")
        return 0
    started_on = state.data.get("started_on")
    if started_on and today.isoformat() < started_on:
        print(f"[{slot}] 学习尚未开始（开始日 {started_on}），跳过本次推送")
        return 0
    pending = state.pending()
    if pending:
        if send:
            print("[邮件] 存在未送达推送，先补发")
            if _send_pending(cfg, state) != 0:
                return 1
        else:
            print("[邮件] 存在未送达推送，本次 dry-run 不发送")
            return 0

    plan = build_plan(cfg, state, groups, today, slot)
    if no_reading:
        reading, listening, cne = {}, {}, {}
    else:
        listening = build_listening(cfg, today, slot)
        reading = build_reading(cfg, today, slot, state)
        cne = build_cne(cfg, plan, today, slot, state)
    # 可选：把当日听力 mp3 作为邮件附件（下载失败自动回退为链接）
    attachment = None
    if listening and cfg.get("listening", {}).get("attach_mp3"):
        mp3_url = (
            (listening.get("files", {}) or {}).get("1.0")
            or listening.get("mp3_url", "")
        )
        if mp3_url:
            try:
                import requests

                resp = requests.get(mp3_url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                attachment = {
                    "filename": f"listening-{today.isoformat()}-{slot}.mp3",
                    "data": resp.content,
                }
                listening["attached"] = True
            except Exception as exc:  # noqa: BLE001
                print(f"[听力] 附件下载失败，仅保留链接：{exc!r}")
    total_new = sum(len(v) for v in plan["new"].values())
    learned_total = sum(state.cursor(g) for g in GROUPS) + total_new
    subject, body = render_email(cfg, plan, reading, listening, cne, lookup, learned_total)

    if not send:
        subject, body = render_plain(cfg, plan, reading, listening, cne, lookup, learned_total)
        print(subject)
        print("=" * 42)
        print(body)
        print("=" * 42)
        if commit_only:
            commit_plan(cfg, state, plan)
            print("--- 已提交状态（未发送邮件）---")
        else:
            print("--- dry-run：未发送邮件、未写入状态 ---")
        return 0

    if send_email(subject, body, cfg, attachment=attachment):
        print("[邮件] 发送成功")
        commit_plan(cfg, state, plan)
        if cne and cne.get("prompt"):
            state.record_cne(cne["prompt"])
        if reading and (reading.get("url") or reading.get("title")):
            state.record_reading(reading.get("url") or reading.get("title"))
        state.clear_pending()
        state.reset_failures()
        state.save()
        return 0
    print("[邮件] 发送失败")
    state.set_pending(subject, body)
    return _handle_failure(cfg, state, {"subject": subject, "body": body})


def main_handler(event: dict | None, context=None) -> int:
    """腾讯云 SCF 入口：
      1. 定时触发器：{"Type":"Timer","TriggerName":...,"Message":"{\"action\":...,\"slot\":...}"}
      2. 直接调用：  {"action": "run"|"email"|"resume", "slot": "morning"|"evening"}
    """
    event = event or {}
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except Exception:  # noqa: BLE001
            event = {}
    if not isinstance(event, dict):
        event = {}
    # 定时触发器把自定义入参放在 Message 字段（字符串），需解析后合并
    if isinstance(event.get("Message"), str):
        try:
            msg = json.loads(event["Message"])
        except Exception:  # noqa: BLE001
            msg = {}
        if isinstance(msg, dict):
            event = {**msg, **event}
    action = event.get("action", "run")
    cfg = load_cet4_config()
    if action == "email":
        return _send_pending(cfg, make_vocab_state(cfg))
    if action == "resume":
        state = make_vocab_state(cfg)
        state.resume()
        state.save()
        print("[恢复] 已清除暂停标记")
        return _send_pending(cfg, state)
    slot = event.get("slot", "morning")
    if slot not in ("morning", "evening"):
        slot = "morning"
    items = load_words(cfg)
    state = make_vocab_state(cfg)
    return run_slot(
        cfg,
        state,
        group_map(items),
        word_lookup(items),
        date.today(),
        slot,
        send=True,
        commit_only=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="四级备考推送")
    parser.add_argument("slot", nargs="?", choices=["morning", "evening"])
    parser.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--preview", type=int, metavar="N", help="模拟前 N 天配额")
    parser.add_argument("--send", action="store_true", help="发送邮件并提交状态")
    parser.add_argument("--commit", action="store_true", help="提交状态但不发邮件")
    parser.add_argument("--no-reading", action="store_true", help="跳过阅读部分（仅 dry-run）")
    parser.add_argument("--config", default=str(CONFIG_FILE), help="配置文件路径（默认 config/cet4.yaml）")
    parser.add_argument("--attach-mp3", action="store_true", help="把当日听力 mp3 作为邮件附件（测试用）")
    args = parser.parse_args()

    if args.send and args.commit:
        parser.error("--send 与 --commit 互斥")

    cfg = load_cet4_config(args.config)
    if args.attach_mp3:
        cfg.setdefault("listening", {})["attach_mp3"] = True
    items = load_words(cfg)
    groups = group_map(items)
    lookup = word_lookup(items)

    if args.preview:
        rows = simulate(cfg, groups, args.preview, date.fromisoformat(args.date))
        header = f"{'天':>3} {'日期':<12} " + " ".join(f"{g[:2]}:{'0':>3}" for g in GROUPS) + "  累计"
        print(header)
        for r in rows:
            q = r["quota"]
            print(
                f"{r['day']:>3} {r['date']:<12} "
                + " ".join(f"{g[:2]}:{q[g]:>3}" for g in GROUPS)
                + f"  {r['learned_total']:>5}"
            )
        return 0

    if not args.slot:
        parser.error("需指定 morning / evening，或使用 --preview")

    state = make_vocab_state(cfg)
    return run_slot(
        cfg,
        state,
        groups,
        lookup,
        date.fromisoformat(args.date),
        args.slot,
        send=args.send,
        commit_only=args.commit,
        no_reading=args.no_reading,
    )


if __name__ == "__main__":
    sys.exit(main())
