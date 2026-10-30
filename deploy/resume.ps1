# -*- coding: utf-8 -*-
# 手动修复后恢复运行：清除暂停标记并补发待发送总结
param(
    [string]$Region = "ap-guangzhou",
    [string]$Namespace = "default",
    [string]$FunctionName = "news_summary"
)
tccli scf Invoke `
  --FunctionName $FunctionName `
  --Namespace $Namespace `
  --InvocationType Sync `
  --ClientContext '{"action":"resume"}'
