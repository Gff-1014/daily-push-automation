# -*- coding: utf-8 -*-
"""腾讯云 SCF 一键部署（六级单词推送，独立函数 vocab_push，不影响 news_summary）。

用法：
    python deploy/deploy_vocab.py --check          # 检查腾讯云密钥是否可用
    python deploy/deploy_vocab.py                   # 构建 + 上传 + 部署函数与触发器

凭证来源（按优先级）：环境变量 TENCENTCLOUD_SECRET_ID/KEY → ~/.tccli/default.credential
业务密钥从项目根目录 .env 只读读取（DEEPSEEK_API_KEY / SMTP_* / MAIL_TO）。
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGION = "ap-guangzhou"
NAMESPACE = "default"
FUNCTION_NAME = "vocab_push"


def _dotenv_value(name: str, default: str = "") -> str:
    if os.environ.get(name):
        return os.environ[name]
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    return default


COS_BUCKET = _dotenv_value("COS_BUCKET")
COS_KEY = "scf/vocab_push.zip"
# 六级固定收件邮箱：不随 .env 变化（.env 与四级项目共享，可能被其他项目修改）
VOCAB_MAIL_TO = _dotenv_value("VOCAB_MAIL_TO") or _dotenv_value("MAIL_TO")
TRIGGERS = [
    ("v0800", "0 0 8 * * * *", {"action": "run", "slot": "morning"}),
    ("v1800", "0 0 18 * * * *", {"action": "run", "slot": "evening"}),
]


def _load_dotenv() -> dict:
    env = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _credentials() -> tuple:
    dotenv = _load_dotenv()
    secret_id = (
        os.environ.get("TENCENTCLOUD_SECRET_ID")
        or os.environ.get("TENCENT_SECRET_ID")
        or dotenv.get("TENCENTCLOUD_SECRET_ID")
        or dotenv.get("TENCENT_SECRET_ID")
        or ""
    )
    secret_key = (
        os.environ.get("TENCENTCLOUD_SECRET_KEY")
        or os.environ.get("TENCENT_SECRET_KEY")
        or dotenv.get("TENCENTCLOUD_SECRET_KEY")
        or dotenv.get("TENCENT_SECRET_KEY")
        or ""
    )
    if not (secret_id and secret_key):
        cfg = Path.home() / ".tccli" / "default.credential"
        if cfg.exists():
            data = json.loads(cfg.read_text(encoding="utf-8"))
            secret_id = data.get("secretId", "")
            secret_key = data.get("secretKey", "")
    return secret_id, secret_key


def _make_scf_client(secret_id: str, secret_key: str):
    from tencentcloud.common import credential
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile
    from tencentcloud.scf.v20180416 import scf_client

    cred = credential.Credential(secret_id, secret_key)
    hp = HttpProfile()
    hp.endpoint = "scf.tencentcloudapi.com"
    hp.reqTimeout = 600
    cp = ClientProfile()
    cp.httpProfile = hp
    return scf_client.ScfClient(cred, REGION, cp)


def check_credentials() -> None:
    secret_id, secret_key = _credentials()
    if not (secret_id and secret_key):
        print("未找到腾讯云密钥。请任选其一：")
        print("  1) 设置环境变量 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY")
        print("  2) 运行 pip install tccli && tccli configure 后重试")
        sys.exit(1)
    try:
        client = _make_scf_client(secret_id, secret_key)
        from tencentcloud.scf.v20180416 import models

        req = models.ListFunctionsRequest()
        req.Namespace = NAMESPACE
        resp = client.ListFunctions(req)
        names = [getattr(f, "FunctionName", "") for f in resp.Functions or []]
        print(f"密钥可用。当前命名空间函数：{names}")
    except Exception as exc:  # noqa: BLE001
        print(f"密钥校验失败：{exc}")
        sys.exit(1)


def build_package() -> Path:
    pkg = ROOT / "deploy" / "package_vocab"
    zip_path = ROOT / "deploy" / "vocab_push.zip"
    if pkg.exists():
        shutil.rmtree(pkg)
    pkg.mkdir(parents=True)

    print("[1/4] 安装运行依赖到 package/ ...")
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv.exe")
    if not os.path.exists(uv):
        raise SystemExit("未找到 uv，请先安装 uv 或改用系统 pip 打包")
    subprocess.run(
        [uv, "pip", "install", "--target", str(pkg), "-r", str(ROOT / "requirements.txt"), "--quiet"],
        check=True,
    )

    print("[2/4] 复制代码与配置 ...")
    shutil.copytree(ROOT / "src", pkg / "src")
    shutil.copytree(ROOT / "config", pkg / "config")
    # 词库数据（云函数运行时读取）
    words_src = ROOT / "data" / "vocab" / "words.json"
    if words_src.exists():
        (pkg / "data" / "vocab").mkdir(parents=True, exist_ok=True)
        shutil.copy2(words_src, pkg / "data" / "vocab" / "words.json")
    # 注入 COS 桶配置（仅改打包副本，不动本地 config/vocab.yaml）
    vocab_cfg_path = pkg / "config" / "vocab.yaml"
    if vocab_cfg_path.exists():
        data = yaml.safe_load(vocab_cfg_path.read_text(encoding="utf-8")) or {}
        data.setdefault("vocab", {}).setdefault("cos", {})["bucket"] = COS_BUCKET
        vocab_cfg_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (pkg / "main.py").write_text("from src.vocab.main import main_handler\n", encoding="utf-8")

    print("[3/4] 打包 zip ...")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in pkg.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(pkg))
    return zip_path


def _zip_b64(zip_path: Path) -> str:
    return base64.b64encode(zip_path.read_bytes()).decode("ascii")


def _wait_active(scf_client) -> None:
    from tencentcloud.scf.v20180416 import models

    for _ in range(30):
        time.sleep(2)
        try:
            req = models.GetFunctionRequest()
            req.FunctionName = FUNCTION_NAME
            req.Namespace = NAMESPACE
            resp = scf_client.GetFunction(req)
            if getattr(resp, "Status", "") == "Active":
                return
        except Exception:  # noqa: BLE001
            pass
    print("等待函数 Active 超时，继续 ...")


def _read_send_mail_env(scf_client) -> dict:
    from tencentcloud.scf.v20180416 import models

    req = models.GetFunctionRequest()
    req.FunctionName = "send_mail"
    req.Namespace = NAMESPACE
    resp = scf_client.GetFunction(req)
    env = {}
    for v in resp.Environment.Variables or []:
        env[v.Key] = v.Value
    return env


def deploy_function(scf_client, env: dict) -> None:
    from tencentcloud.scf.v20180416 import models

    env_vars = [{"Key": k, "Value": str(v)} for k, v in env.items()]
    env_obj = models.Environment()
    env_obj.Variables = env_vars

    exists = False
    failed_state = False
    try:
        get_req = models.GetFunctionRequest()
        get_req.FunctionName = FUNCTION_NAME
        get_req.Namespace = NAMESPACE
        resp = scf_client.GetFunction(get_req)
        exists = resp.FunctionName == FUNCTION_NAME
        failed_state = getattr(resp, "Status", "") == "CreateFailed"
    except Exception:  # noqa: BLE001
        exists = False

    zip_b64 = _zip_b64(ROOT / "deploy" / "vocab_push.zip")
    if exists and failed_state:
        print("函数处于 CreateFailed 状态，删除后重建 ...")
        del_req = models.DeleteFunctionRequest()
        del_req.FunctionName = FUNCTION_NAME
        del_req.Namespace = NAMESPACE
        scf_client.DeleteFunction(del_req)
        exists = False
        for _ in range(20):
            time.sleep(3)
            try:
                get_req2 = models.GetFunctionRequest()
                get_req2.FunctionName = FUNCTION_NAME
                get_req2.Namespace = NAMESPACE
                scf_client.GetFunction(get_req2)
            except Exception:  # noqa: BLE001
                break
        else:
            print("等待删除超时，继续尝试创建 ...")

    if exists:
        print("函数已存在，更新代码与配置 ...")
        code_req = models.UpdateFunctionCodeRequest()
        code_req.FunctionName = FUNCTION_NAME
        code_req.Namespace = NAMESPACE
        code_req.Handler = "main.main_handler"
        code_req.ZipFile = zip_b64
        scf_client.UpdateFunctionCode(code_req)
        _wait_active(scf_client)

        cfg_req = models.UpdateFunctionConfigurationRequest()
        cfg_req.FunctionName = FUNCTION_NAME
        cfg_req.Namespace = NAMESPACE
        cfg_req.MemorySize = 512
        cfg_req.Timeout = 900
        cfg_req.Environment = env_obj
        scf_client.UpdateFunctionConfiguration(cfg_req)
    else:
        print("创建函数 ...")
        code = models.Code()
        code.ZipFile = zip_b64

        create_req = models.CreateFunctionRequest()
        create_req.FunctionName = FUNCTION_NAME
        create_req.Namespace = NAMESPACE
        create_req.Code = code
        create_req.Handler = "main.main_handler"
        create_req.Runtime = "Python3.9"
        create_req.MemorySize = 512
        create_req.Timeout = 900
        create_req.Environment = env_obj
        scf_client.CreateFunction(create_req)
        _wait_active(scf_client)
    print("函数部署完成")


def deploy_triggers(scf_client) -> None:
    from tencentcloud.scf.v20180416 import models

    existing = set()
    try:
        list_req = models.ListTriggersRequest()
        list_req.FunctionName = FUNCTION_NAME
        list_req.Namespace = NAMESPACE
        resp = scf_client.ListTriggers(list_req)
        existing = {t.TriggerName for t in resp.Triggers or []}
    except Exception:  # noqa: BLE001
        existing = set()

    for name, cron, payload in TRIGGERS:
        if name in existing:
            print(f"触发器 {name} 已存在，跳过")
            continue
        try:
            req = models.CreateTriggerRequest()
            req.FunctionName = FUNCTION_NAME
            req.Namespace = NAMESPACE
            req.TriggerName = name
            req.Type = "timer"
            req.TriggerDesc = cron
            req.CustomArgument = json.dumps(payload, ensure_ascii=False)
            req.Enable = "OPEN"
            scf_client.CreateTrigger(req)
            print(f"触发器 {name} ({cron}) 创建成功")
        except Exception as exc:  # noqa: BLE001
            print(f"触发器 {name} 创建失败（可能已存在）：{exc}")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        check_credentials()
        return 0

    secret_id, secret_key = _credentials()
    if not (secret_id and secret_key):
        check_credentials()
        return 1

    dotenv = _load_dotenv()
    scf_client = _make_scf_client(secret_id, secret_key)
    smtp_from_send_mail = {}
    try:
        smtp_from_send_mail = _read_send_mail_env(scf_client)
    except Exception:  # noqa: BLE001
        print("提示：读取 send_mail 环境变量失败，将使用 .env 中的 SMTP 配置（如有）")

    smtp_user = dotenv.get("SMTP_USER") or smtp_from_send_mail.get("SMTP_USER", "")
    smtp_auth = dotenv.get("SMTP_AUTH_CODE") or smtp_from_send_mail.get("SMTP_AUTH_CODE", "")
    mail_to = VOCAB_MAIL_TO
    if smtp_user:
        print(f"SMTP 配置已同步：发件 {smtp_user} → 收件 {mail_to}")

    env = {
        "DEEPSEEK_API_KEY": dotenv.get("DEEPSEEK_API_KEY", ""),
        "EMAIL_WEBHOOK_URL": dotenv.get("EMAIL_WEBHOOK_URL", ""),
        "SMTP_HOST": dotenv.get("SMTP_HOST", "smtp.qq.com"),
        "SMTP_PORT": dotenv.get("SMTP_PORT", "465"),
        "SMTP_USER": smtp_user,
        "SMTP_AUTH_CODE": smtp_auth,
        "MAIL_TO": mail_to,
        "COS_BUCKET": COS_BUCKET,
        "COS_REGION": REGION,
        "TZ": "Asia/Shanghai",
        "TENCENT_SECRET_ID": secret_id,
        "TENCENT_SECRET_KEY": secret_key,
    }

    build_package()
    deploy_function(scf_client, env)
    deploy_triggers(scf_client)
    print("\nvocab_push 部署完成。可在控制台验证函数与触发器。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
