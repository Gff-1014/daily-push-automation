# -*- coding: utf-8 -*-
# 腾讯云 SCF 部署脚本（tccli 版）
# 前置条件：
#   1. pip install tccli
#   2. tccli configure（配置 SecretId / SecretKey / Region 广州 ap-guangzhou）
#   3. 已执行 .\build_package.ps1 生成 news_summary.zip，并上传到 COS
param(
    [string]$Region = "ap-guangzhou",
    [string]$Namespace = "default",
    [string]$FunctionName = "news_summary",
    [string]$CosBucket = "",          # 例如 news-summary-1250000000
    [string]$CosKey = "scf/news_summary.zip"
)
$ErrorActionPreference = "Stop"

if (-not $CosBucket) { throw "请提供 -CosBucket（存放 zip 的 COS 桶）" }

Write-Host "[1/4] 创建/更新函数 $FunctionName ..."
$envJson = '{"DEEPSEEK_API_KEY":"","JUHE_API_KEY":"","EMAIL_WEBHOOK_URL":"","COS_BUCKET":"' + $CosBucket + '","COS_REGION":"' + $Region + '"}'

tccli scf CreateFunction `
  --FunctionName $FunctionName `
  --Handler main.main_handler `
  --Runtime Python3.9 `
  --Namespace $Namespace `
  --MemorySize 512 `
  --Timeout 480 `
  --Environment.Variables $envJson `
  --Code.CosBucketName $CosBucket `
  --Code.CosObjectName $CosKey

Write-Host "[2/4] 配置环境变量（密钥请手动填入控制台或改用 --Environment.Variables）..."
Write-Host "   DEEPSEEK_API_KEY / JUHE_API_KEY / EMAIL_WEBHOOK_URL 需在函数配置中填写真实值"

Write-Host "[3/4] 创建 4 个定时触发器 ..."
$triggers = @(
  @{ Name = "t0830"; Cron = "0 30 8 * * * *"; Payload = '{"action":"run","slot":"morning"}' },
  @{ Name = "t2030"; Cron = "0 30 20 * * * *"; Payload = '{"action":"run","slot":"evening"}' },
  @{ Name = "t0900"; Cron = "0 0 9 * * * *"; Payload = '{"action":"email"}' },
  @{ Name = "t2100"; Cron = "0 0 21 * * * *"; Payload = '{"action":"email"}' }
)
foreach ($t in $triggers) {
  tccli scf CreateTrigger `
    --FunctionName $FunctionName `
    --Namespace $Namespace `
    --TriggerName $t.Name `
    --Type timer `
    --TriggerDesc $t.Cron `
    --CustomArgument $t.Payload `
    --Enable
}

Write-Host "[4/4] 完成。建议在控制台：函数配置 -> 环境变量 填写真实密钥。"
