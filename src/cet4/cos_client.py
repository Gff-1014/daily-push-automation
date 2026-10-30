# -*- coding: utf-8 -*-
"""极简 COS REST 客户端（纯 requests + HMAC-SHA1 签名，四级自包含副本）。"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional
from urllib.parse import quote

import requests


class CosRestClient:
    def __init__(self, bucket: str, region: str, secret_id: str, secret_key: str) -> None:
        self.bucket = bucket
        self.region = region
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.host = f"{bucket}.cos.{region}.myqcloud.com"

    def _signed(self, method: str, key: str) -> dict:
        now = int(time.time())
        key_time = f"{now - 120};{now + 900}"
        sign_key = hmac.new(self.secret_key.encode("utf-8"), key_time.encode("utf-8"), hashlib.sha1).hexdigest()
        http_string = f"{method.lower()}\n/{key}\n\nhost={self.host}\n"
        sha1_http = hashlib.sha1(http_string.encode("utf-8")).hexdigest()
        string_to_sign = f"sha1\n{key_time}\n{sha1_http}\n"
        signature = hmac.new(sign_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).hexdigest()
        auth = (
            "q-sign-algorithm=sha1"
            f"&q-ak={self.secret_id}"
            f"&q-sign-time={key_time}"
            f"&q-key-time={key_time}"
            "&q-header-list=host"
            "&q-url-param-list="
            f"&q-signature={signature}"
        )
        return {"Host": self.host, "Authorization": auth}

    def get_object(self, key: str) -> Optional[str]:
        url = f"https://{self.host}/{key}"
        resp = requests.get(url, headers=self._signed("get", key), timeout=10)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def put_object(self, key: str, body: str) -> None:
        url = f"https://{self.host}/{key}"
        resp = requests.put(
            url,
            headers=dict(self._signed("put", key), **{"Content-Type": "application/json"}),
            data=body.encode("utf-8"),
            timeout=15,
        )
        resp.raise_for_status()

    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "audio/mpeg",
        acl: str = "",
        content_disposition: str = "",
    ) -> None:
        url = f"https://{self.host}/{key}"
        headers = dict(self._signed("put", key), **{"Content-Type": content_type})
        if acl:
            headers["x-cos-acl"] = acl
        if content_disposition:
            headers["Content-Disposition"] = content_disposition
        resp = requests.put(
            url,
            headers=headers,
            data=data,
            timeout=60,
        )
        resp.raise_for_status()

    def delete_object(self, key: str) -> None:
        url = f"https://{self.host}/{key}"
        resp = requests.delete(url, headers=self._signed("delete", key), timeout=10)
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()

    def presigned_url(
        self,
        key: str,
        params: Optional[dict] = None,
        expires_seconds: int = 15552000,
    ) -> str:
        """生成预签名 GET URL，可带 response-* 参数（如 response-content-disposition=inline），
        用于绕过 2024 年后新建桶默认域名的强制下载限制。"""
        now = int(time.time())
        key_time = f"{now};{now + expires_seconds}"
        sign_key = hmac.new(self.secret_key.encode("utf-8"), key_time.encode("utf-8"), hashlib.sha1).hexdigest()
        params = {k: str(v) for k, v in (params or {}).items()}
        query = "&".join(
            f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(params.items())
        )
        param_names = ";".join(sorted(params))
        http_string = f"get\n/{key}\n{query}\nhost={self.host}\n"
        sha1_http = hashlib.sha1(http_string.encode("utf-8")).hexdigest()
        string_to_sign = f"sha1\n{key_time}\n{sha1_http}\n"
        signature = hmac.new(sign_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).hexdigest()
        auth = (
            "q-sign-algorithm=sha1"
            f"&q-ak={self.secret_id}"
            f"&q-sign-time={key_time}"
            f"&q-key-time={key_time}"
            "&q-header-list=host"
            f"&q-url-param-list={param_names}"
            f"&q-signature={signature}"
        )
        base = f"https://{self.host}/{key}"
        return f"{base}?{query}&{auth}" if query else f"{base}?{auth}"
