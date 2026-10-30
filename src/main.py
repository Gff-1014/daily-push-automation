# -*- coding: utf-8 -*-
"""每日流水线入口：python -m src.main morning|evening [--dry-run]"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.categories import CHANNEL_FALLBACK_CATEGORY
from src.collector.pipeline import collect_all, filter_xwlb_duplicates, merge_items, window_bounds
from src.collector.xwlb import collect_xwlb
from src.config import load_settings
from src.fetch import make_session
from src.formatter import SLOT_LABEL, format_summary
from src.heat import top_hot_words
from src.keywords import KeywordScorer
from src.llm import analyze_items
from src.models import NewsItem
from src.notifier import send_alert, send_email
from src.scoring import select_pushed
from src.state import make_state

def _apply_llm_results(items: List[NewsItem], results: Dict[int, dict], llm_ok: bool) -> List[str]:
    warnings: List[str] = []
    for idx, it in enumerate(items):
        r = results.get(idx)
        if r:
            it.category = r.get("category") or CHANNEL_FALLBACK_CATEGORY.get(it.channel, "杂类")
            it.llm_score = max(0.0, min(10.0, r.get("score", 0.0)))
            it.keywords = r.get("keywords", [])
            it.one_line_summary = r.get("summary", "")
        else:
            it.category = CHANNEL_FALLBACK_CATEGORY.get(it.channel, "杂类")
            it.llm_score = 5.0  # LLM 不可用时的中性分，保证流程可跑通
            it.one_line_summary = ""
    if not llm_ok:
        warnings.append("LLM 未配置或调用失败：分类用来源兜底，评分取中性值")
    return warnings


def run(slot: str, dry_run: bool = False, defer_email: bool = False, run_date=None) -> int:
    settings = load_settings()
    state = make_state(settings, force_local=run_date is not None)
    if run_date is not None:
        hour = {"morning": 8, "evening": 20}[slot]
        minute = {"morning": 30, "evening": 30}[slot]
        now = datetime.combine(run_date, datetime.min.time()).replace(hour=hour, minute=minute)
    else:
        now = datetime.now()
    label = SLOT_LABEL.get(slot, slot)

    if state.paused:
        print(f"[{label}] 系统处于暂停状态，跳过本次运行（需手动修复后运行恢复脚本）")
        return 0

    # 补发上次未送达总结
    pending = state.data.get("pending_summary")
    if pending and settings["email"].get("webhook_url"):
        if send_email(pending.get("subject", ""), pending.get("body", ""), settings):
            print("[邮件] 补发上次总结成功")
            state.set_success()
        else:
            print("[邮件] 补发上次总结失败")

    session = make_session(settings["collector"]["user_agent"], settings["collector"]["timeout"])
    items, warn1 = collect_all(session, settings, slot, now)
    merged, warn2 = merge_items(items, settings, state.fingerprint_map(), state.recent_titles())
    print(f"[{label}] 采集 {len(items)} → 合并 {len(merged)}")

    # 早间：与昨晚《新闻联播》重复的新闻不推送
    if slot == "morning" and settings["slots"]["morning"].get("skip_xwlb_duplicates", True):
        try:
            yesterday = now - timedelta(days=1)
            yesterday_run = yesterday.replace(hour=20, minute=30)
            xwlb_items = collect_xwlb(session, settings, yesterday_run)
            merged, skipped = filter_xwlb_duplicates(merged, xwlb_items)
            print(f"[去重] 昨晚新闻联播重复跳过 {skipped} 条")
        except Exception:  # noqa: BLE001
            print("[去重] 昨晚新闻联播拉取失败，跳过该去重步骤")

    results = {}
    llm_ok = bool(settings.deepseek_api_key) or os.environ.get("LLM_MOCK") == "1"
    if llm_ok:
        try:
            results = analyze_items(merged, settings)
        except Exception as exc:  # noqa: BLE001
            llm_ok = False
            print(f"[LLM] 失败：{exc}")
    warn3 = _apply_llm_results(merged, results, llm_ok)

    # 财联社仅作为 政治/经济/科技 三类补充来源
    cls_cats = set(settings["collector"]["cls"].get("categories", ["政治", "经济", "科技"]))
    merged = [it for it in merged if not (it.source == "财联社" and it.category not in cls_cats)]
    if len(merged) < len(results):
        print(f"[过滤] 财联社非目标分类剔除 {len(results) - len(merged)} 条")

    scorer = KeywordScorer()
    speed_list, sections, heat_ok = select_pushed(merged, session, settings, slot, scorer)
    pushed = [it for _, lst in sections for it in lst]
    print(f"[{label}] 推送 {len(pushed)} 条（热度可用: {heat_ok}）")

    window_start, window_end = window_bounds(settings["slots"][slot], now)
    text = format_summary(
        slot,
        window_start=window_start,
        window_end=window_end,
        speed_list=speed_list,
        sections=sections,
        include_links=settings["output"].get("include_links", True),
        hot_topics=top_hot_words(session, settings, 10),
    )

    try:
        out_dir = Path(settings["output"]["dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{now:%Y-%m-%d}-{label}.txt"
        out_file.write_text(text, encoding="utf-8")
        print(f"[输出] 已保存 {out_file}")
    except OSError:
        # 云端工作目录只读：写入 /tmp（仅本地排查用）
        tmp_dir = Path(tempfile.gettempdir()) / "news-summary"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        out_file = tmp_dir / f"{now:%Y-%m-%d}-{label}.txt"
        out_file.write_text(text, encoding="utf-8")
        print(f"[输出] 已保存到临时目录 {out_file}")

    if dry_run:
        print("=" * 40)
        print(text)
        print("=" * 40)
        return 0

    subject = f"{now.month}月{now.day}日新闻与热点（{label}）"
    if defer_email:
        # 云端：由 09:00 / 21:00 邮件触发器发送
        state.data["pending_summary"] = {"subject": subject, "body": text}
        state.record_pushed(pushed)
        state.save()
        print("[邮件] 已暂存，等待定时邮件触发器发送")
        return 0
    if send_email(subject, text, settings):
        print("[邮件] 发送成功")
        state.record_pushed(pushed)
        state.set_success()
        state.save()
        return 0

    print("[邮件] 发送失败")
    state.data["pending_summary"] = {"subject": subject, "body": text}
    failures = state.register_email_failure()
    limit = int(settings["email"].get("alert_after_failures", 3))
    if failures >= limit:
        alert_ok = send_alert("邮件发送连续失败，无法送达每日总结。", settings)
        state.pause()
        print(f"[告警] 已连续 {failures} 次失败，系统暂停；告警邮件发送: {alert_ok}")
    state.save()
    return 1


def send_pending_email() -> int:
    """邮件触发器：补发待发送的总结。"""
    settings = load_settings()
    state = make_state(settings)
    if state.paused:
        print("[邮件] 系统暂停中，不发送")
        return 0
    pending = state.data.get("pending_summary")
    if not pending:
        print("[邮件] 无待发送总结")
        return 0
    if send_email(pending.get("subject", ""), pending.get("body", ""), settings):
        print("[邮件] 发送成功")
        state.set_success()
        state.save()
        return 0
    print("[邮件] 发送失败")
    failures = state.register_email_failure()
    limit = int(settings["email"].get("alert_after_failures", 3))
    if failures >= limit:
        send_alert("邮件发送连续失败，无法送达每日总结。", settings)
        state.pause()
        print(f"[告警] 已连续 {failures} 次失败，系统暂停")
    state.save()
    return 1


TRIGGER_ROUTES = {
    "t0830": {"action": "run", "slot": "morning"},
    "t2030": {"action": "run", "slot": "evening"},
    "t0900": {"action": "email"},
    "t2100": {"action": "email"},
}


def _parse_timer_event(event) -> dict:
    """兼容腾讯云定时触发器事件格式：{"Type":"Timer","TriggerName":"t2030","Message":"自定义参数"}。"""
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except json.JSONDecodeError:
            event = {}
    if not isinstance(event, dict):
        event = {}
    msg = event.get("Message")
    if msg:
        try:
            parsed = json.loads(msg) if isinstance(msg, str) else msg
            if isinstance(parsed, dict):
                event = dict(event)
                event.update(parsed)
        except json.JSONDecodeError:
            pass
    route = TRIGGER_ROUTES.get(event.get("TriggerName", ""))
    if route:
        event.setdefault("action", route["action"])
        event.setdefault("slot", route.get("slot", "morning"))
    return event


def main_handler(event, context) -> int:
    """腾讯云 SCF 入口。支持事件：{"action":"run"|"email", "slot":"morning"|"evening"} 与定时触发器格式。"""
    event = _parse_timer_event(event)
    action = event.get("action", "run")
    if action == "email":
        return send_pending_email()
    if action == "resume":
        settings = load_settings()
        state = make_state(settings)
        state.reset()
        print("[恢复] 已清除暂停标记，尝试补发待发送总结")
        return send_pending_email()
    slot = event.get("slot", "morning")
    return run(slot, defer_email=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="央视网新闻文字总结")
    parser.add_argument("slot", choices=["morning", "evening"])
    parser.add_argument("--dry-run", action="store_true", help="不发送邮件、不更新状态")
    parser.add_argument("--defer-email", action="store_true", help="只暂存总结，等待邮件触发器发送")
    parser.add_argument("--date", type=str, default="", help="按指定日期运行（YYYY-MM-DD），用于回补")
    args = parser.parse_args()
    run_date = None
    if args.date:
        run_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    return run(args.slot, args.dry_run, defer_email=args.defer_email, run_date=run_date)


if __name__ == "__main__":
    sys.exit(main())
