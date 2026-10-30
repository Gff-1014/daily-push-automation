# -*- coding: utf-8 -*-
"""DeepSeek LLM 客户端（四级自包含副本：仅通用 chat + JSON 解析）。"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

import requests


class LLMSettings:
    """四级 LLM 配置：读取 config/cet4.yaml 的 llm 段 + DEEPSEEK_API_KEY。"""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        self._llm: Dict[str, Any] = cfg.get("llm", {}) or {}

    def __getitem__(self, key: str) -> Any:
        return self._llm[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._llm.get(key, default)


def make_llm_settings(cfg: Dict[str, Any]) -> LLMSettings:
    return LLMSettings(cfg)


def _chat(
    settings: LLMSettings,
    messages: List[dict],
    *,
    max_tokens: int = 8000,
) -> Optional[str]:
    key = settings.deepseek_api_key
    if not key:
        return None
    url = f"{settings.get('base_url', 'https://api.deepseek.com/v1').rstrip('/')}/chat/completions"
    body: Dict = {
        "model": settings.get("model", "deepseek-v4-flash"),
        "messages": messages,
        "temperature": float(settings.get("temperature", 0.2)),
        "max_tokens": max_tokens,
    }
    if settings.get("json_mode", True):
        # DeepSeek 要求 response_format=json_object 时提示词中必须出现 "json" 字样，否则 400
        if not any(
            "json" in str(m.get("content", "")).lower()
            for m in messages
            if isinstance(m, dict)
        ):
            messages = [*messages, {"role": "user", "content": "请严格按 JSON 格式输出。"}]
            body["messages"] = messages
        body["response_format"] = {"type": "json_object"}
    last_err: Optional[Exception] = None
    for attempt in range(1, int(settings.get("max_retries", 2)) + 2):
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
                timeout=int(settings.get("timeout", 120)),
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if not content or not content.strip():
                finish = (data.get("choices") or [{}])[0].get("finish_reason", "")
                raise RuntimeError(
                    f"LLM 返回空内容（finish_reason={finish}）："
                    "推理过程可能占满 max_tokens，请调大该调用方的 max_tokens"
                )
            return content.strip()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"LLM 调用失败: {last_err!r}")


def chat(
    settings: LLMSettings,
    messages: List[dict],
    *,
    max_tokens: int = 8000,
) -> Optional[str]:
    """通用对话接口（四级阅读改写/翻译/听力翻译/汉译英等复用）。"""
    return _chat(settings, messages, max_tokens=max_tokens)


def parse_json(content: str) -> Optional[dict]:
    """解析 LLM 返回的 JSON（容忍前后杂质）。"""
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    start, end = content.find("{"), content.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None
