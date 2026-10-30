# -*- coding: utf-8 -*-
"""cet4 配置加载：config/cet4.yaml。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_FILE = ROOT / "config" / "cet4.yaml"

DEFAULT: Dict[str, Any] = {
    "words_file": "data/cet4/words.json",
    "state_file": "data/cet4/state.json",
    "output_dir": "data/cet4/output",
    "plan_days": 100,
    "end_date": "2026-12-12",
    "final_review_days": 14,
    "morning_ratio": 0.5,
    "srs_intervals": [0, 1, 2, 4, 7, 15, 30],
    "review_per_push_max": 20,             # 每次推送复习词上限
    "review_target_min": 15,               # 每次推送复习词目标下限（到期不足时按最早待复习补齐）
    "review_exclude_groups": ["基础词", "基础补强"],   # 复习板块只推四级大纲词
    "http": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "timeout": 15,
    },
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "temperature": 0.2,
        "timeout": 120,
        "max_retries": 2,
        "json_mode": True,
    },
    "listening": {
        "enabled": True,
        "max_chars": 3000,
        "cos_key_prefix": "cet4/listening/",
        "cos_bucket": "",                        # 由环境变量 CET4_MEDIA_BUCKET 注入
        "cos_region": "ap-guangzhou",
        "url_expire_days": 180,                  # 预签名链接有效期（天），到期后旧邮件链接失效
        "speeds": [1.25, 1.0, 0.75],
        "excerpt_min": 30,           # 摘选时长下限（秒）
        "excerpt_max": 45,           # 摘选时长上限（秒）
        "attach_mp3": False,         # True = 把当日 mp3 作为邮件附件发送（下载失败自动回退为链接）
        "sources": {
            "tingroom_voa": "http://www.tingroom.com/voa/",
        },
    },
    "cne": {
        "enabled": True,
    },
    "email": {
        "enabled": True,
        "webhook_url": "",
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "timeout": 30,
        "retries": 3,
        "alert_after_failures": 3,
    },
    "cos": {"bucket": "", "region": "ap-guangzhou", "key": "cet4/state.json"},
    "timezone": "Asia/Shanghai",
}


def load_cet4_config(path: str | os.PathLike = CONFIG_FILE) -> Dict[str, Any]:
    _load_dotenv(ROOT / ".env")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    cet4 = data.get("cet4", {})
    cfg = {**DEFAULT, **cet4}
    listening = cfg.setdefault("listening", {})
    if os.environ.get("CET4_MEDIA_BUCKET"):
        listening["cos_bucket"] = os.environ["CET4_MEDIA_BUCKET"]
    if os.environ.get("MEDIA_PROXY_BASE_URL"):
        listening["proxy_base_url"] = os.environ["MEDIA_PROXY_BASE_URL"]
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
