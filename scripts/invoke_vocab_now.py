# -*- coding: utf-8 -*-
"""立即调用云端 vocab_push 一次（用于验证；今天会跳过，不发邮件）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deploy.deploy_vocab import _credentials, _load_dotenv, _make_scf_client  # noqa: E402


def main() -> int:
    env = _load_dotenv()
    scf = _make_scf_client(*_credentials())
    from tencentcloud.scf.v20180416 import models

    req = models.InvokeRequest()
    req.FunctionName = "vocab_push"
    req.Namespace = "default"
    req.InvocationType = "RequestResponse"
    req.ClientContext = json.dumps({"action": "run", "slot": "morning"})
    resp = scf.Invoke(req)
    out = resp.Result
    print("STATUS:", getattr(out, "Status", None))
    print("RETMSG:", (getattr(out, "RetMsg", None) or "")[:500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
