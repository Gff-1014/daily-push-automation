# -*- coding: utf-8 -*-
"""极简 COS REST 客户端（纯 requests + HMAC-SHA1 签名，无 C 扩展，兼容 Python 3.9）。"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional

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

    def delete_object(self, key: str) -> None:
        url = f"https://{self.host}/{key}"
        resp = requests.delete(url, headers=self._signed("delete", key), timeout=10)
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()
