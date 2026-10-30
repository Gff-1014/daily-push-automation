# -*- coding: utf-8 -*-
"""vocab 邮件推送：webhook 或 SMTP（凭据只读复用 .env，不修改现有配置）。"""
from __future__ import annotations

import os
import ssl
import smtplib
import time
from datetime import datetime
from email.header import Header
from email.mime.text import MIMEText
from typing import Any, Dict

import requests


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _send_smtp(subject: str, body: str, email_cfg: Dict[str, Any]) -> bool:
    sender = _env("SMTP_USER")
    auth_code = _env("SMTP_AUTH_CODE")
    receiver = _env("MAIL_TO")
    if not (sender and auth_code and receiver):
        print("[SMTP] 缺少 SMTP_USER/SMTP_AUTH_CODE/MAIL_TO，跳过")
        return False
    host = _env("SMTP_HOST", email_cfg.get("smtp_host", "smtp.qq.com"))
    port = int(_env("SMTP_PORT", email_cfg.get("smtp_port", 465)) or 465)

    msg = MIMEText(body, "html", "utf-8")
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = Header(subject, "utf-8")

    ctx = ssl.create_default_context()
    ctx.options |= ssl.OP_NO_TLSv1
    ctx.options |= ssl.OP_NO_TLSv1_1
    attempts = [("SSL", host, port, "ssl")]
    if port != 587:
        attempts.append(("STARTTLS", host, 587, "starttls"))

    for label, h, p, mode in attempts:
        try:
            if mode == "ssl":
                server = smtplib.SMTP_SSL(h, p, timeout=20, context=ctx)
            else:
                server = smtplib.SMTP(h, p, timeout=20)
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()
            with server:
                server.login(sender, auth_code)
                server.sendmail(sender, [receiver], msg.as_string())
            print(f"[SMTP:{label}] 发送成功")
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[SMTP:{label}] 失败：{exc!r}")
    return False


def send_email(subject: str, body: str, cfg: Dict[str, Any]) -> bool:
    email_cfg = cfg.get("email", {})
    webhook = _env("EMAIL_WEBHOOK_URL", email_cfg.get("webhook_url", ""))
    if webhook:
        timeout = int(email_cfg.get("timeout", 30))
        retries = int(email_cfg.get("retries", 3))
        for attempt in range(1, retries + 1):
            try:
                resp = requests.post(
                    webhook,
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
    return _send_smtp(subject, body, email_cfg)


def send_alert(reason: str, cfg: Dict[str, Any]) -> bool:
    return send_email(
        f"【六级单词打卡】运行异常告警 {datetime.now():%Y-%m-%d %H:%M}",
        f"六级单词邮件连续发送失败，系统已暂停。\n原因：{reason}\n修复后请运行恢复脚本。",
        cfg,
    )
