# -*- coding: utf-8 -*-
"""修改云端 vocab_push 的收件邮箱（不改 .env，不影响其他项目）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deploy.deploy_vocab import _credentials, _load_dotenv, _make_scf_client  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python scripts/set_vocab_mailto.py 收件邮箱")
        return 1
    mail_to = sys.argv[1]
    env = _load_dotenv()
    scf = _make_scf_client(*_credentials())
    from tencentcloud.scf.v20180416 import models

    get_req = models.GetFunctionRequest()
    get_req.FunctionName = "vocab_push"
    get_req.Namespace = "default"
    resp = scf.GetFunction(get_req)
    variables = {v.Key: v.Value for v in (resp.Environment.Variables or [])}
    variables["MAIL_TO"] = mail_to

    env_obj = models.Environment()
    env_obj.Variables = [{"Key": k, "Value": str(v)} for k, v in variables.items()]
    cfg_req = models.UpdateFunctionConfigurationRequest()
    cfg_req.FunctionName = "vocab_push"
    cfg_req.Namespace = "default"
    cfg_req.Environment = env_obj
    scf.UpdateFunctionConfiguration(cfg_req)
    print(f"已更新 vocab_push MAIL_TO = {mail_to}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
