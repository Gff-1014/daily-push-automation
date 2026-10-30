# -*- coding: utf-8 -*-
# 构建腾讯云 SCF 部署包：安装依赖 + 复制代码 + 打包 zip
param(
    [string]$PythonExe = "python"
)
$ErrorActionPreference = "Stop"
$deployDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $deployDir
$pkg = Join-Path $deployDir "package"

if (Test-Path $pkg) { Remove-Item -Recurse -Force $pkg }
New-Item -ItemType Directory -Path $pkg | Out-Null

Write-Host "[1/3] 安装依赖到 package/ ..."
& $PythonExe -m pip install -r (Join-Path $root "requirements.txt") -t $pkg --no-compile --quiet
if ($LASTEXITCODE -ne 0) { throw "pip 安装失败" }

Write-Host "[2/3] 复制 src 与 config ..."
Copy-Item (Join-Path $root "src") (Join-Path $pkg "src") -Recurse
Copy-Item (Join-Path $root "config") (Join-Path $pkg "config") -Recurse

Write-Host "[3/3] 打包 news_summary.zip ..."
$zip = Join-Path $deployDir "news_summary.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path (Join-Path $pkg "*") -DestinationPath $zip -Force
Write-Host "完成: $zip"
