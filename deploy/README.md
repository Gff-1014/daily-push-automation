# 腾讯云 SCF 部署说明

## 一、前置准备（只需一次）

1. 在腾讯云控制台创建 COS 存储桶（广州、私有读写、单 AZ），并在 `.env` 中配置 `COS_BUCKET=<你的桶名-APPID>`
2. 准备腾讯云 API 密钥（访问管理 CAM → API 密钥管理），写入项目根目录 `.env`（已 gitignore）：
   ```ini
   TENCENTCLOUD_SECRET_ID=你的SecretId
   TENCENTCLOUD_SECRET_KEY=你的SecretKey
   ```

## 二、一键部署

```powershell
# 1. 先验证密钥可用（不部署任何东西）
python deploy/deploy.py --check

# 2. 正式部署（自动完成：装依赖打包 → 上传 COS → 创建/更新函数 → 创建 4 个定时触发器）
python deploy/deploy.py
```

业务密钥（DeepSeek / 聚合数据）从项目根目录 `.env` 自动读取并写入云函数环境变量，无需手动填控制台。

## 三、部署结果

| 触发时间 | 事件 | 用途 |
| --- | --- | --- |
| 08:30 | `{"action":"run","slot":"morning"}` | 早间采集总结 |
| 09:00 | `{"action":"email"}` | 早间邮件发送 |
| 20:30 | `{"action":"run","slot":"evening"}` | 晚间采集总结 |
| 21:00 | `{"action":"email"}` | 晚间邮件发送 |

函数：`news_summary`（Python 3.9，512MB，超时 480 秒），入口 `main.main_handler`。

## 四、失败恢复

邮件连续 3 次发送失败后系统自动暂停。修复问题后，在云函数控制台用以下事件手动调用一次函数：

```json
{"action": "resume"}
```

恢复动作：清除暂停标记 → 补发未送达总结 → 恢复正常调度。

## 五、本地测试

```powershell
$env:LLM_MOCK = "1"      # 无密钥时用模拟 LLM 验证全流程
python -m src.main morning --dry-run
```

真实密钥测试：项目根目录 `.env`（已 gitignore）已配置 `DEEPSEEK_API_KEY`、`JUHE_API_KEY`。
