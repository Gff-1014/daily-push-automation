# -*- coding: utf-8 -*-
"""cet4 听力媒体代理（SCF Web 函数 + 函数 URL）。

从 COS 读取听力对照页 / 变速音频对象，以可控响应头返回：
  - 正确 Content-Type（text/html / audio/mpeg）
  - Content-Disposition: inline（不触发下载）
  - CORS 允许跨域
从而绕过 2024 年后新建 COS 桶默认域名强制下载的限制。

部署：python deploy/deploy_media_proxy.py
"""
from __future__ import annotations

import base64
import json
import os
from urllib.parse import unquote

from cos_reader import CosReadError, get_object

MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "")
COS_REGION = os.environ.get("COS_REGION", "ap-guangzhou")
SECRET_ID = os.environ.get("TENCENT_SECRET_ID", "")
SECRET_KEY = os.environ.get("TENCENT_SECRET_KEY", "")
ALLOWED_PREFIX = os.environ.get("MEDIA_KEY_PREFIX", "cet4/listening/")

FALLBACK_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def _respond(status: int, content_type: str, body: str, extra: dict = None) -> dict:
    headers = {
        "Content-Type": content_type,
        "Content-Disposition": "inline",
        "Cache-Control": "public, max-age=86400",
        "Access-Control-Allow-Origin": "*",
    }
    if extra:
        headers.update(extra)
    return {
        "statusCode": status,
        "headers": headers,
        "body": body,
        "isBase64Encoded": False,
    }


def main_handler(event, context):  # noqa: ARG001
    path = event.get("path") or ""
    if not path:
        req_ctx = event.get("requestContext") or {}
        path = req_ctx.get("path") or ""
    key = unquote(path.lstrip("/"))
    if not key:
        return _respond(404, "text/plain; charset=utf-8", "not found")
    if not key.startswith(ALLOWED_PREFIX):
        return _respond(403, "text/plain; charset=utf-8", "forbidden")
    if not (MEDIA_BUCKET and SECRET_ID and SECRET_KEY):
        return _respond(500, "text/plain; charset=utf-8", "proxy env missing")
    try:
        data, ctype = get_object(MEDIA_BUCKET, COS_REGION, SECRET_ID, SECRET_KEY, key)
    except CosReadError as exc:
        return _respond(404 if exc.status == 404 else 502, "text/plain; charset=utf-8", str(exc)[:200])
    except Exception as exc:  # noqa: BLE001
        return _respond(502, "text/plain; charset=utf-8", str(exc)[:200])

    ext = os.path.splitext(key)[1].lower()
    content_type = (ctype or "").split(";")[0].strip().lower() or FALLBACK_TYPES.get(ext, "application/octet-stream")
    if "html" in content_type:
        content_type = "text/html; charset=utf-8"
    elif content_type.startswith("audio/") or content_type.startswith("image/"):
        pass
    else:
        content_type = FALLBACK_TYPES.get(ext, content_type)

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": content_type,
            "Content-Disposition": "inline",
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Range",
        },
        "body": base64.b64encode(data).decode("ascii"),
        "isBase64Encoded": True,
    }


if __name__ == "__main__":
    # 本地冒烟测试：python deploy/media_proxy/main.py <cos key>
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env_path = os.path.join(root, ".env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    SECRET_ID = os.environ.get("TENCENTCLOUD_SECRET_ID") or os.environ.get("TENCENT_SECRET_ID", "")
    SECRET_KEY = os.environ.get("TENCENTCLOUD_SECRET_KEY") or os.environ.get("TENCENT_SECRET_KEY", "")
MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "")
    key = sys.argv[1] if len(sys.argv) > 1 else "cet4/listening/2026-08-29-morning/index.html"
    resp = main_handler({"path": f"/{key}"}, None)
    print(json.dumps({k: (v[:120] + "..." if isinstance(v, str) and len(v) > 120 else v) for k, v in resp.items()}, ensure_ascii=False, indent=2))
