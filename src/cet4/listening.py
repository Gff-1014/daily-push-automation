# -*- coding: utf-8 -*-
"""每日听力训练：国内可达的 VOA 慢速英语镜像（tingroom.com），三份变速音频精听。

早间 / 晚间各取一篇（早晚共两篇）：
    - 音频：摘选 30–45 秒，生成 1.25x / 1x / 0.75x 三份 mp3 并上传 COS（失败回退原始直链）
    - 原文：英文文本随音频一起给出
    - 翻译：中文翻译（答案）放在原文后，空数行分隔
"""
from __future__ import annotations

import os
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional

from src.cet4.audio import build_variants
from src.cet4.audio import upload_listening_page
from src.cet4.fetch import get_text, make_session
from src.cet4.llm import chat, make_llm_settings, parse_json

SAMPLE_LISTENING: Dict[str, Any] = {
    "title": "VOA慢速英语 · How to Protect Against Increasing Infections",
    "mp3_url": "https://example.com/listening/sample.mp3",
    "play_url": "https://example.com/listening/sample.mp3",
    "page_url": "https://example.com/listening/index.html",
    "speeds": [1.25, 1.0, 0.75],
    "excerpt_seconds": 40,
    "files": {
        "1.25": "https://example.com/listening/sample-125.mp3",
        "1.0": "https://example.com/listening/sample.mp3",
        "0.75": "https://example.com/listening/sample-075.mp3",
    },
    "transcript": (
        "Knowing what these infections are and how they spread can help us avoid them. "
        "Some signs of a cold, the flu, COVID-19 or norovirus are similar. "
        "This can make it hard to know what sickness you have. "
        "The flu is caused by influenza viruses that are always changing."
    ),
    "translation": (
        "了解这些传染病是什么以及它们如何传播，能帮助我们避开它们。"
        "感冒、流感、新冠肺炎或诺如病毒的一些症状很相似。"
        "这可能让你很难知道自己得了什么病。流感由不断变化的流感病毒引起。"
    ),
    "source": "内置示例听力（LISTENING_MOCK）",
}

LLM_TRANSLATE_SYSTEM = """你是英语四级学习材料的编辑。请把给定的英文听力文本翻译成通顺、准确的中文，
适合四级考生对照学习。输出必须是合法 JSON：{"translation": "全文中文翻译"}。"""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _llm_available(settings) -> bool:
    if _env("LLM_MOCK") == "1":
        return True
    return bool(settings.deepseek_api_key)


# ---------------------------------------------------------------------------
# tingroom.com（VOA 慢速英语镜像，国内可达）
# ---------------------------------------------------------------------------

def fetch_tingroom_list(session, list_url: str, limit: int = 12) -> List[dict]:
    text = get_text(session, list_url, retries=2, timeout=25)
    seen: set = set()
    out: List[dict] = []
    for href, title in re.findall(r'href="([^"]*?/voa/\d{4}/[^"]+\.html)"[^>]*>([^<]{5,120})<', text):
        if href in seen:
            continue
        seen.add(href)
        m = re.search(r"(\d+)\.html$", href)
        out.append({"url": href if href.startswith("http") else f"http://www.tingroom.com{href}", "title": title.strip(), "id": m.group(1) if m else ""})
        if len(out) >= limit:
            break
    return out


def _english_ratio(s: str) -> float:
    letters = sum(1 for ch in s if ch.isalpha())
    if not letters:
        return 0.0
    en = sum(1 for ch in s if ("a" <= ch.lower() <= "z"))
    return en / letters


def fetch_tingroom_article(session, url: str, max_chars: int = 3000) -> Optional[dict]:
    from bs4 import BeautifulSoup

    text = get_text(session, url, retries=2, timeout=25)
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "form", "iframe"]):
        tag.decompose()
    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    paras = [p for p in paras if len(p.split()) >= 8 and _english_ratio(p) >= 0.85]
    transcript = re.sub(r"\s+", " ", " ".join(paras)).strip()
    if len(transcript) < 80:
        return None
    if len(transcript) > max_chars:
        cut = transcript[:max_chars]
        idx = cut.rfind(". ")
        transcript = cut[: idx + 1] if idx > max_chars * 0.6 else cut
    title = (soup.title.get_text(strip=True) if soup.title else "") or ""
    title = re.split(r"[_|]", title)[0].strip()
    m = re.search(r"(\d+)\.html$", url)
    return {
        "title": title,
        "transcript": transcript[:max_chars],
        "id": m.group(1) if m else "",
        "source": url,
    }


def fetch_tingroom_mp3(session, article_id: str) -> str:
    if not article_id:
        return ""
    text = get_text(session, f"http://www.tingroom.com/play.php?id={article_id}", retries=2, timeout=25)
    m = re.search(r'<audio[^>]+src="([^"]+\.mp3[^"]*)"', text, re.I)
    if not m:
        m = re.search(r'(https?://[^\s"\'<>]+\.mp3)', text, re.I)
    return m.group(1).strip() if m else ""


def fetch_tingroom_item(cfg: Dict[str, Any], session, today: date, slot: str) -> Optional[dict]:
    sources = cfg.get("listening", {}).get("sources", {})
    list_url = sources.get("tingroom_voa", "")
    if not list_url:
        return None
    max_chars = int(cfg.get("listening", {}).get("max_chars", 3000))
    items = fetch_tingroom_list(session, list_url)
    if not items:
        return None
    start = (today.toordinal() + (0 if slot == "morning" else 1)) % len(items)
    for i in range(len(items)):
        item = items[(start + i) % len(items)]
        try:
            article = fetch_tingroom_article(session, item["url"], max_chars)
            if not article:
                continue
            mp3 = fetch_tingroom_mp3(session, article["id"]) if article["id"] else ""
            return {
                "title": article["title"] or item["title"],
                "transcript": article["transcript"],
                "mp3_url": mp3,
                "source": item["url"],
            }
        except Exception:  # noqa: BLE001
            continue
    return None


def _chunk_text(text: str, limit: int = 2500) -> List[str]:
    """按句切分超长文本，每段不超过 limit 字符（用于分块翻译）。"""
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: List[str] = []
    cur = ""
    for s in sentences:
        if cur and len(cur) + len(s) + 1 > limit:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def _translate_one(settings, chunk: str) -> Optional[str]:
    messages = [
        {"role": "system", "content": LLM_TRANSLATE_SYSTEM},
        {"role": "user", "content": f"听力文本：\n{chunk}"},
    ]
    last_err = "LLM 返回内容不完整"
    for attempt in range(3):
        try:
            data = parse_json(chat(settings, messages, max_tokens=6000) or "")
            if data and (data.get("translation") or "").strip():
                return data["translation"].strip()
        except Exception as exc:  # noqa: BLE001
            last_err = repr(exc)
        if attempt < 2:
            time.sleep(3.0 * (attempt + 1))
    print(f"[听力] 翻译失败（已重试 3 次）：{last_err}")
    return None


def _translate(settings, transcript: str) -> str:
    parts: List[str] = []
    for chunk in _chunk_text(transcript):
        part = _translate_one(settings, chunk)
        if part is None:
            return "（翻译生成失败，已重试 3 次）"
        parts.append(part)
    return "".join(parts)


def build_listening(cfg: Dict[str, Any], today: date, slot: str) -> Dict[str, Any]:
    """生成当日听力训练（三份变速音频 + 原文 + 翻译）。不可用时返回内置示例。"""
    if not cfg.get("listening", {}).get("enabled", True):
        return {}
    settings = make_llm_settings(cfg)
    if _env("LISTENING_MOCK") == "1":
        return dict(SAMPLE_LISTENING)
    http_cfg = cfg.get("http", {})
    session = make_session(http_cfg.get("user_agent", "Mozilla/5.0"), int(http_cfg.get("timeout", 15)))
    try:
        item = fetch_tingroom_item(cfg, session, today, slot)
        if not item:
            return dict(SAMPLE_LISTENING)
        translation = _translate(settings, item["transcript"]) if _llm_available(settings) else "（LLM 翻译暂不可用）"
        speeds = list(cfg.get("listening", {}).get("speeds", [1.25, 1.0, 0.75]))
        variants = build_variants(cfg, item["mp3_url"], today, slot)
        files = variants.get("files", {})
        inline_data = variants.get("inline_data", {})
        page_url = ""
        # 内嵌音频可用时直接进邮件 HTML（无外链）；否则才生成对照页链接兜底
        if files and not inline_data:
            page_url = upload_listening_page(
                cfg,
                today,
                slot,
                {
                    "title": item["title"],
                    "files": files,
                    "excerpt_seconds": variants.get("excerpt_seconds", 0),
                    "transcript": item["transcript"],
                    "translation": translation,
                },
            )
        return {
            "title": item["title"],
            "mp3_url": item["mp3_url"],
            "files": files,
            "inline_data": inline_data,
            "excerpt_seconds": variants.get("excerpt_seconds", 0),
            "play_url": files.get("1.0") or item["mp3_url"],
            "page_url": page_url,
            "speeds": speeds,
            "transcript": item["transcript"],
            "translation": translation,
            "source": item["source"],
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[听力] 获取失败，使用示例：{exc!r}")
        return dict(SAMPLE_LISTENING)
