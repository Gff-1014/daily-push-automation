# -*- coding: utf-8 -*-
"""调试：对指定日期的阅读正文执行一次 LLM 改写调用，打印结果或错误。"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.vocab.config import load_vocab_config  # noqa: E402
from src.vocab.reading import _llm_rewrite, _pick_news, fetch_article_text  # noqa: E402
from src.fetch import make_session  # noqa: E402
from src.config import load_settings  # noqa: E402


def main() -> int:
    d = date(2026, 8, 28)
    cfg = load_vocab_config()
    settings = load_settings()
    session = make_session(
        settings["collector"].get("user_agent", "Mozilla/5.0"),
        int(settings["collector"].get("timeout", 15)),
    )
    news = _pick_news(session, cfg, "morning", d)
    if not news:
        print("无新闻")
        return 1
    text = news.get("summary") or ""
    if news.get("link"):
        try:
            text = fetch_article_text(session, news["link"], 3000)
        except Exception as exc:  # noqa: BLE001
            print("抓正文失败:", repr(exc))
    print("新闻:", news.get("title"))
    print("正文长度:", len(text))
    try:
        result = _llm_rewrite(settings, news, text, 300, 3000)
        if result:
            print("LLM OK, article len:", len(result["article"].split()), "translation len:", len(result["translation"]))
        else:
            print("LLM 返回空/解析失败")
    except Exception as exc:  # noqa: BLE001
        print("LLM 异常:", repr(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
