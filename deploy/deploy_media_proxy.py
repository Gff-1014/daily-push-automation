# -*- coding: utf-8 -*-
"""部署 cet4 听力媒体代理（SCF Web 函数 + 函数 URL）。

背景：2024-01-01 之后新建的腾讯云 COS 桶，默认域名强制下载、无法内联预览。
方案二：独立 SCF 函数从 COS 读取对象，自己控制响应头（正确 Content-Type、
Content-Disposition: inline、CORS），通过"函数 URL"（官方替代已下线的 API 网关）
对外提供 HTTPS 直连，无需域名备案。

用法：
    python deploy/deploy_media_proxy.py --check   # 检查腾讯云密钥
    python deploy/deploy_media_proxy.py           # 部署函数 + 函数 URL + 回填配置

凭证来源：环境变量 TENCENTCLOUD_SECRET_ID/KEY → 项目根 .env。
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGION = "ap-guangzhou"
NAMESPACE = "default"
FUNCTION_NAME = "cet4_media_proxy"
TRIGGER_NAME = "func_url"


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


MEDIA_BUCKET = _dotenv_value("CET4_MEDIA_BUCKET")
MEDIA_KEY_PREFIX = "cet4/listening/"
PROXY_DIR = ROOT / "deploy" / "media_proxy"
ZIP_PATH = ROOT / "deploy" / "media_proxy.zip"
CONFIG_FILES = [ROOT / "config" / "cet4.yaml", ROOT / "config" / "cet4.test.yaml"]


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
    hp.reqTimeout = 120
    cp = ClientProfile()
    cp.httpProfile = hp
    return scf_client.ScfClient(cred, REGION, cp)


def build_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in ("main.py", "cos_reader.py", "server.py"):
            zf.write(PROXY_DIR / name, arcname=name)
        # scf_bootstrap：Web 函数启动文件，必须可执行
        info = zipfile.ZipInfo("scf_bootstrap")
        info.external_attr = 0o755 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, (PROXY_DIR / "scf_bootstrap").read_text(encoding="utf-8"))
    return buf.getvalue()


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


def _env_object(secret_id: str, secret_key: str) -> dict:
    from tencentcloud.scf.v20180416 import models

    env = models.Environment()
    env.Variables = [
        {"Key": "MEDIA_BUCKET", "Value": MEDIA_BUCKET},
        {"Key": "COS_REGION", "Value": REGION},
        {"Key": "MEDIA_KEY_PREFIX", "Value": MEDIA_KEY_PREFIX},
        {"Key": "TENCENT_SECRET_ID", "Value": secret_id},
        {"Key": "TENCENT_SECRET_KEY", "Value": secret_key},
    ]
    return env


def _public_net() -> dict:
    from tencentcloud.scf.v20180416 import models

    obj = models.PublicNetConfigIn()
    obj.PublicNetStatus = "ENABLE"
    eip = models.EipConfigIn()
    eip.EipStatus = "DISABLE"
    obj.EipConfig = eip
    return obj


def deploy_function(scf_client, secret_id: str, secret_key: str, zip_bytes: bytes) -> None:
    from tencentcloud.scf.v20180416 import models

    zip_b64 = base64.b64encode(zip_bytes).decode("ascii")
    exists = False
    failed = False
    try:
        get_req = models.GetFunctionRequest()
        get_req.FunctionName = FUNCTION_NAME
        get_req.Namespace = NAMESPACE
        resp = scf_client.GetFunction(get_req)
        exists = resp.FunctionName == FUNCTION_NAME
        failed = getattr(resp, "Status", "") == "CreateFailed"
        ftype = getattr(resp, "Type", "") or "Event"
    except Exception:  # noqa: BLE001
        exists = False
        ftype = ""

    if exists and (failed or ftype != "HTTP"):
        reason = "类型不是 Web 函数" if not failed else "处于 CreateFailed 状态"
        print(f"函数{reason}，删除后重建 ...")
        del_req = models.DeleteFunctionRequest()
        del_req.FunctionName = FUNCTION_NAME
        del_req.Namespace = NAMESPACE
        scf_client.DeleteFunction(del_req)
        for _ in range(20):
            time.sleep(3)
            try:
                get_req2 = models.GetFunctionRequest()
                get_req2.FunctionName = FUNCTION_NAME
                get_req2.Namespace = NAMESPACE
                scf_client.GetFunction(get_req2)
            except Exception:  # noqa: BLE001
                break
        exists = False

    env_obj = _env_object(secret_id, secret_key)
    if exists:
        print("更新函数代码与配置 ...")
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
        cfg_req.MemorySize = 256
        cfg_req.Timeout = 30
        cfg_req.Environment = env_obj
        cfg_req.PublicNetConfig = _public_net()
        scf_client.UpdateFunctionConfiguration(cfg_req)
    else:
        print("创建 Web 函数 ...")
        code = models.Code()
        code.ZipFile = zip_b64

        create_req = models.CreateFunctionRequest()
        create_req.FunctionName = FUNCTION_NAME
        create_req.Namespace = NAMESPACE
        create_req.Code = code
        create_req.Handler = "main.main_handler"
        create_req.Runtime = "Python3.9"
        create_req.MemorySize = 256
        create_req.Timeout = 30
        # Web 函数（HTTP 直通）+ 函数 URL：请求/响应直接透传，
        # server.py 内置 HTTP 服务写回原始二进制，Content-Type 完全可控。
        create_req.Type = "HTTP"
        create_req.Environment = env_obj
        create_req.PublicNetConfig = _public_net()
        create_req.Description = "cet4 听力媒体代理（COS 内联预览，绕过强制下载）"
        scf_client.CreateFunction(create_req)
        _wait_active(scf_client)
    print("函数部署完成")


def create_function_url(scf_client) -> None:
    from tencentcloud.scf.v20180416 import models

    existing = False
    try:
        list_req = models.ListTriggersRequest()
        list_req.FunctionName = FUNCTION_NAME
        list_req.Namespace = NAMESPACE
        resp = scf_client.ListTriggers(list_req)
        existing = any(getattr(t, "Type", "") == "http" for t in resp.Triggers or [])
    except Exception:  # noqa: BLE001
        existing = False

    if existing:
        print(f"函数 URL（{TRIGGER_NAME}）已存在，跳过创建")
        return

    desc = {
        "AuthType": "NONE",
        "NetConfig": {"EnableIntranet": False, "EnableExtranet": True},
        "CorsConfig": {
            "Enable": True,
            "Origins": ["*"],
            "Headers": ["content-type", "range", "authorization"],
            "Methods": ["GET", "HEAD", "OPTIONS"],
            "ExposeHeaders": ["*"],
            "MaxAge": 3600,
            "Credentials": False,
        },
    }
    req = models.CreateTriggerRequest()
    req.FunctionName = FUNCTION_NAME
    req.Namespace = NAMESPACE
    req.TriggerName = TRIGGER_NAME
    req.Type = "http"
    req.TriggerDesc = json.dumps(desc, ensure_ascii=False)
    req.Enable = "OPEN"
    req.Description = "cet4 听力媒体代理公网 URL"
    scf_client.CreateTrigger(req)
    print("函数 URL 创建成功")


def get_function_url(scf_client) -> str:
    from tencentcloud.scf.v20180416 import models

    for _ in range(20):
        time.sleep(3)
        try:
            list_req = models.ListTriggersRequest()
            list_req.FunctionName = FUNCTION_NAME
            list_req.Namespace = NAMESPACE
            resp = scf_client.ListTriggers(list_req)
            for t in resp.Triggers or []:
                if getattr(t, "Type", "") != "http":
                    continue
                bound = getattr(t, "BoundResources", "") or ""
                if bound:
                    try:
                        items = json.loads(bound)
                    except Exception:  # noqa: BLE001
                        items = [bound]
                    for item in items:
                        if isinstance(item, dict) and item.get("url"):
                            return item["url"]
                        if isinstance(item, str) and item.startswith("https://"):
                            return item
                # 兜底：从 TriggerDesc.NetConfig.ExtranetUrl 取公网地址
                desc = getattr(t, "TriggerDesc", "") or ""
                if desc:
                    try:
                        data = json.loads(desc)
                        url = (data.get("NetConfig") or {}).get("ExtranetUrl", "")
                        if url:
                            return url
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            pass
    return ""


def update_configs(url: str) -> None:
    if not url:
        print("未获取到函数 URL，跳过配置回填")
        return
    for path in CONFIG_FILES:
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        listening = data.setdefault("cet4", {}).setdefault("listening", {})
        listening["proxy_base_url"] = url
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"已写入 {path.relative_to(ROOT)} -> listening.proxy_base_url = {url}")


def check_credentials() -> None:
    secret_id, secret_key = _credentials()
    if not (secret_id and secret_key):
        print("未找到腾讯云密钥。请任选其一：")
        print("  1) 设置环境变量 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY")
        print("  2) 在项目 .env 中填写 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY")
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


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        check_credentials()
        return 0

    secret_id, secret_key = _credentials()
    if not (secret_id and secret_key):
        check_credentials()
        return 1

    scf_client = _make_scf_client(secret_id, secret_key)
    zip_bytes = build_zip()
    deploy_function(scf_client, secret_id, secret_key, zip_bytes)
    create_function_url(scf_client)
    url = get_function_url(scf_client)
    if not url:
        print("警告：未能获取函数 URL，请到控制台函数 URL 页面查看公网地址后手动回填配置")
        return 1
    update_configs(url)
    print(f"\n媒体代理 URL：{url}")
    print("验证命令：")
    print(f"  curl -s -D - -o /dev/null {url}/{MEDIA_KEY_PREFIX}2026-08-29-morning/index.html")
    print(f"  curl -s -D - -o /dev/null {url}/{MEDIA_KEY_PREFIX}2026-08-29-morning/1.0.mp3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
