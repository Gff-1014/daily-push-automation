# -*- coding: utf-8 -*-
"""HTTP 抓取基础工具：UA、超时、重试、编码修复（四级自包含副本）。"""
from __future__ import annotations

import time
from typing import Optional

import requests


def make_session(user_agent: str, timeout: int = 15) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent})
    s.timeout = timeout
    return s


def get_text(
    session: requests.Session,
    url: str,
    *,
    retries: int = 3,
    timeout: int = 15,
    headers: Optional[dict] = None,
    referer: str = "",
) -> str:
    """带重试与编码修复的 GET，返回文本。"""
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            h = dict(headers or {})
            if referer:
                h.setdefault("Referer", referer)
            resp = session.get(url, timeout=timeout, headers=h)
            resp.raise_for_status()
            if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "ascii"):
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(1.0 * attempt)
    raise RuntimeError(f"GET {url} 失败: {last_err!r}")
