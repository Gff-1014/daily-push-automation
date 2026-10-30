# -*- coding: utf-8 -*-
"""每日学习计划：新词（按配额）+ 复习（SRS 到期）。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from src.cet4.srs import due_words, intervals_of, mark_learned, mark_reviewed
from src.cet4.state import GROUPS, VocabState
from src.cet4.words import daily_quota, group_map, split_quota, take_new_words


def build_plan(
    cfg: Dict[str, Any],
    state: VocabState,
    groups: Dict[str, List[dict]],
    today: date,
    slot: str,
) -> Dict[str, Any]:
    """生成某次推送的计划：{date, day_no, quota, new, review}。"""
    totals = {g: len(groups.get(g, [])) for g in GROUPS}
    dp = state.data.get("day_plan") or {}
    if dp.get("date") == today.isoformat():
        # 当天配额已定：早间取未推部分，晚间取早间剩余
        day_q = {g: int(dp["quota"].get(g, 0)) for g in GROUPS}
        if slot == "morning":
            taken = dp.get("morning_taken", {})
            new_q = {g: max(0, day_q[g] - int(taken.get(g, 0))) for g in GROUPS}
        else:
            mt = dp.get("morning_taken", {})
            et = dp.get("evening_taken", {})
            new_q = {
                g: max(0, day_q[g] - int(mt.get(g, 0)) - int(et.get(g, 0)))
                for g in GROUPS
            }
    else:
        day_q = daily_quota(cfg, state, totals, today)
        morning_q, evening_q = split_quota(day_q, float(cfg.get("morning_ratio", 0.5)))
        new_q = morning_q if slot == "morning" else evening_q
    new_words = take_new_words(groups, state, new_q)
    cap = int(cfg.get("review_per_push_max", 25))
    min_target = min(int(cfg.get("review_target_min", 0)), cap)
    exclude = set(str(x) for x in cfg.get("review_exclude_groups", []) or [])
    word_group = {it["word"]: g for g, items in groups.items() for it in items}

    def _allowed(word: str) -> bool:
        return not (exclude and word_group.get(word) in exclude)

    # 第一轮：SRS 到期的词（按到期时间排序）
    review = [w for w in due_words(state, today, max(cap, min_target) * 3) if _allowed(w)]
    # 第二轮：到期词不足目标下限时，从已学词里按「下次复习时间最早」补齐（相当于提前复习）
    if len(review) < min_target:
        learned = state.data.get("learned", {}) or {}
        extra = [w for w in learned if w not in review and _allowed(w)]
        extra.sort(key=lambda w: (learned[w].get("next_review", ""), learned[w].get("learned_on", "")))
        review += extra[: min_target - len(review)]
    review = review[:cap]
    return {
        "date": today,
        "day_no": state.day_no(today),
        "slot": slot,
        "quota": day_q,
        "new": new_words,
        "review": review,
    }


def commit_plan(cfg: Dict[str, Any], state: VocabState, plan: Dict[str, Any]) -> None:
    """邮件发送成功后提交：推进游标、登记新词与复习。"""
    today = plan["date"]
    state.ensure_started(today)
    intervals = intervals_of(cfg)
    taken = {g: len(plan["new"].get(g, [])) for g in GROUPS}
    for g in GROUPS:
        words = plan["new"].get(g, [])
        if words:
            state.advance_cursor(g, len(words))
            for it in words:
                mark_learned(state, it["word"], today)
    for w in plan["review"]:
        mark_reviewed(state, w, today, intervals)
    dp = dict(state.data.get("day_plan") or {})
    if plan["slot"] == "morning":
        state.data["day_plan"] = {
            "date": today.isoformat(),
            "quota": {g: int(plan["quota"].get(g, 0)) for g in GROUPS},
            "morning_taken": taken,
            "evening_taken": dp.get("evening_taken", {}) if dp.get("date") == today.isoformat() else {g: 0 for g in GROUPS},
        }
    else:
        if dp.get("date") == today.isoformat():
            dp["evening_taken"] = taken
            state.data["day_plan"] = dp
    state.data["last_run"] = {"date": today.isoformat(), "slot": plan["slot"]}
    state.save()


def simulate(cfg: Dict[str, Any], groups: Dict[str, List[dict]], days: int, start: date) -> List[Dict[str, Any]]:
    """预览模拟：返回每日各组新词数与累计总数（不写真实状态）。"""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    with TemporaryDirectory(prefix="cet4_sim_") as tmp:
        sim_cfg = {**cfg, "state_file": str(Path(tmp) / "state.json")}
        state = VocabState(sim_cfg)
        state.ensure_started(start)
        rows = []
        for i in range(days):
            today = start + timedelta(days=i)
            morning = build_plan(sim_cfg, state, groups, today, "morning")
            commit_plan(sim_cfg, state, morning)
            evening = build_plan(sim_cfg, state, groups, today, "evening")
            commit_plan(sim_cfg, state, evening)
            total = sum(state.cursor(g) for g in GROUPS)
            rows.append(
                {
                    "day": i + 1,
                    "date": today.isoformat(),
                    "quota": morning["quota"],
                    "learned_total": total,
                }
            )
        return rows
