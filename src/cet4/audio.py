# -*- coding: utf-8 -*-
"""听力音频处理：摘选 30–45 秒 + 生成 1.25x / 1x / 0.75x 三份音频。

用 ffmpeg atempo 保音调变速；处理失败自动回退为原始直链。
ffmpeg 查找顺序：环境变量 FFMPEG_BIN → imageio_ffmpeg 内置 → 系统 PATH。
"""
from __future__ import annotations

import base64
import os
import html as html_mod
import json as json_mod
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from src.cet4.cos_client import CosRestClient

SPEEDS = [1.25, 1.0, 0.75]


def resolve_ffmpeg() -> str:
    exe = os.environ.get("FFMPEG_BIN", "").strip()
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        pass
    return shutil.which("ffmpeg") or ""


def _run(ffmpeg: str, args: list) -> None:
    proc = subprocess.run([ffmpeg, *args], capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {proc.stderr[-300:]}")


def _duration(ffmpeg: str, path: Path) -> float:
    proc = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True, timeout=120)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", proc.stderr)
    if not m:
        raise RuntimeError("无法解析音频时长")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def _excerpt_args(in_path: Path, out_path: Path, start: float, dur: float) -> list:
    return [
        "-y", "-ss", f"{start:.1f}", "-t", f"{dur:.1f}", "-i", str(in_path),
        "-vn", "-acodec", "libmp3lame", "-q:a", "6", str(out_path),
    ]


def _speed_args(in_path: Path, out_path: Path, rate: float) -> list:
    return [
        "-y", "-i", str(in_path),
        "-filter:a", f"atempo={rate}",
        "-vn", "-acodec", "libmp3lame", "-q:a", "6", str(out_path),
    ]


def _cos_client(cfg: Dict[str, Any]) -> Optional[CosRestClient]:
    cos = cfg.get("cos", {})
    listening = cfg.get("listening", {})
    bucket = listening.get("cos_bucket", "") or cos.get("bucket", "")
    if not bucket:
        return None
    secret_id = os.environ.get("TENCENT_SECRET_ID", "") or os.environ.get("TENCENTCLOUD_SECRET_ID", "")
    secret_key = os.environ.get("TENCENT_SECRET_KEY", "") or os.environ.get("TENCENTCLOUD_SECRET_KEY", "")
    if not (secret_id and secret_key):
        return None
    region = listening.get("cos_region", "") or cos.get("region", "ap-guangzhou")
    return CosRestClient(bucket, region, secret_id, secret_key)


def build_variants(cfg: Dict[str, Any], mp3_url: str, today: date, slot: str) -> Dict[str, Any]:
    """下载 → 摘选 30–45 秒 → 生成三份变速 → 传 COS。

    返回 {"files": {"1.25": url, "1.0": url, "0.75": url}, "excerpt_seconds": N}；
    任何环节失败返回 {}（调用方回退为原始直链）。
    """
    ffmpeg = resolve_ffmpeg()
    client = _cos_client(cfg)
    if not (ffmpeg and client and mp3_url):
        return {}
    try:
        import requests

        listening = cfg.get("listening", {})
        prefix = str(listening.get("cos_key_prefix", "cet4/listening/"))
        expire = int(listening.get("url_expire_days", 180)) * 86400
        with tempfile.TemporaryDirectory(prefix="cet4_audio_") as tmp:
            tmp_dir = Path(tmp)
            raw = tmp_dir / "raw.mp3"
            resp = requests.get(mp3_url, timeout=90, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            raw.write_bytes(resp.content)

            total = _duration(ffmpeg, raw)
            if total < 20:
                return {}
            excerpt_min = int(listening.get("excerpt_min", 30))
            excerpt_max = int(listening.get("excerpt_max", 45))
            dur = min(excerpt_max, max(excerpt_min, excerpt_min + today.toordinal() % (excerpt_max - excerpt_min + 1)))
            dur = min(dur, int(total) - 1)
            excerpt = tmp_dir / "excerpt.mp3"
            _run(ffmpeg, _excerpt_args(raw, excerpt, 1.0, dur))

            files: Dict[str, str] = {}
            inline_data: Dict[str, str] = {}
            key_base = f"{prefix}{today.isoformat()}-{slot}"
            for rate in SPEEDS:
                out = tmp_dir / f"{rate}.mp3"
                if abs(rate - 1.0) < 1e-9:
                    out.write_bytes(excerpt.read_bytes())
                else:
                    _run(ffmpeg, _speed_args(excerpt, out, rate))
                key = f"{key_base}/{rate}.mp3"
                data = out.read_bytes()
                client.put_bytes(
                    key,
                    data,
                    "audio/mpeg",
                    acl="public-read",
                    content_disposition="inline",
                )
                files[str(rate)] = client.presigned_url(
                    key, {"response-content-disposition": "inline"}, expires_seconds=expire
                )
                # 内嵌数据：直接把 mp3 转 base64，供邮件 HTML 播放器使用（无外链、不依赖托管域名）
                inline_data[str(rate)] = base64.b64encode(data).decode("ascii")
            return {"files": files, "inline_data": inline_data, "excerpt_seconds": dur}
    except Exception as exc:  # noqa: BLE001
        print(f"[音频] 三份处理失败，回退直链：{exc!r}")
        return {}


def _render_listening_page(payload: Dict[str, Any]) -> str:
    """生成听力对照页（移动端兼容）：播放器在用户点击时动态创建（video 元素），
    绕开 QQ/微信 X5 与 iOS 的自动播放/audio 兼容问题；三档倍速 + 原文 + 空行答案区。"""
    h = html_mod.escape
    title = h(payload.get("title", ""))
    transcript = h(payload.get("transcript", ""))
    translation = h(payload.get("translation", ""))
    excerpt = int(payload.get("excerpt_seconds") or 0)
    excerpt_txt = f"本次摘选 {excerpt} 秒" if excerpt else "本次摘选 30–45 秒"
    files = payload.get("files", {}) or {}
    files_json = json_mod.dumps(files, ensure_ascii=False)
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
  .btn {{ display: inline-block; margin: 6px 8px 6px 0; padding: 12px 18px; border: none; border-radius: 8px;
         font-size: 17px; cursor: pointer; color: #fff; }}
  .b075 {{ background: #7f9d6b; }} .b100 {{ background: #4a7fc1; }} .b125 {{ background: #c97070; }}
  .btn.active {{ outline: 3px solid #333; }}
  .play-btn {{ display: block; width: 100%; padding: 18px 0; margin: 14px 0; border: none; border-radius: 10px;
               font-size: 22px; cursor: pointer; color: #fff; background: #4a7fc1; }}
  .meta {{ color: #666; font-size: 15px; margin: 8px 0; }}
  .note {{ background: #f2f7ff; border-left: 4px solid #4a7fc1; color: #555; font-size: 14px;
          line-height: 1.8; padding: 10px 12px; margin: 12px 0; }}
  .section {{ font-size: 19px; font-weight: bold; margin: 22px 0 6px; }}
  .text {{ font-size: 18px; line-height: 1.95; }}
  .gap {{ height: 1.6em; }}
  .hint {{ color: #999; font-size: 15px; margin: 4px 0 10px; }}
  .answer {{ font-size: 18px; line-height: 1.95; color: #444; }}
</style>
</head>
<body>
<h1>四级听力 · 三遍精听（{excerpt_txt}）</h1>
<p class="tip">第一遍 <b>1.25x</b> 快速听大意 → 第二遍 <b>1x</b> 正常精听 → 第三遍 <b>0.75x</b> 慢速核对细节。</p>
<button class="play-btn" id="toggle" onclick="togglePlay()">▶ 开始播放</button>
<audio id="player" playsinline webkit-playsinline preload="none"></audio>
<div>
  <button class="btn b125" id="b1.25" onclick="setRate('1.25')">1.25x 快速</button>
  <button class="btn b100 active" id="b1.0" onclick="setRate('1.0')">1x 正常</button>
  <button class="btn b075" id="b0.75" onclick="setRate('0.75')">0.75x 慢速</button>
</div>
<div class="meta"><span id="time">0:00 / 0:00</span> · <a href="javascript:restart()">↺ 重听</a> · <a href="javascript:stopPlay()">⏹ 停止</a> · <a id="sysopen" href="#" target="_blank" rel="noopener">用系统播放器打开（可后台听）</a></div>
<div id="err" class="hint" style="display:none;">当前环境无法播放：请点上方「用系统播放器打开」，或用手机自带浏览器（Safari/Chrome）打开本页。</div>
<p class="note">💡 后台播放：在手机浏览器（Safari/Chrome）中打开本页，点「开始播放」后切到其他 App，音频会继续播放；若在 QQ 邮箱内打开，请点右上角「在浏览器打开」后使用。</p>
<div class="meta">标题：{title}</div>
<div class="section">英文原文</div>
<div class="text">{transcript}</div>
<div class="gap"></div><div class="gap"></div><div class="gap"></div><div class="gap"></div><div class="gap"></div>
<div class="hint">（以下为答案，先听完/看完再翻）</div>
<div class="section">中文翻译</div>
<div class="answer">{translation}</div>
<script>
var FILES = {files_json};
var CUR = '1.0';
var player = document.getElementById('player');
var btn = document.getElementById('toggle');
var timeEl = document.getElementById('time');
document.getElementById('sysopen').href = FILES[CUR];

function fmt(t) {{
  if (!isFinite(t) || t < 0) return '0:00';
  var m = Math.floor(t / 60);
  var s = Math.floor(t % 60);
  return m + ':' + (s < 10 ? '0' : '') + s;
}}
function markActive(r) {{
  ['0.75', '1.0', '1.25'].forEach(function (x) {{
    var el = document.getElementById('b' + x);
    if (el) el.classList.toggle('active', x === r);
  }});
}}
function updateBtn() {{
  btn.textContent = player.paused ? '▶ 开始播放' : '⏸ 暂停';
}}
player.addEventListener('play', updateBtn);
player.addEventListener('pause', updateBtn);
player.addEventListener('timeupdate', function () {{
  timeEl.textContent = fmt(player.currentTime) + ' / ' + fmt(player.duration);
}});
player.addEventListener('loadedmetadata', function () {{
  timeEl.textContent = fmt(player.currentTime) + ' / ' + fmt(player.duration);
}});
player.addEventListener('ended', function () {{
  btn.textContent = '▶ 重新播放';
}});
player.addEventListener('error', function () {{
  document.getElementById('err').style.display = 'block';
}});
function ensureSrc(r) {{
  if (!player.getAttribute('src')) {{
    player.src = FILES[r];
  }}
}}
function setRate(r) {{
  if (!FILES[r]) return;
  CUR = r;
  markActive(r);
  document.getElementById('sysopen').href = FILES[r];
  try {{ player.playbackRate = parseFloat(r); }} catch (e) {{}}
}}
function togglePlay() {{
  ensureSrc(CUR);
  try {{ player.playbackRate = parseFloat(CUR); }} catch (e) {{}}
  if (player.paused) {{
    var p = player.play();
    if (p && p.catch) p.catch(function () {{
      document.getElementById('err').style.display = 'block';
    }});
  }} else {{
    player.pause();
  }}
  updateBtn();
}}
function restart() {{
  ensureSrc(CUR);
  player.currentTime = 0;
  try {{ player.playbackRate = parseFloat(CUR); }} catch (e) {{}}
  var p = player.play();
  if (p && p.catch) p.catch(function () {{
    document.getElementById('err').style.display = 'block';
  }});
  updateBtn();
}}
function stopPlay() {{
  player.pause();
  player.currentTime = 0;
  updateBtn();
}}
</script>
</body>
</html>
"""


def upload_listening_page(cfg: Dict[str, Any], today: date, slot: str, payload: Dict[str, Any]) -> str:
    """生成并上传听力对照页（public-read），返回页面 URL；失败返回空字符串。"""
    client = _cos_client(cfg)
    if not client:
        return ""
    try:
        html = _render_listening_page(payload)
        prefix = str(cfg.get("listening", {}).get("cos_key_prefix", "cet4/listening/"))
        expire = int(cfg.get("listening", {}).get("url_expire_days", 180)) * 86400
        key = f"{prefix}{today.isoformat()}-{slot}/index.html"
        client.put_bytes(
            key,
            html.encode("utf-8"),
            "text/html; charset=utf-8",
            acl="public-read",
            content_disposition="inline",
        )
        return client.presigned_url(
            key, {"response-content-disposition": "inline"}, expires_seconds=expire
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[音频] 听力对照页上传失败：{exc!r}")
        return ""
