# -*- coding: utf-8 -*-
"""当日英文新闻 → 六级难度短文 + 中文翻译（含兜底）。"""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from src.config import load_settings
from src.fetch import get_text, make_session
from src.llm import chat, parse_json

SAMPLE_ARTICLE: Dict[str, str] = {
    "title": "Cities Turn to Greener Transport to Cut Air Pollution",
    "article": (
        "Many cities around the world are trying to reduce air pollution by "
        "encouraging greener forms of transport. Officials say that cars powered by "
        "petrol and diesel are a major source of harmful gases, so local governments "
        "are expanding bus lanes, building new cycle paths and offering cheaper "
        "tickets for electric buses. Environmental experts believe these measures "
        "could greatly improve the quality of the air that residents breathe. "
        "However, they also point out that changing the habits of millions of "
        "commuters will take time and money. Some cities have already seen "
        "encouraging results, with a measurable drop in traffic and an increase in "
        "the number of people choosing bicycles over private cars. In the long run, "
        "the ability to balance economic growth with a cleaner environment will "
        "depend on both government policy and public support."
    ),
    "translation": (
        "世界上许多城市正在通过鼓励更环保的交通方式来减少空气污染。官员表示，"
        "使用汽油和柴油的汽车是有害气体的主要来源，因此地方政府正在扩建公交专用道、"
        "修建新的自行车道，并为电动公交车提供更优惠的票价。环境专家认为，这些措施"
        "能够大幅改善居民呼吸的空气的质量。不过，他们也指出，改变数百万通勤者的"
        "习惯需要时间和资金。一些城市已经看到了令人鼓舞的成果，交通流量明显下降，"
        "选择自行车而非私家车的人数也在增加。从长远来看，在经济增长与更清洁的"
        "环境之间取得平衡，既取决于政府政策，也取决于公众的支持。"
    ),
    "source": "内置示例文章",
    "url": "",
}

LLM_SYSTEM = """你是英语六级学习材料的编辑。请把给定的英文新闻改写成适合英语六级考试的短文：
1. 篇幅 200-280 词；
2. 保留新闻事实，不得虚构细节；
3. 使用六级难度词汇与句型，但语言自然流畅，不得超出 300 词；
4. 输出必须是合法 JSON：{"title": "英文标题", "article": "英文短文正文", "translation": "全文中文翻译"}。
"""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _llm_available(settings) -> bool:
    if _env("LLM_MOCK") == "1":
        return True
    return bool(settings.deepseek_api_key)


def _feed_urls(cfg: Dict[str, Any], slot: str) -> List[str]:
    reading = cfg.get("reading", {})
    feeds = reading.get("feeds", {})
    key = "morning_sources" if slot == "morning" else "evening_sources"
    names = reading.get(key, [])
    return [feeds[n] for n in names if n in feeds]


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def fetch_rss(session, url: str, limit: int = 10) -> List[dict]:
    text = get_text(session, url, retries=2, timeout=25)
    root = ET.fromstring(text)
    items: List[dict] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip()
        desc = _strip_html(item.findtext("description") or "")
        pub = (item.findtext("pubDate") or "").strip()
        items.append({"title": title, "link": link, "summary": desc, "pub_date": pub})
        if len(items) >= limit:
            break
    return items


def fetch_article_text(session, url: str, max_chars: int = 3000) -> str:
    text = get_text(
        session,
        url,
        retries=2,
        timeout=25,
        headers={"Accept-Language": "en-US,en;q=0.8"},
    )
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "form", "figure"]):
        tag.decompose()
    node = soup.find("article") or soup.body or soup
    paras = [p.get_text(" ", strip=True) for p in node.find_all("p")]
    body = " ".join(paras) or node.get_text(" ", strip=True)
    body = re.sub(r"\s+", " ", body).strip()
    return body[:max_chars]


def _pick_news(session, cfg: Dict[str, Any], slot: str, today: date) -> Optional[dict]:
    urls = _feed_urls(cfg, slot)
    if not urls:
        return None
    # 按日期轮换起始源，失败自动切下一源
    start = today.toordinal() % len(urls)
    for i in range(len(urls)):
        url = urls[(start + i) % len(urls)]
        try:
            items = fetch_rss(session, url)
            if not items:
                continue
            news = items[0]
            news["source"] = url
            return news
        except Exception:  # noqa: BLE001
            continue
    return None


def _llm_rewrite(settings, news: dict, text: str, max_words: int, article_chars: int) -> Optional[dict]:
    messages = [
        {"role": "system", "content": LLM_SYSTEM},
        {
            "role": "user",
            "content": (
                f"新闻标题：{news.get('title', '')}\n"
                f"新闻正文：{text[:article_chars]}\n"
                f"来源链接：{news.get('link', '')}\n"
                f"目标词数：约 {max_words} 词。"
            ),
        },
    ]
    # LLM 偶发失败：最多重试 3 次（首次 + 2 次补偿），仍失败由调用方走兜底
    last_error = None
    for attempt in range(3):
        try:
            content = chat(settings, messages, max_tokens=3000)
            data = parse_json(content or "")
            if data and (data.get("article") or "").strip() and (data.get("translation") or "").strip():
                return {
                    "title": (data.get("title") or news.get("title") or "").strip(),
                    "article": (data.get("article") or "").strip(),
                    "translation": (data.get("translation") or "").strip(),
                    "source": news.get("source", ""),
                    "url": news.get("link", ""),
                }
            last_error = "LLM 返回内容不完整"
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    print(f"[阅读] LLM 改写/翻译失败（已重试）：{last_error}")
    return None


def build_reading(cfg: Dict[str, Any], today: date, slot: str) -> Dict[str, Any]:
    """生成阅读材料 + 翻译。LLM/网络不可用时返回内置示例文章。"""
    settings = load_settings()
    reading_cfg = cfg.get("reading", {})
    max_words = int(reading_cfg.get("max_words", 300))
    article_chars = int(reading_cfg.get("article_chars", 3000))

    if not _llm_available(settings) or _env("READING_MOCK") == "1":
        return dict(SAMPLE_ARTICLE)

    session = make_session(
        settings["collector"].get("user_agent", "Mozilla/5.0"),
        int(settings["collector"].get("timeout", 15)),
    )
    news = _pick_news(session, cfg, slot, today)
    if not news:
        return dict(SAMPLE_ARTICLE)

    text = news.get("summary") or ""
    if news.get("link"):
        try:
            body = fetch_article_text(session, news["link"], article_chars)
            if body:
                text = body
        except Exception:  # noqa: BLE001
            pass
    news["text"] = text

    result = _llm_rewrite(settings, news, text, max_words, article_chars)
    if result and result.get("article"):
        return result
    # 兜底：无 LLM 结果时用 RSS 摘要当正文，翻译留占位
    return {
        "title": news.get("title", ""),
        "article": text or SAMPLE_ARTICLE["article"],
        "translation": "（LLM 改写/翻译暂不可用）",
        "source": news.get("source", ""),
        "url": news.get("link", ""),
    }
