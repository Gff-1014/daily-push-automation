# -*- coding: utf-8 -*-
"""邮件推送：POST 到「自动邮件」HTTP 触发器（阶段4）。"""
from __future__ import annotations

import os
import ssl
import smtplib
import time
from typing import Optional

import requests
from email.header import Header
from email.mime.text import MIMEText

from src.config import Settings


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _send_smtp(subject: str, body: str) -> bool:
    """直接 SMTP 发信（QQ/163 邮箱授权码），不再依赖 API 网关。"""
    smtp_host = _env("SMTP_HOST", "smtp.qq.com")
    smtp_port = int(_env("SMTP_PORT", "465") or 465)
    sender = _env("SMTP_USER")
    auth_code = _env("SMTP_AUTH_CODE")
    receiver = _env("MAIL_TO")
    if not (sender and auth_code and receiver):
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = Header(subject, "utf-8")
    ctx = ssl.create_default_context()
    ctx.options |= ssl.OP_NO_TLSv1
    ctx.options |= ssl.OP_NO_TLSv1_1
    attempts = [
        ("SSL-465", smtp_host, 465, "ssl"),
        ("STARTTLS-587", smtp_host, 587, "starttls"),
    ]
    for label, host, port, mode in attempts:
        try:
            if mode == "ssl":
                server = smtplib.SMTP_SSL(host, port, timeout=20, context=ctx)
            else:
                server = smtplib.SMTP(host, port, timeout=20)
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()
            with server:
                server.login(sender, auth_code)
                server.sendmail(sender, [receiver], msg.as_string())
            print(f"[SMTP] {label} 发送成功")
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[SMTP] {label} 失败：{exc!r}")
    return False


def send_email(subject: str, body: str, settings: Settings) -> bool:
    url = settings["email"].get("webhook_url", "")
    if url:
        timeout = settings["email"].get("timeout", 30)
        retries = int(settings["email"].get("retries", 3))
        for attempt in range(1, retries + 1):
            try:
                resp = requests.post(
                    url,
                    json={"subject": subject, "body": body},
                    timeout=timeout,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") == 0:
                    return True
            except Exception:  # noqa: BLE001
                pass
            if attempt < retries:
                time.sleep(2.0 * attempt)
        return False
    return _send_smtp(subject, body)


def send_alert(reason: str, settings: Settings) -> bool:
    return send_email(
        f"【央视网新闻总结】运行异常告警 {__import__('datetime').datetime.now():%Y-%m-%d %H:%M}",
        f"系统已连续 3 次邮件发送失败，已暂停运行。\n原因：{reason}\n请检查「自动邮件」配置后运行恢复脚本。",
        settings,
    )
