# 六级单词推送部署脚本（独立函数 vocab_push，不影响 news_summary）
param([switch]$Check)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if ($Check) {
    python "$root/deploy/deploy_vocab.py" --check
} else {
    python "$root/deploy/deploy_vocab.py"
}
