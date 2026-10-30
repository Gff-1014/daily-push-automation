# -*- coding: utf-8 -*-
"""DeepSeek LLM 客户端：批量分类/评分/概述 + 去重复查。"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

import requests

from src.config import Settings
from src.models import NewsItem

CATEGORIES = ["政治", "经济", "科技", "生活", "国际", "社会", "文化教育", "军事国防", "生态环境", "杂类"]

SYSTEM_PROMPT = """你是资深新闻编辑，负责对当日新闻做分类、重要度评分和一句话概括。
评分标准（0-10 分，可含一位小数）：从影响面、涉及人群数量、经济/民生影响程度、突发事件级别、政策含金量五个维度综合判断。
0-2 分：鸡毛蒜皮；3-5 分：普通新闻；6-8 分：重要新闻；9-10 分：重大新闻。
分类只能取：政治、经济、科技、生活、国际、社会、文化教育、军事国防、生态环境、杂类。
一句话概括 30-60 字，客观陈述，不评论。输出必须是合法 JSON。"""


def _chat(
    settings: Settings,
    messages: List[dict],
    *,
    max_tokens: int = 8000,
) -> Optional[str]:
    key = settings.deepseek_api_key
    if not key:
        return None
    llm = settings["llm"]
    url = f"{llm['base_url'].rstrip('/')}/chat/completions"
    body: Dict = {
        "model": llm["model"],
        "messages": messages,
        "temperature": llm.get("temperature", 0.2),
        "max_tokens": max_tokens,
    }
    if llm.get("json_mode", True):
        body["response_format"] = {"type": "json_object"}
    last_err: Optional[Exception] = None
    for attempt in range(1, llm.get("max_retries", 2) + 2):
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
                timeout=llm.get("timeout", 120),
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"LLM 调用失败: {last_err!r}")


def chat(
    settings: Settings,
    messages: List[dict],
    *,
    max_tokens: int = 8000,
) -> Optional[str]:
    """通用对话接口（供词汇阅读改写/翻译等复用）。"""
    return _chat(settings, messages, max_tokens=max_tokens)


def parse_json(content: str) -> Optional[dict]:
    """解析 LLM 返回的 JSON（容忍前后杂质）。"""
    return _try_json(content)


def _try_json(content: str) -> Optional[dict]:
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


def _item_text(item: NewsItem, limit: int) -> str:
    text = item.title
    if item.summary:
        text += "。" + item.summary[:limit]
    return text[:limit + 200]


def analyze_items(items: List[NewsItem], settings: Settings) -> Dict[int, dict]:
    """批量分类/评分/概述，返回 {原索引: 结果}。"""
    if os.environ.get("LLM_MOCK") == "1":
        return {
            i: {
                "category": _mock_category(it),
                "score": round(8.0 - (i % 4) * 0.7, 1),
                "keywords": [it.title[:8]],
                "summary": it.title[:45] + "。",
            }
            for i, it in enumerate(items)
        }
    llm = settings["llm"]
    batch_size = llm.get("batch_size", 20)
    limit = llm.get("input_chars", 800)
    results: Dict[int, dict] = {}
    batches = []
    for start in range(0, len(items), batch_size):
        batches.append((start, items[start : start + batch_size]))

    def _run_batch(pair) -> Dict[int, dict]:
        start, chunk = pair
        user_payload = {
            "items": [
                {"index": start + i, "title": it.title, "text": _item_text(it, limit)}
                for i, it in enumerate(chunk)
            ]
        }
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "请分析以下新闻，返回 JSON：{\"items\": [{\"index\": 0, \"category\": \"政治\", "
                    "\"score\": 8.5, \"keywords\": [\"关键词1\"], \"summary\": \"一句话概括\"}]}。"
                    "必须包含所有条目，不得遗漏。\n" + json.dumps(user_payload, ensure_ascii=False)
                ),
            },
        ]
        out: Dict[int, dict] = {}
        try:
            content = _chat(settings, messages)
            data = _try_json(content or "")
        except Exception:  # noqa: BLE001
            data = None
        if not data:
            return out
        for entry in data.get("items", []):
            try:
                idx = int(entry.get("index", -1))
            except (TypeError, ValueError):
                continue
            if idx < start or idx >= start + len(chunk):
                continue
            out[idx] = {
                "category": entry.get("category", ""),
                "score": float(entry.get("score", 0.0) or 0.0),
                "keywords": list(entry.get("keywords", []) or [])[:5],
                "summary": (entry.get("summary", "") or "").strip(),
            }
        return out

    workers = min(llm.get("parallel", 3), max(1, len(batches)))
    if workers <= 1:
        for pair in batches:
            results.update(_run_batch(pair))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for part in pool.map(_run_batch, batches):
                results.update(part)
    return results


def _mock_category(item: NewsItem) -> str:
    from src.categories import CHANNEL_FALLBACK_CATEGORY

    return CHANNEL_FALLBACK_CATEGORY.get(item.channel, "杂类")


def review_duplicates(items: List[NewsItem], pairs: List[Tuple[int, int]], settings: Settings) -> List[Tuple[int, int]]:
    """疑似重复对复查，返回确认重复的 (i, j) 列表。"""
    if not pairs:
        return []
    confirmed: List[Tuple[int, int]] = []
    for start in range(0, len(pairs), 20):
        batch = pairs[start : start + 20]
        payload = [
            {
                "id": k,
                "title1": items[i].title,
                "title2": items[j].title,
            }
            for k, (i, j) in enumerate(batch)
        ]
        messages = [
            {"role": "system", "content": "你是新闻去重审核员。判断两条新闻标题是否描述同一新闻事件（含不同表述、多平台转载）。输出合法 JSON。"},
            {
                "role": "user",
                "content": (
                    "返回格式：{\"results\": [{\"id\": 0, \"duplicate\": true, \"reason\": \"简要原因\"}]}。"
                    "duplicate 为 true 表示应合并为一条。\n" + json.dumps({"pairs": payload}, ensure_ascii=False)
                ),
            },
        ]
        try:
            content = _chat(settings, messages, max_tokens=3000)
            data = _try_json(content or "")
        except Exception:  # noqa: BLE001
            data = None
        if not data:
            continue
        by_id = {r.get("id"): r for r in data.get("results", [])}
        for k, (i, j) in enumerate(batch):
            if by_id.get(k, {}).get("duplicate"):
                confirmed.append((i, j))
    return confirmed
