# -*- coding: utf-8 -*-
"""词汇学习进度状态：新词游标 + 已学单词 SRS 记录（本地 JSON，可扩展 COS）。"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

GROUPS = ["6研共有", "6级独有", "考研独有", "小初共有"]


class VocabState:
    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg
        self.path = Path(cfg["state_file"])
        self.data: Dict[str, Any] = {
            "started_on": None,          # 首次学习日期 YYYY-MM-DD
            "cursors": {g: 0 for g in GROUPS},   # 各组已出队新词数
            "learned": {},               # word -> {learned_on, reviews, last_review, next_review}
            "email_failures": 0,
            "paused": False,
            "pending_body": None,
            "day_plan": None,          # {"date","quota","morning_taken","evening_taken"}
            "last_run": None,
        }
        self.load()

    # ---------- 持久化 ----------
    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self.data.update(raw)
        for g in GROUPS:
            self.data.setdefault("cursors", {}).setdefault(g, 0)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ---------- 日期与周期 ----------
    def ensure_started(self, today: date) -> None:
        if not self.data.get("started_on"):
            self.data["started_on"] = today.isoformat()

    def day_no(self, today: date) -> int:
        start = self.data.get("started_on")
        if not start:
            return 1
        return max(1, (today - date.fromisoformat(start)).days + 1)

    def new_word_days(self) -> int:
        """可推新词的总天数（end_date 设置时自动倒排并预留冲刺期）。"""
        end_str = str(self.cfg.get("end_date", "") or "").strip()
        if end_str and self.data.get("started_on"):
            end = date.fromisoformat(end_str)
            start = date.fromisoformat(self.data["started_on"])
            total = (end - start).days + 1
            final = int(self.cfg.get("final_review_days", 14))
            return max(1, total - final)
        return int(self.cfg.get("plan_days", 100))

    # ---------- 新词游标 ----------
    def cursor(self, group: str) -> int:
        return int(self.data["cursors"].get(group, 0))

    def advance_cursor(self, group: str, n: int) -> None:
        self.data["cursors"][group] = self.cursor(group) + n

    # ---------- 复习记录 ----------
    def mark_learned(self, word: str, today: date) -> None:
        iso = today.isoformat()
        self.data["learned"][word] = {
            "learned_on": iso,
            "reviews": 0,
            "last_review": iso,
            "next_review": iso,  # 当天晚间回测
        }

    def mark_reviewed(self, word: str, today: date, intervals: List[int]) -> None:
        rec = self.data["learned"].get(word)
        if not rec:
            return
        from datetime import timedelta

        rec["reviews"] = int(rec.get("reviews", 0)) + 1
        rec["last_review"] = today.isoformat()
        idx = min(rec["reviews"], len(intervals) - 1)
        rec["next_review"] = (today + timedelta(days=intervals[idx])).isoformat()

    def due_reviews(self, today: date, cap: int) -> List[str]:
        iso = today.isoformat()
        due = [
            w for w, rec in self.data["learned"].items()
            if rec.get("next_review", "") <= iso
        ]
        due.sort(key=lambda w: (self.data["learned"][w]["next_review"], self.data["learned"][w]["learned_on"]))
        return due[: max(0, cap)]

    # ---------- 邮件失败 ----------
    def register_email_failure(self) -> int:
        self.data["email_failures"] = int(self.data.get("email_failures", 0)) + 1
        return self.data["email_failures"]

    def reset_failures(self) -> None:
        self.data["email_failures"] = 0

    @property
    def paused(self) -> bool:
        return bool(self.data.get("paused", False))

    def set_pending(self, subject: str, body: str) -> None:
        self.data["pending_body"] = {"subject": subject, "body": body}

    def pending(self) -> dict | None:
        return self.data.get("pending_body")

    def clear_pending(self) -> None:
        self.data["pending_body"] = None

    def pause(self) -> None:
        self.data["paused"] = True

    def resume(self) -> None:
        self.data["paused"] = False
        self.data["email_failures"] = 0


class CosVocabState(VocabState):
    """COS 持久化版（SCF 云端用）：本地落盘 + 上传云端，读取时云端优先。"""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        cos = cfg.get("cos", {})
        self._bucket = cos.get("bucket", "")
        self._region = cos.get("region", "ap-guangzhou")
        self._key = cos.get("key", "vocab/state.json")
        self._client = None
        super().__init__(cfg)

    def _get_client(self):
        import os

        from src.cos_client import CosRestClient

        if self._client is None:
            self._client = CosRestClient(
                bucket=self._bucket,
                region=self._region,
                secret_id=os.environ.get("TENCENT_SECRET_ID", "") or os.environ.get("TENCENTCLOUD_SECRET_ID", ""),
                secret_key=os.environ.get("TENCENT_SECRET_KEY", "") or os.environ.get("TENCENTCLOUD_SECRET_KEY", ""),
            )
        return self._client

    def load(self) -> None:
        super().load()
        if not self._bucket:
            return
        try:
            raw = self._get_client().get_object(self._key)
            if raw:
                self.data.update(json.loads(raw))
                for g in GROUPS:
                    self.data.setdefault("cursors", {}).setdefault(g, 0)
        except Exception:  # noqa: BLE001
            pass

    def save(self) -> None:
        try:
            super().save()
        except OSError:
            # SCF 运行目录可能只读：本地落盘失败不阻断 COS 上传
            pass
        if not self._bucket:
            return
        try:
            self._get_client().put_object(self._key, json.dumps(self.data, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print(f"[COS] 状态上传失败：{exc!r}")


def make_vocab_state(cfg: Dict[str, Any]) -> VocabState:
    if cfg.get("cos", {}).get("bucket"):
        return CosVocabState(cfg)
    return VocabState(cfg)
