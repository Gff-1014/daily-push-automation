# 个人自动化推送项目集

一个运行在腾讯云 SCF 上的自动化推送集合，目前包含三个相互独立的子系统，共享同一套凭据与基础设施（腾讯云 COS、DeepSeek、SMTP）。

| 子系统 | 云函数 | 推送时间（北京时间） | 说明 |
| --- | --- | --- | --- |
| 央视新闻每日总结 | `news_summary` | 08:30 / 20:30 采集，09:00 / 21:00 发信 | 央视网多源采集 → LLM 分类评分排序 → 三大板块纯文字邮件 |
| 四级备考推送 | `cet4_push` | 08:00 / 18:00 | 单词计划 + SRS 复习 + 阅读 + 听力 + 汉译英 |
| 六级单词推送 | `vocab_push` | 08:00 / 18:00 | 100 天单词计划 + 滚动复习 + 阅读素材 |

## 目录结构

```
.
├─ src/
│  ├─ collector/        # 新闻源采集（央视网 JSONP、财联社、朝闻天下、新闻联播、国外源）
│  ├─ main.py           # 新闻总结流水线 + SCF 入口
│  ├─ llm.py            # DeepSeek 批量分类/评分/概述
│  ├─ scoring.py        # 混合加权、门槛、板块上限、来源加权
│  ├─ heat.py           # 聚合数据全网热搜榜（运行时热度）
│  ├─ formatter.py      # 今日热点 / 要闻速览 / 三大板块纯文本
│  ├─ notifier.py       # SMTP 直发
│  ├─ state.py          # 本地 / COS 状态（游标、指纹、暂停标记）
│  ├─ cet4/             # 四级备考推送子系统
│  └─ vocab/            # 六级单词推送子系统
├─ config/              # config.yaml / keywords.json / cet4.yaml / vocab.yaml
├─ deploy/              # 各子系统部署脚本 + 听力媒体代理
├─ scripts/             # 回测、预览、进度与状态运维脚本
├─ tests/               # 单元测试（76 项）
├─ docs/                # 各子系统大纲与专题文档
└─ README.md
```

## 快速开始

```bash
# 1. 安装依赖
python -m venv .venv
pip install -r requirements.txt

# 2. 配置环境变量：复制 .env.example 为 .env 并填写
#    DEEPSEEK_API_KEY / JUHE_API_KEY / SMTP_* / MAIL_TO
#    COS_BUCKET / CET4_MEDIA_BUCKET / MEDIA_PROXY_BASE_URL
#    TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY

# 3. 本地试跑（不发信、不写云端状态）
export LLM_MOCK=1        # Windows: $env:LLM_MOCK = "1"
python -m src.main morning --dry-run

# 4. 运行全部测试
python -m unittest discover -s tests -v
```

> `data/`（词表、学习状态、运行输出）属于个人运行数据，未纳入仓库；词表可用 `scripts/build_cet4.py`、`scripts/build_vocab.py` 生成，运行状态由云端 COS 或程序自动创建。

## 部署到腾讯云

```bash
python deploy/deploy.py              # 新闻总结：news_summary
python deploy/deploy_cet4.py         # 四级备考：cet4_push
python deploy/deploy_vocab.py        # 六级单词：vocab_push
python deploy/deploy_media_proxy.py  # 听力媒体代理（函数 URL）
```

脚本会依次：构建依赖包 → 直传代码（ZipFile）→ 创建/更新函数 → 配置环境变量 → 创建定时触发器。

## 主要配置项

| 配置 | 位置 | 说明 |
| --- | --- | --- |
| 采集窗口 | `config/config.yaml` → `slots.*.window_start` | 早间 20:30→08:30、晚间 08:30→20:30，无缝覆盖 24 小时 |
| 推送门槛 | `config/config.yaml` → `slots.*.thresholds` | 早间政治/经济/科技/国际 55、其他 65；晚间 55 |
| 板块上限 | `config/config.yaml` → `caps` | 主类各 10、次类 15、杂类 10 |
| 评分权重 | `config/config.yaml` → `scoring` | LLM 60% + 热度 25% + 关键词 15%，含来源加权 +8 |
| 关键词表 | `config/keywords.json` | 三档权重（重大/重要/一般）与新词标记 |

## 安全说明

- 仓库不含密钥或个人信息：API Key、邮箱授权码、COS 桶名、账号 ID、函数 URL 全部通过环境变量注入
- `.env`、`data/`、`logs/`、`deploy/package*/`、`*.zip` 已在 `.gitignore` 中排除
- 部署脚本只从 `.env` / 环境变量读取凭据，不写入代码或配置示例
- 提交前可自查：`git grep -nE "@qq\.com|@163\.com|AKID|sk-[A-Za-z0-9]{10,}"`（应为空）

## 文档

- [文档索引](docs/README.md)
- [新闻总结系统大纲](docs/每日新闻总结-大纲.md)
- [四级备考推送大纲](docs/四级备考推送-大纲.md)
- [六级单词推送大纲](docs/六级单词推送-大纲.md)
- [四级听力播放问题调整思路](docs/四级听力播放问题-调整思路.md)

## 成本概览

- 新闻总结：每日 2 次运行，DeepSeek 约 ¥10/月；SCF、COS、聚合数据均在免费额度内
- 四级 / 六级推送：复用同一 DeepSeek 额度；云函数与存储开销同样在免费额度内
