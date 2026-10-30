# -*- coding: utf-8 -*-
"""纯标准库 COS 对象读取（SCF 媒体代理函数内使用，避免第三方依赖）。

仅实现 GET 单对象：返回 (bytes, content_type)。
签名逻辑与 src/cet4/cos_client.py 保持一致（COS XML API 签名）。
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional
from urllib import parse, request


class CosReadError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _authorization(
    bucket: str,
    region: str,
    secret_id: str,
    secret_key: str,
    key: str,
    params: Optional[dict] = None,
) -> tuple:
    """返回 (host, Authorization, query)。"""
    now = int(time.time())
    key_time = f"{now - 120};{now + 900}"
    sign_key = hmac.new(secret_key.encode("utf-8"), key_time.encode("utf-8"), hashlib.sha1).hexdigest()
    host = f"{bucket}.cos.{region}.myqcloud.com"
    params = {k: str(v) for k, v in (params or {}).items()}
    query = "&".join(
        f"{parse.quote(k, safe='')}={parse.quote(v, safe='')}" for k, v in sorted(params.items())
    )
    param_names = ";".join(sorted(params))
    http_string = f"get\n/{key}\n{query}\nhost={host}\n"
    sha1_http = hashlib.sha1(http_string.encode("utf-8")).hexdigest()
    string_to_sign = f"sha1\n{key_time}\n{sha1_http}\n"
    signature = hmac.new(sign_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).hexdigest()
    auth = (
        "q-sign-algorithm=sha1"
        f"&q-ak={secret_id}"
        f"&q-sign-time={key_time}"
        f"&q-key-time={key_time}"
        "&q-header-list=host"
        f"&q-url-param-list={param_names}"
        f"&q-signature={signature}"
    )
    return host, auth, query


def get_object(
    bucket: str,
    region: str,
    secret_id: str,
    secret_key: str,
    key: str,
    params: Optional[dict] = None,
    timeout: int = 20,
) -> tuple:
    host, auth, query = _authorization(bucket, region, secret_id, secret_key, key, params)
    quoted_key = parse.quote(key, safe="/")
    url = f"https://{host}/{quoted_key}"
    if query:
        url = f"{url}?{query}"
    req = request.Request(
        url,
        headers={
            "Host": host,
            "Authorization": auth,
            "User-Agent": "cet4-media-proxy",
        },
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            content_type = resp.headers.get("Content-Type", "") or ""
            return data, content_type
    except Exception as exc:  # noqa: BLE001
        status = getattr(exc, "code", 0) or 502
        raise CosReadError(status, str(exc)) from exc
