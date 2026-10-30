# -*- coding: utf-8 -*-
"""探测页面中的 JS 数据/API 端点（开发期工具）。"""
import re
import sys

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}


def main() -> None:
    url = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "default"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.encoding = r.apparent_encoding or "utf-8"
    html = r.text
    print("len:", len(html))
    if mode == "endpoints":
        for pat in [
            r"(?:jsonpCallback|callback|url|jsonurl|apiUrl)\s*[:=]\s*[\"']([^\"']+)[\"']",
            r"[\"'](https?://[^\"']*?(?:json|jsonp|list|get|api)[^\"']*)[\"']",
        ]:
            for m in re.finditer(pat, html, re.I):
                print("[ep]", m.group(1)[:180])
        for m in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.S):
            script = m.group(1)
            if any(k in script for k in ["jsonp", "getJSON", "ajax", ".json"]):
                for u in re.findall(r"[\"']([^\"']*?(?:json|jsonp|ajax|getJSON|api)[^\"']*)[\"']", script, re.I):
                    print("[inline]", u[:160])
        return
    if mode == "scripts":
        for m in re.finditer(r'<script[^>]+src="([^"]+)"', html):
            print("[script]", m.group(1)[:150])
        for m in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.S):
            script = m.group(1).strip()
            if script and "function" not in script[:40] and len(script) < 500:
                print("[inline]", script[:300].replace("\n", " "))
        return
    if mode == "topicid":
        for m in re.finditer(r"topicID\s*=\s*[\"']?([A-Za-z0-9]+)", html):
            print("[topicID]", m.group(1))
        for m in re.finditer(r"data-topicid|data-columnid|columnId[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9]+)", html, re.I):
            print("[column]", m.group(1))
        return
    for pat, label in [
        (r"datalist\s*=\s*(\[.*?\])", "datalist"),
        (r"(?:var|let|const)\s+\w+\s*=\s*(\{.*\"title\".*?\})", "obj-with-title"),
    ]:
        for m in re.finditer(pat, html, re.S):
            print(f"== {label}:", m.group(1)[:800])
            break
    for m in re.finditer(r"jsonpurl\s*=\s*[\"']([^\"']+)[\"']", html):
        print("[jsonpurl]", m.group(1))
    for m in re.finditer(r"(?:url|api)\s*:\s*[\"']([^\"']+)[\"']", html):
        print("[urlfield]", m.group(1)[:150])
    for m in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.S):
        script = m.group(1)
        if "datalist" in script:
            for u in re.findall(r"[\"']([^\"']*(?:get|list|json|data|news|ajax)[^\"']*)[\"']", script, re.I):
                if "http" in u or ".js" not in u:
                    print("[inline-url]", u[:200])
            idx = script.find("datalist")
            jidx = 0
            while True:
                jidx = script.find("jsonpurl", jidx)
                if jidx < 0:
                    break
                print("[jsonpurl-context]", script[max(0, jidx - 250): jidx + 350].replace("\n", " "))
                jidx += 1
            print("[datalist-context]", script[max(0, idx - 400): idx + 300])
    for m in re.finditer(r'<script[^>]*src="([^"]+)"', html):
        print("script:", m.group(1)[:140])
    for kw in ["api", "json", "data", "list", "shtml", "getUrl", "request", "ajax", "nodeapi"]:
        for m in re.finditer(r'(["\'])([^"\']*' + kw + r'[^"\']*)\1', html, re.I):
            print(f"[{kw}]", m.group(2)[:180])


if __name__ == "__main__":
    main()
