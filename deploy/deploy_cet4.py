# -*- coding: utf-8 -*-
"""腾讯云 SCF 一键部署（四级备考推送，独立函数 cet4_push，不影响 news_summary / vocab_push）。

用法：
    python deploy/deploy_cet4.py --check          # 检查腾讯云密钥是否可用
    python deploy/deploy_cet4.py                   # 构建 + 上传 + 部署函数与触发器

凭证来源（按优先级）：环境变量 TENCENTCLOUD_SECRET_ID/KEY → ~/.tccli/default.credential
业务密钥从项目根目录 .env 只读读取（DEEPSEEK_API_KEY / SMTP_* / MAIL_TO）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
REGION = "ap-guangzhou"
NAMESPACE = "default"
FUNCTION_NAME = "cet4_push"
RUNTIME = "Python3.10"


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
COS_KEY = "scf/cet4_push.zip"
MEDIA_BUCKET = _dotenv_value("CET4_MEDIA_BUCKET")
TRIGGERS = [
    ("c0800", "0 0 8 * * * *", {"action": "run", "slot": "morning"}),
    ("c1800", "0 0 18 * * * *", {"action": "run", "slot": "evening"}),
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
    pkg = ROOT / "deploy" / "package_cet4"
    zip_path = ROOT / "deploy" / "cet4_push.zip"
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
    # 四级词库数据（云函数运行时读取；当前为空占位，词表范围确认后随构建更新）
    words_src = ROOT / "data" / "cet4" / "words.json"
    if words_src.exists():
        (pkg / "data" / "cet4").mkdir(parents=True, exist_ok=True)
        shutil.copy2(words_src, pkg / "data" / "cet4" / "words.json")
    # 注入 COS 桶配置（仅改打包副本，不动本地 config/cet4.yaml）
    cet4_cfg_path = pkg / "config" / "cet4.yaml"
    if cet4_cfg_path.exists():
        data = yaml.safe_load(cet4_cfg_path.read_text(encoding="utf-8")) or {}
        data.setdefault("cet4", {}).setdefault("cos", {})["bucket"] = COS_BUCKET
        data.setdefault("cet4", {}).setdefault("listening", {})["cos_bucket"] = MEDIA_BUCKET
        data.setdefault("cet4", {}).setdefault("listening", {})["cos_region"] = REGION
        cet4_cfg_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    (pkg / "main.py").write_text("from src.cet4.main import main_handler\n", encoding="utf-8")

    print("[3/4] 打包 zip ...")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in pkg.rglob("*"):
            if f.is_file():
                arcname = f.relative_to(pkg)
                info = zipfile.ZipInfo(str(arcname))
                with open(f, "rb") as src:
                    data = src.read()
                if f.name == "ffmpeg":
                    info.external_attr = 0o755 << 16  # Linux 可执行权限
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, data)
    return zip_path
def upload_zip_to_cos(secret_id: str, secret_key: str) -> None:
    """把部署包 zip 上传到 COS（包内含 ffmpeg，体积较大，走 COS 部署避免 API 体积限制）。"""
    from src.cet4.cos_client import CosRestClient

    client = CosRestClient(COS_BUCKET, REGION, secret_id, secret_key)
    data = (ROOT / "deploy" / "cet4_push.zip").read_bytes()
    client.put_bytes(COS_KEY, data, "application/zip")
    print(f"部署包已上传：cos://{COS_BUCKET}/{COS_KEY}（{len(data) // (1024 * 1024)} MB）")


def create_media_bucket(secret_id: str, secret_key: str) -> None:
    """确保独立媒体桶存在（无强制下载，页面/音频可内联播放）。"""
    from src.cet4.cos_client import CosRestClient

    import requests

    client = CosRestClient(MEDIA_BUCKET, REGION, secret_id, secret_key)
    resp = requests.put(
        f"https://{client.host}/",
        headers=client._signed("put", ""),
        timeout=30,
    )
    if resp.status_code in (200, 409):
        print(f"媒体桶就绪：{MEDIA_BUCKET}")
    else:
        print(f"媒体桶创建异常：{resp.status_code} {resp.text[:200]}")


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
        current_runtime = getattr(resp, "Runtime", "") or ""
    except Exception:  # noqa: BLE001
        exists = False
        failed_state = False
        current_runtime = ""

    if exists and (failed_state or current_runtime != RUNTIME):
        reason = f"Runtime 为 {current_runtime or '未知'}" if not failed_state else "处于 CreateFailed 状态"
        print(f"函数{reason}，删除后重建为 {RUNTIME} ...")
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
        code_req.CosBucketName = COS_BUCKET
        code_req.CosObjectName = COS_KEY
        code_req.CosBucketRegion = REGION
        scf_client.UpdateFunctionCode(code_req)
        _wait_active(scf_client)

        cfg_req = models.UpdateFunctionConfigurationRequest()
        cfg_req.FunctionName = FUNCTION_NAME
        cfg_req.Namespace = NAMESPACE
        cfg_req.Runtime = RUNTIME
        cfg_req.MemorySize = 512
        cfg_req.Timeout = 900
        cfg_req.Environment = env_obj
        scf_client.UpdateFunctionConfiguration(cfg_req)
    else:
        print("创建函数 ...")
        code = models.Code()
        code.CosBucketName = COS_BUCKET
        code.CosObjectName = COS_KEY
        code.CosBucketRegion = REGION

        create_req = models.CreateFunctionRequest()
        create_req.FunctionName = FUNCTION_NAME
        create_req.Namespace = NAMESPACE
        create_req.Code = code
        create_req.Handler = "main.main_handler"
        create_req.Runtime = RUNTIME
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
    mail_to = dotenv.get("MAIL_TO") or smtp_from_send_mail.get("MAIL_TO", "")
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
    create_media_bucket(secret_id, secret_key)
    upload_zip_to_cos(secret_id, secret_key)
    deploy_function(scf_client, env)
    deploy_triggers(scf_client)
    print("\ncet4_push 部署完成。可在控制台验证函数与触发器。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
