# 四级备考推送部署脚本（独立函数 cet4_push，不影响 news_summary / vocab_push）
param([switch]$Check)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if ($Check) {
    python "$root/deploy/deploy_cet4.py" --check
} else {
    python "$root/deploy/deploy_cet4.py"
}
