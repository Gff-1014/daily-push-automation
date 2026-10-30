# -*- coding: utf-8 -*-
"""探测各新闻源页面结构与可达性（开发期工具，不进入部署包）。"""
import re
import sys

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}


def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = r.apparent_encoding or "utf-8"
    print(f"== {url} -> {r.status_code} len={len(r.text)} final={r.url}")
    print(f"   encoding={r.encoding} apparent={r.apparent_encoding} ctype={r.headers.get('content-type','')}")
    return r.text


def show_links(html: str, keywords, limit: int = 8) -> None:
    soup = BeautifulSoup(html, "html.parser")
    all_a = [a for a in soup.find_all("a", href=True) if "".join(a.get_text()).strip()]
    print(f"-- total <a> with text: {len(all_a)}")
    for a in all_a[:10]:
        print("   ", a["href"][:80], "|", "".join(a.get_text()).strip()[:40])
    for kw in keywords:
        hits = []
        for a in soup.find_all("a", href=True):
            text = "".join(a.get_text()).strip()
            href = a["href"]
            if kw in text:
                hits.append((href, text[:50]))
        print(f"-- {kw}: {len(hits)} hits")
        for href, text in hits[:limit]:
            print("   ", href, "|", text)


def show_articles(html: str, limit: int = 15) -> None:
    soup = BeautifulSoup(html, "html.parser")
    pat = re.compile(r"/20\d\d/\d\d/\d\d/")
    seen = set()
    count = 0
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if pat.search(href) and href not in seen:
            seen.add(href)
            text = "".join(a.get_text()).strip()
            print(f"   {href[:100]} | {text[:60]}")
            count += 1
            if count >= limit:
                break
    print(f"-- article-like links: {count} (unique {len(seen)})")


def main() -> None:
    targets = {
        "homepage": ("https://www.cctv.com/", ["要闻", "时政", "科技", "国际", "军事", "文化", "生态", "社会", "财经", "教育", "健康"]),
        "news": ("https://news.cctv.com/", ["要闻", "国内", "国际", "时政", "24小时", "社会"]),
        "finance": ("https://finance.cctv.com/index.shtml", ["要闻", "财经", "政策", "股市"]),
        "tech": ("https://news.cctv.com/tech/index.shtml", ["科技", "AI", "航天"]),
        "world": ("https://news.cctv.com/world/", ["国际", "要闻"]),
        "military": ("https://military.cctv.com/index.shtml", ["军事", "要闻"]),
        "culture": ("https://www.cctv.com/culture/index.shtml", ["文化", "要闻", "教育"]),
        "society": ("https://news.cctv.com/society/", ["社会", "要闻"]),
    }
    which = sys.argv[1] if len(sys.argv) > 1 else "homepage"
    if which == "articles":
        url = sys.argv[2]
        html = fetch(url)
        show_articles(html)
        return
    if which not in targets:
        print("unknown target", which)
        return
    url, kws = targets[which]
    html = fetch(url)
    show_links(html, kws)


if __name__ == "__main__":
    main()
