# -*- coding: utf-8 -*-
"""当日英文新闻 → 四级难度短文 + 中文翻译 + 长难句分析（含兜底）。"""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from src.cet4.fetch import get_text, make_session
from src.cet4.llm import chat, make_llm_settings, parse_json

SAMPLE_ARTICLE: Dict[str, Any] = {
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
    "sentences": [
        {
            "sentence": (
                "However, they also point out that changing the habits of millions of "
                "commuters will take time and money."
            ),
            "analysis": (
                "主句：they point out ...（他们指出……）；"
                "that 引导宾语从句：changing the habits of millions of commuters will take time and money；"
                "从句主语是动名词短语 changing the habits of millions of commuters（改变数百万通勤者的习惯）。"
                "通俗理解：但专家也说，要改变这么多人的出行习惯，既需要时间也需要钱。"
            ),
        }
    ],
}

LLM_SYSTEM = """你是英语四级学习材料的编辑。请把给定的英文新闻改写成适合英语四级考试的短文：
1. 篇幅 120-220 词；
2. 保留新闻事实，不得虚构细节；
3. 使用四级难度词汇与句型（以四级大纲词为主，超出难度的词用简单表达或括号注释），
   句子不宜过长，语言自然流畅；
4. 从改写后的短文中挑出 1-2 个对四级考生最有难度的长难句，输出长难句分析
   （主谓宾拆分 + 特殊语法点 + 通俗解释，确保基础薄弱的考生也能看懂）；
5. 输出必须是合法 JSON：
   {"title": "英文标题", "article": "英文短文正文", "translation": "全文中文翻译",
    "sentences": [{"sentence": "长难句原文（必须逐字来自 article）", "analysis": "主谓宾拆分+语法点+通俗解释"}]}。
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


def _parse_rss(text: str):
    """解析 RSS XML，容忍非法控制字符与文档尾部垃圾（ScienceDaily 常见）。"""
    candidates = [text]
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    if cleaned != text:
        candidates.append(cleaned)
    for cand in list(candidates):
        for marker in ("</rss>", "</channel>", "</feed>"):
            idx = cand.rfind(marker)
            if idx > 0:
                candidates.append(cand[: idx + len(marker)])
    last_err: Exception | None = None
    for cand in candidates:
        try:
            return ET.fromstring(cand.strip())
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise last_err or ValueError("RSS 解析失败")


def fetch_rss(session, url: str, limit: int = 10) -> List[dict]:
    text = get_text(session, url, retries=2, timeout=25)
    root = _parse_rss(text)
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


def _pick_news(
    session,
    cfg: Dict[str, Any],
    slot: str,
    today: date,
    used: Optional[List[str]] = None,
) -> Optional[dict]:
    urls = _feed_urls(cfg, slot)
    if not urls:
        return None
    used_set = set(used or [])
    # 按日期轮换起始源，失败自动切下一源
    start = today.toordinal() % len(urls)
    first_fallback: Optional[dict] = None
    for i in range(len(urls)):
        url = urls[(start + i) % len(urls)]
        try:
            items = fetch_rss(session, url, limit=12)
            if not items:
                continue
            if first_fallback is None:
                first_fallback = dict(items[0], source=url)
            # 取第一篇没出现过的文章（链接或标题任一命中历史即视为用过）
            for news in items:
                if used_set and ({news.get("link", ""), news.get("title", "")} & used_set):
                    continue
                news["source"] = url
                return news
        except Exception:  # noqa: BLE001
            continue
    # 所有源的文章都用过：退回首个源的第一篇（允许重复），避免整封邮件缺阅读板块
    if first_fallback:
        print("[阅读] 所有候选文章均已用过，回退最早可用文章（可能重复）")
    return first_fallback


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
            # 推理模型（DeepSeek V4 系）会先输出思考内容，3000 会被思考占满导致正文为空
            content = chat(settings, messages, max_tokens=8000)
            data = parse_json(content or "")
            if data and (data.get("article") or "").strip() and (data.get("translation") or "").strip():
                return {
                    "title": (data.get("title") or news.get("title") or "").strip(),
                    "article": (data.get("article") or "").strip(),
                    "translation": (data.get("translation") or "").strip(),
                    "sentences": [
                        {
                            "sentence": (s.get("sentence") or "").strip(),
                            "analysis": (s.get("analysis") or "").strip(),
                        }
                        for s in (data.get("sentences") or [])
                        if (s.get("sentence") or "").strip()
                    ],
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


def build_reading(cfg: Dict[str, Any], today: date, slot: str, state=None) -> Dict[str, Any]:
    """生成阅读材料 + 翻译。LLM/网络不可用时返回内置示例文章。"""
    settings = make_llm_settings(cfg)
    reading_cfg = cfg.get("reading", {})
    max_words = int(reading_cfg.get("max_words", 220))
    article_chars = int(reading_cfg.get("article_chars", 3000))

    if not _llm_available(settings) or _env("READING_MOCK") == "1":
        return dict(SAMPLE_ARTICLE, sentences=list(SAMPLE_ARTICLE.get("sentences", [])))

    http_cfg = cfg.get("http", {})
    session = make_session(http_cfg.get("user_agent", "Mozilla/5.0"), int(http_cfg.get("timeout", 15)))
    used = state.reading_used_keys() if state is not None else []
    news = _pick_news(session, cfg, slot, today, used)
    if not news:
        return dict(SAMPLE_ARTICLE, sentences=list(SAMPLE_ARTICLE.get("sentences", [])))

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
        result.setdefault("sentences", [])
        return result
    # 兜底：无 LLM 结果时用 RSS 摘要当正文，翻译留占位
    return {
        "title": news.get("title", ""),
        "article": text or SAMPLE_ARTICLE["article"],
        "translation": "（LLM 改写/翻译暂不可用）",
        "sentences": [],
        "source": news.get("source", ""),
        "url": news.get("link", ""),
    }
