# -*- coding: utf-8 -*-
"""探测四平台热榜接口（开发期工具）。"""
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Referer": "https://www.baidu.com/",
}


def main() -> None:
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "buvid":
        s = requests.Session()
        r = s.get(
            "https://api.bilibili.com/x/frontend/finger/spi",
            headers={"User-Agent": HEADERS["User-Agent"]},
            timeout=12,
        )
        print("spi:", r.status_code, r.text[:200])
        r2 = s.get(
            "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all",
            headers={"User-Agent": HEADERS["User-Agent"]},
            timeout=12,
        )
        print("ranking:", r2.status_code, len(r2.text), r2.text[:180])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "weibo-m":
        url = "https://m.weibo.cn/api/container/getIndex?containerid=106003type%3D25%26t%3D3%26disable_hot%3D1"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}, timeout=12)
        print("m.weibo:", r.status_code, len(r.text), r.text[:250])
        return
    cases = [
        ("weibo-ajax", "https://weibo.com/ajax/side/hotSearch", {}),
        ("weibo-s", "https://s.weibo.com/top/summary", {}),
        ("baidu-api", "https://top.baidu.com/api/board?platform=wise&tab=realtime", {}),
        ("baidu-board", "https://top.baidu.com/board?tab=realtime", {}),
        ("bilibili-ranking", "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all", {}),
        ("douyin-hot", "https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/aweme/", {}),
    ]
    for name, url, extra in cases:
        try:
            r = requests.get(url, headers=HEADERS, timeout=12, **extra)
            print(f"[{name}] {r.status_code} len={len(r.text)} {r.text[:220].replace(chr(10), ' ')}")
        except Exception as exc:  # noqa: BLE001
            print(f"[{name}] ERR {exc!r}"[:200])


if __name__ == "__main__":
    main()
