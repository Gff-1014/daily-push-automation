# -*- coding: utf-8 -*-
"""vocab 配置加载：config/vocab.yaml。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_FILE = ROOT / "config" / "vocab.yaml"

DEFAULT: Dict[str, Any] = {
    "words_file": "data/vocab/words.json",
    "state_file": "data/vocab/state.json",
    "output_dir": "data/vocab/output",
    "plan_days": 100,
    "end_date": "",
    "final_review_days": 14,
    "morning_ratio": 0.5,
    "srs_intervals": [0, 1, 2, 4, 7, 15, 30],
    "review_per_push_max": 25,
    "email": {
        "enabled": True,
        "webhook_url": "",
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "timeout": 30,
        "retries": 3,
        "alert_after_failures": 3,
    },
    "cos": {"bucket": "", "region": "ap-guangzhou", "key": "vocab/state.json"},
    "timezone": "Asia/Shanghai",
}


def load_vocab_config(path: str | os.PathLike = CONFIG_FILE) -> Dict[str, Any]:
    _load_dotenv(ROOT / ".env")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    vocab = data.get("vocab", {})
    cfg = {**DEFAULT, **vocab}
    cos = cfg.setdefault("cos", {})
    if os.environ.get("COS_BUCKET"):
        cos["bucket"] = os.environ["COS_BUCKET"]
    cfg["root"] = str(ROOT)
    return cfg


def _load_dotenv(path) -> None:
    """只读加载 .env（不覆盖已有环境变量，不修改文件）。"""
    if not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
