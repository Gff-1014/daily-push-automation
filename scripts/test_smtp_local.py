# -*- coding: utf-8 -*-
"""本地 SMTP 连通性测试（读取云端 send_mail 配置，不打印密钥）。"""
import smtplib
import ssl
import sys
from email.header import Header
from email.mime.text import MIMEText

sys.path.insert(0, ".")

from deploy.deploy import _load_dotenv  # noqa: E402


def main() -> None:
    env = _load_dotenv()
    host = env.get("SMTP_HOST", "smtp.qq.com")
    port = int(env.get("SMTP_PORT", "465") or 465)
    sender = env.get("SMTP_USER", "")
    auth = env.get("SMTP_AUTH_CODE", "")
    to = env.get("MAIL_TO", "") or sender
    print(f"目标: {host}:{port}  发件: {sender}  收件: {to}")

    msg = MIMEText("本地 SMTP 连通性测试", "plain", "utf-8")
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = Header("【测试】本地 SMTP 连通性", "utf-8")

    ctx = ssl.create_default_context()
    ctx.options |= ssl.OP_NO_TLSv1
    ctx.options |= ssl.OP_NO_TLSv1_1

    for label, host_, port_, mode in [("SSL-465", host, 465, "ssl"), ("STARTTLS-587", host, 587, "starttls")]:
        try:
            if mode == "ssl":
                server = smtplib.SMTP_SSL(host_, port_, timeout=15, context=ctx)
                print(f"[{label}] 已建立 SSL 连接")
            else:
                server = smtplib.SMTP(host_, port_, timeout=15)
                print(f"[{label}] TCP 已连接: {server.ehlo()}")
                server.starttls(context=ctx)
                print(f"[{label}] STARTTLS 成功: {server.ehlo()}")
            code, resp = server.login(sender, auth)
            print(f"[{label}] 登录成功: {code} {resp.decode() if isinstance(resp, bytes) else resp}")
            server.sendmail(sender, [to], msg.as_string())
            print(f"[{label}] 发送成功")
            server.quit()
            return
        except Exception as exc:  # noqa: BLE001
            print(f"[{label}] 失败: {exc!r}")
    print("全部尝试失败")


if __name__ == "__main__":
    main()
