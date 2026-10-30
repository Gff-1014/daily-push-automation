# -*- coding: utf-8 -*-
"""SCF Web 函数 HTTP 服务（scf_bootstrap 启动，监听 :9000）。

函数 URL 对 Web 函数请求/响应直接透传：这里用标准库 http.server 直接写回
二进制字节与自定义响应头（正确 Content-Type、inline、CORS），彻底规避
COS 默认域名强制下载与函数 URL 事件模式不解码 base64 的问题。
"""
from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from cos_reader import CosReadError, get_object

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


class MediaHandler(BaseHTTPRequestHandler):
    server_version = "cet4-media-proxy"

    @staticmethod
    def _env() -> dict:
        return {
            "bucket": os.environ.get("MEDIA_BUCKET", ""),
            "region": os.environ.get("COS_REGION", "ap-guangzhou"),
            "secret_id": os.environ.get("TENCENT_SECRET_ID")
            or os.environ.get("TENCENTCLOUD_SECRET_ID")
            or "",
            "secret_key": os.environ.get("TENCENT_SECRET_KEY")
            or os.environ.get("TENCENTCLOUD_SECRET_KEY")
            or "",
            "prefix": os.environ.get("MEDIA_KEY_PREFIX", "cet4/listening/"),
        }

    def log_message(self, fmt, *args):  # noqa: ARG002
        pass

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        self.send_header("Access-Control-Expose-Headers", "*")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        self._serve()

    def do_HEAD(self) -> None:
        self._serve(head_only=True)

    def _serve(self, head_only: bool = False) -> None:
        env = self._env()
        key = unquote(self.path.lstrip("/"))
        if not key:
            self._text(404, "not found", head_only)
            return
        if not key.startswith(env["prefix"]):
            self._text(403, "forbidden", head_only)
            return
        if not (env["bucket"] and env["secret_id"] and env["secret_key"]):
            self._text(500, "proxy env missing", head_only)
            return
        try:
            data, ctype = get_object(
                env["bucket"], env["region"], env["secret_id"], env["secret_key"], key
            )
        except CosReadError as exc:
            self._text(404 if exc.status == 404 else 502, str(exc)[:200], head_only)
            return
        except Exception as exc:  # noqa: BLE001
            self._text(502, str(exc)[:200], head_only)
            return

        ext = os.path.splitext(key)[1].lower()
        base_type = (ctype or "").split(";")[0].strip().lower()
        if "html" in base_type:
            content_type = "text/html; charset=utf-8"
        else:
            content_type = FALLBACK_TYPES.get(ext, base_type or "application/octet-stream")

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", "inline")
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def _text(self, status: int, message: str, head_only: bool) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", "inline")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        if not head_only:
            self.wfile.write(body)


def main() -> None:
    env = MediaHandler._env()
    if not (env["bucket"] and env["secret_id"] and env["secret_key"]):
        _load_env_dotenv()
    port = int(os.environ.get("PORT", "9000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), MediaHandler)
    server.serve_forever()


def _load_env_dotenv() -> None:
    """本地测试兜底：从项目根 .env 读取密钥（云端无 .env，不受影响）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        env_path = os.path.join(here, ".env")
        if os.path.exists(env_path):
            for line in open(env_path, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return
        here = os.path.dirname(here)


if __name__ == "__main__":
    main()
