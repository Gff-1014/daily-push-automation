# -*- coding: utf-8 -*-
"""探测财联社可用接口（开发期工具）。"""
import hashlib
import json

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0",
    "Referer": "https://www.cls.cn/telegraph",
}


def sign(qs: str) -> str:
    return hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()


def build(base: str, params: dict) -> str:
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return f"{base}?{qs}&sign={sign(qs)}"


def main() -> None:
    inspect = __import__("sys").argv[1] if len(__import__("sys").argv) > 1 else ""
    if inspect:
        if inspect == "depth":
            url = build("https://api3.cls.cn/v3/depth/home/assembled/1000", {"app": "CailianpressWeb", "os": "web", "sv": "8.7.9"})
        else:
            url = build("https://www.cls.cn/api/cache", {"name": "telegraph", "app": "CailianpressWeb", "os": "web", "sv": "8.7.9"})
        r = requests.get(url, headers=HEADERS, timeout=12)
        data = json.loads(r.text)
        if inspect == "depth":
            d = data.get("data", {})
            print("depth keys:", sorted(d.keys()))
            for k, v in d.items():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    print("list field:", k, len(v), sorted(v[0].keys())[:20])
            return
        roll = data.get("data", {}).get("roll_data", [])
        print("total:", len(roll))
        print("keys:", sorted(roll[0].keys()) if roll else None)
        from collections import Counter
        for key in ["type", "level", "importance", "important", "is_important", "tag"]:
            vals = Counter(str(item.get(key)) for item in roll if item.get(key) is not None)
            if vals:
                print(f"field[{key}]:", dict(vals))
        for item in roll[:3]:
            print(json.dumps(item, ensure_ascii=False)[:600])
        return
    cases = [
        ("telegraph-api3-node", "https://api3.cls.cn/nodeapi/telegraphList", {"app": "CailianpressWeb", "os": "web", "sv": "8.7.9"}),
        ("telegraph-api3-node-ts", "https://api3.cls.cn/nodeapi/telegraphList", {"app": "CailianpressWeb", "os": "web", "sv": "8.7.9", "last_time": "1766707200"}),
        ("cache-www", "https://www.cls.cn/api/cache", {"name": "telegraph", "app": "CailianpressWeb", "os": "web", "sv": "8.7.9"}),
        ("cache-api3", "https://api3.cls.cn/api/cache", {"name": "telegraph", "app": "CailianpressWeb", "os": "web", "sv": "8.7.9"}),
        ("roll-api3", "https://api3.cls.cn/v1/roll/get_roll_list", {"app": "CailianpressWeb", "os": "web", "sv": "8.7.9"}),
        ("depth-api3", "https://api3.cls.cn/v3/depth/home/assembled/1000", {"app": "CailianpressWeb", "os": "web", "sv": "8.7.9"}),
    ]
    for name, base, params in cases:
        try:
            url = build(base, params)
            r = requests.get(url, headers=HEADERS, timeout=12)
            body = r.text[:300].replace("\n", " ")
            print(f"[{name}] {r.status_code} len={len(r.text)} {body}")
        except Exception as exc:  # noqa: BLE001
            print(f"[{name}] ERR {exc!r}"[:200])


if __name__ == "__main__":
    main()
