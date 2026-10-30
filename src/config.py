# -*- coding: utf-8 -*-
"""配置加载：YAML + 环境变量。"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config" / "config.yaml"


class Settings:
    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data
        self.deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        self.juhe_api_key = os.environ.get("JUHE_API_KEY", "")

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    @property
    def raw(self) -> Dict[str, Any]:
        return self._data


_settings: Settings | None = None


def load_settings(path: str | os.PathLike = CONFIG_FILE) -> Settings:
    global _settings
    os.environ.setdefault("TZ", "Asia/Shanghai")
    if hasattr(time, "tzset"):
        time.tzset()
    _load_dotenv(ROOT / ".env")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    state = data.setdefault("state", {})
    if os.environ.get("COS_BUCKET"):
        state["cos_bucket"] = os.environ["COS_BUCKET"]
    if os.environ.get("COS_REGION"):
        state["cos_region"] = os.environ["COS_REGION"]
    _settings = Settings(data)
    return _settings


def get_settings() -> Settings:
    if _settings is None:
        return load_settings()
    return _settings


def _load_dotenv(path) -> None:
    """极简 .env 加载：不覆盖已有环境变量。"""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
