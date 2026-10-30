# -*- coding: utf-8 -*-
"""生成自包含听力对照页（三档音频 base64 内嵌，<audio controls> 系统原生播放器）
并作为邮件附件发送，用于验证"可打开、可播放"的载体。

用法：python scripts/send_listening_attachment.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.cet4.config import load_cet4_config  # noqa: E402
from src.cet4.notifier import send_email  # noqa: E402

PREVIEW = ROOT / "data" / "cet4" / "output" / "preview"
TITLE = "VOA 慢速英语 · Do Weighted Blankets Have Health Benefits?"
TRANSCRIPT = (
    "From VOA Learning English, this is the Health & Lifestyle report. "
    "When her husband gave her a weighted blanket to help her sleep, "
    "Rhonda James did not think it would work. In other words, she was skeptical. "
    "But five minutes after covering herself with the blanket, she was asleep."
)
TRANSLATION = (
    "来自 VOA 慢速英语，这里是健康与生活方式报道。"
    "当她的丈夫给她一条重力毯帮助睡眠时，朗达·詹姆斯并不认为它会起作用。"
    "换句话说，她持怀疑态度。但盖上毯子五分钟后，她就睡着了。"
)


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def build_page() -> str:
    players = []
    for label, rate in (
        ("第一遍 · 1.25x 快速听大意", "1.25"),
        ("第二遍 · 1x 正常精听", "1.0"),
        ("第三遍 · 0.75x 慢速核对", "0.75"),
    ):
        b64 = _b64(PREVIEW / f"{rate}.mp3")
        players.append(
            f'<div style="font-size:18px;font-weight:bold;margin:14px 0 4px;">{label}</div>'
            f'<audio controls preload="none" src="data:audio/mpeg;base64,{b64}" '
            'style="width:100%;"></audio>'
        )
    players_html = "".join(players)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>四级听力 · 对照</title>
<style>
  body {{ font-family: "Microsoft YaHei", Arial, sans-serif; max-width: 760px; margin: 32px auto; padding: 0 16px; color: #222; }}
  h1 {{ font-size: 24px; }}
  .tip {{ color: #666; font-size: 15px; line-height: 1.8; }}
  .section {{ font-size: 19px; font-weight: bold; margin: 22px 0 6px; }}
  .text {{ font-size: 18px; line-height: 1.95; }}
  .answer {{ font-size: 18px; line-height: 1.95; color: #444; }}
  .gap {{ height: 1.6em; }}
  .note {{ background: #f2f7ff; border-left: 4px solid #4a7fc1; color: #555; font-size: 14px;
          line-height: 1.8; padding: 10px 12px; margin: 12px 0; }}
</style>
</head>
<body>
<h1>四级听力 · 三遍精听（摘选 35 秒）</h1>
<p class="tip">第一遍 <b>1.25x</b> 快速听大意 → 第二遍 <b>1x</b> 正常精听 → 第三遍 <b>0.75x</b> 慢速核对细节。</p>
<p class="note">💡 后台播放：播放中切到其他 App（或锁屏），音频会继续播放。</p>
{players_html}
<div class="section">标题</div>
<div class="text">{TITLE}</div>
<div class="section">英文原文</div>
<div class="text">{TRANSCRIPT}</div>
<div class="gap"></div><div class="gap"></div><div class="gap"></div><div class="gap"></div><div class="gap"></div>
<div class="section">中文翻译（答案）</div>
<div class="answer">{TRANSLATION}</div>
</body>
</html>
"""


def main() -> int:
    cfg = load_cet4_config(str(ROOT / "config" / "cet4.test.yaml"))
    page = build_page()
    subject = "【四级备考】听力对照页（自包含 HTML，请打开附件测试）"
    body = (
        '<div style="font-size:20px;line-height:1.9;font-family:Microsoft YaHei,Arial;color:#222;">'
        "这封邮件附带一个<b>自包含听力对照页</b>（HTML 文件，三档音频已内嵌，无需联网）。<br><br>"
        "<b>打开方式：</b><br>"
        "① 电脑：下载附件后双击，用浏览器（Chrome/Edge/Safari）打开即可；<br>"
        "② 手机：下载后用「浏览器」打开（如 iPhone 可存到文件 App 后选择用浏览器打开）。<br><br>"
        "页面内含三档倍速的 iOS 系统原生播放器，以及英文原文 / 中文翻译对照。"
        "请测试后告诉我：能否打开、能否播放、切后台是否继续。</div>"
    )
    ok = send_email(
        subject,
        body,
        cfg,
        attachment={"filename": "听力对照页.html", "data": page.encode("utf-8")},
    )
    print("邮件发送成功" if ok else "邮件发送失败")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
