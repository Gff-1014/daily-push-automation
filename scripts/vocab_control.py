# -*- coding: utf-8 -*-
"""六级推送暂停 / 恢复 / 状态查看（操作云端 COS 状态与本地状态）。

用法:
    python scripts/vocab_control.py pause     # 暂停推送（触发器仍保留，执行时跳过）
    python scripts/vocab_control.py resume    # 恢复推送
    python scripts/vocab_control.py status    # 查看当前状态
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deploy.deploy_vocab import _credentials, _load_dotenv  # noqa: E402
from src.cos_client import CosRestClient  # noqa: E402

REGION = "ap-guangzhou"
KEY = "vocab/state.json"
LOCAL_STATE = ROOT / "data" / "vocab" / "state.json"


def _client() -> CosRestClient:
    env = _load_dotenv()
    bucket = env.get("COS_BUCKET", "")
    if not bucket:
        raise SystemExit("请在 .env 中配置 COS_BUCKET")
    return CosRestClient(
        bucket,
        REGION,
        env.get("TENCENTCLOUD_SECRET_ID", ""),
        env.get("TENCENTCLOUD_SECRET_KEY", ""),
    )


def _load_state() -> dict:
    raw = _client().get_object(KEY)
    if not raw:
        raise SystemExit("云端无状态文件")
    return json.loads(raw)


def _save_state(data: dict) -> None:
    body = json.dumps(data, ensure_ascii=False)
    _client().put_object(KEY, body)
    LOCAL_STATE.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_STATE.write_text(body, encoding="utf-8")


def _print_status(data: dict) -> None:
    learned = data.get("learned", {})
    print("paused:", data.get("paused"))
    print("started_on:", data.get("started_on"))
    print("last_run:", data.get("last_run"))
    print("learned_total:", len(learned))
    print("cursors:", data.get("cursors"))
    print("email_failures:", data.get("email_failures"))
    print("pending_body 存在:", bool(data.get("pending_body")))


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("pause", "resume", "status"):
        print("用法: python scripts/vocab_control.py pause|resume|status")
        return 1
    action = sys.argv[1]
    data = _load_state()

    if action == "pause":
        data["paused"] = True
        _save_state(data)
        print("[已暂停] 六级推送：触发器保留，08:00 / 18:00 执行时将直接跳过")
    elif action == "resume":
        data["paused"] = False
        data["email_failures"] = 0
        _save_state(data)
        print("[已恢复] 六级推送：按原计划继续，下次触发正常推送")
    _print_status(_load_state())
    return 0


if __name__ == "__main__":
    sys.exit(main())
