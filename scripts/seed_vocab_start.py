# -*- coding: utf-8 -*-
"""播种六级单词系统开始日期：写入本地 state.json 并同步 COS。

用法:
    python scripts/seed_vocab_start.py 2026-08-27
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.vocab.state import GROUPS  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python scripts/seed_vocab_start.py YYYY-MM-DD")
        return 1
    start = sys.argv[1]
    date.fromisoformat(start)  # 校验格式

    cfg_path = ROOT / "config" / "vocab.yaml"
    state_path = ROOT / "data" / "vocab" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)

    state = {
        "started_on": start,
        "cursors": {g: 0 for g in GROUPS},
        "learned": {},
        "email_failures": 0,
        "paused": False,
        "pending_body": None,
        "day_plan": None,
        "last_run": None,
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[本地] state.json 已写入开始日期 {start}")

    # 尝试同步 COS（与云端部署的桶一致；失败仅提示，不影响本地）
    import yaml

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    vocab = data.get("vocab", {})
    cos = vocab.get("cos", {})
    bucket = cos.get("bucket", "")
    if not bucket:
        print("[COS] 本地配置未注入桶（COS_BUCKET），跳过云端同步")
        return 0
    try:
        env = {}
        dotenv_path = ROOT / ".env"
        for line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
        from src.cos_client import CosRestClient

        cli = CosRestClient(bucket, cos.get("region", "ap-guangzhou"), env.get("TENCENTCLOUD_SECRET_ID", ""), env.get("TENCENTCLOUD_SECRET_KEY", ""))
        cli.put_object(cos.get("key", "vocab/state.json"), json.dumps(state, ensure_ascii=False))
        print(f"[COS] 状态已同步到 {bucket}/{cos.get('key', 'vocab/state.json')}")
    except Exception as exc:  # noqa: BLE001
        print(f"[COS] 同步失败：{exc!r}（可稍后重试，本地状态已就绪）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
