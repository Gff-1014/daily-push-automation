# -*- coding: utf-8 -*-
"""分析 JS bundle 中的 API 端点（开发期工具）。"""
import re
import sys

import requests


def main() -> None:
    url = sys.argv[1]
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.encoding = "utf-8"
    text = r.text
    print("len:", len(text))
    pats = [
        r'https?://[^"\'\s\\]+',
        r'["\'](/[^"\']*(?:api|list|json|hot|news|search)[^"\']*)["\']',
        r'["\']([^"\']*/(?:v\d+|api)[^"\']*)["\']',
    ]
    seen = set()
    for pat in pats:
        for m in re.finditer(pat, text, re.I):
            val = m.group(1) if m.lastindex else m.group(0)
            if val.startswith(("http", "/")) and len(val) < 220 and val not in seen:
                seen.add(val)
                print("[ep]", val)
    for kw in ["baseUrl", "baseURL", "apiHost", "apiBase", "node/", "offset", "limit=", "getList", "fetchList", "queryList", "ajax", "request("]:
        for m in re.finditer(re.escape(kw), text, re.I):
            i = m.start()
            chunk = text[max(0, i - 150): i + 180].replace("\n", " ")
            print(f"[{kw}]", chunk[:330])
    if "--words" in sys.argv:
        for kw in ["huanqiu", "node", "api/", "article/", "world"]:
            for m in re.finditer(re.escape(kw), text, re.I):
                i = m.start()
                chunk = text[max(0, i - 120): i + 140].replace("\n", " ")
                print(f"[{kw}]", chunk[:260])


if __name__ == "__main__":
    main()
