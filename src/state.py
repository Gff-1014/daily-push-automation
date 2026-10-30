# -*- coding: utf-8 -*-
"""运行状态（本地文件版；云端部署时切换 COS 版）。"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.config import Settings


class StateStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = Path(settings["state"]["local_file"])
        self.days = int(settings["state"].get("fingerprint_days", 10))
        self.data: dict = {
            "last_success_time": None,
            "fingerprints": {},   # fp -> YYYY-MM-DD
            "recent_titles": [],  # [{"title": ..., "date": ...}]
            "alert_count": 0,
            "paused": False,
            "pending_summary": None,
        }
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    self.data.update(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass
        self.prune()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def prune(self) -> None:
        cutoff = date.today() - timedelta(days=self.days)
        self.data["fingerprints"] = {
            fp: d for fp, d in self.data.get("fingerprints", {}).items() if d >= cutoff.isoformat()
        }
        self.data["recent_titles"] = [
            t for t in self.data.get("recent_titles", []) if t.get("date", "") >= cutoff.isoformat()
        ]

    def fingerprint_map(self) -> Dict[str, str]:
        return dict(self.data.get("fingerprints", {}))

    def recent_titles(self) -> List[str]:
        return [t.get("title", "") for t in self.data.get("recent_titles", [])]

    def record_pushed(self, items) -> None:
        today = date.today().isoformat()
        from src.collector.normalize import fingerprint

        for it in items:
            self.data["fingerprints"][fingerprint(it.title, it.url)] = today
            self.data["recent_titles"].append({"title": it.title, "date": today})
        # 控制 recent_titles 规模
        self.data["recent_titles"] = self.data["recent_titles"][-5000:]

    def set_success(self, when: Optional[str] = None) -> None:
        self.data["last_success_time"] = when or datetime.now().isoformat(timespec="seconds")
        self.data["alert_count"] = 0
        self.data["pending_summary"] = None

    def register_email_failure(self) -> int:
        self.data["alert_count"] = int(self.data.get("alert_count", 0)) + 1
        return self.data["alert_count"]

    def pause(self) -> None:
        self.data["paused"] = True

    def resume(self) -> None:
        self.data["paused"] = False
        self.data["alert_count"] = 0

    @property
    def paused(self) -> bool:
        return bool(self.data.get("paused", False))

    def reset(self) -> None:
        """手动修复后恢复：清除暂停与失败计数，保留指纹与待发总结。"""
        self.data["paused"] = False
        self.data["alert_count"] = 0
        self.save()


class CosStateStore(StateStore):
    """COS 持久化版状态（腾讯云 SCF 云端使用）。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = Path(settings["state"]["local_file"])
        self.days = int(settings["state"].get("fingerprint_days", 10))
        self._bucket = settings["state"].get("cos_bucket", "")
        self._region = settings["state"].get("cos_region", "")
        self._key = "news-summary/state.json"
        self._client = None
        self.data: dict = {
            "last_success_time": None,
            "fingerprints": {},
            "recent_titles": [],
            "alert_count": 0,
            "paused": False,
            "pending_summary": None,
        }
        self.load()

    def _get_client(self):
        from src.cos_client import CosRestClient

        if self._client is None:
            import os

            self._client = CosRestClient(
                bucket=self._bucket,
                region=self._region,
                secret_id=os.environ.get("TENCENT_SECRET_ID", ""),
                secret_key=os.environ.get("TENCENT_SECRET_KEY", ""),
            )
        return self._client

    def load(self) -> None:
        if not self._bucket:
            return
        try:
            raw = self._get_client().get_object(self._key)
            if raw:
                self.data.update(json.loads(raw))
        except Exception:  # noqa: BLE001
            pass
        self.prune()

    def save(self) -> None:
        if not self._bucket:
            return
        self._get_client().put_object(self._key, json.dumps(self.data, ensure_ascii=False))

def make_state(settings: Settings, force_local: bool = False) -> StateStore:
    if not force_local and settings["state"].get("cos_bucket"):
        return CosStateStore(settings)
    return StateStore(settings)
