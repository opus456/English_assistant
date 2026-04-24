# CET6 Daily Flow · English Assistant

> 自动化抓取高质量英文文章 → 调用大模型生成 CET-6 风格阅读题与学习包 → 渲染 PDF → 每日通过 QQ 机器人（NapCat / OneBot）推送到手机 / 平板。

## ✨ 功能特性

- **素材抓取**：基于 RSS + Playwright 抓取 BBC、The Guardian、China Daily、ScienceDaily、AP News 等来源的文章。
- **难度筛选**：按词数（500–800）与自研可读性分值过滤，锁定 CET-6 难度。
- **AI 生成**：调用 DeepSeek / OpenAI 兼容接口生成仔细阅读题、长篇匹配题、词汇表、长难句解析。
- **PDF 排版**：WeasyPrint 渲染清爽现代风 A4 试卷与解析卷，适合平板手写批注。
- **自动推送**：通过 NapCat（OneBot 11 协议）每日定时私聊发送 PDF。
- **Docker 化**：`docker-compose` 一键拉起爬虫/生成器 + NapCat。

## 🧱 项目结构

```
English_Assistant/
├── scrape_articles.py          # 爬虫：RSS + Playwright
├── generate_cet6_materials.py  # LLM 出题 + PDF 渲染
├── qq_daily_sender.py          # NapCat 推送
├── cet6_generation_prompt.md   # 核心 Prompt
├── articles/                   # 按日期存放抓取与生成的产物
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── NAPCAT_DEPLOY.md            # NapCat 部署详细说明
```

## 🚀 快速开始

### 1. 本地运行

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

cp .env.example .env   # 填入 DEEPSEEK_API_KEY 等
```

抓取今日文章：

```bash
python scrape_articles.py --limit 1
```

生成试卷与解析 PDF：

```bash
python generate_cet6_materials.py
```

### 2. Docker 部署

```bash
cp .env.example .env   # 修改 QQ_TARGET_ID / TOKEN / API KEY
docker compose up -d
```

- NapCat WebUI：`http://<server>:6099`，用 `NAPCAT_WEBUI_TOKEN` 登录扫码。
- 详细 NapCat 登录流程见 `NAPCAT_DEPLOY.md`。

## ⚙️ 环境变量（摘要）

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | LLM 接入（默认 DeepSeek，可换任意 OpenAI 兼容端点） |
| `QQ_TARGET_TYPE` / `QQ_TARGET_ID` | 推送目标（private/group + QQ号/群号） |
| `NAPCAT_API_BASE` / `NAPCAT_ACCESS_TOKEN` | OneBot HTTP 接口地址与 token |
| `CET6_BOT_SEND_TIME` | 每日推送时间（默认 `07:30`） |
| `APP_TIMEZONE` | 时区（默认 `Asia/Shanghai`） |
| `HTTPS_PROXY` / `HTTP_PROXY` | 爬虫代理（境外站点访问必备） |

完整变量见 `.env.example`。

## 🕷️ 爬虫代理说明

爬虫脚本 `scrape_articles.py` 支持两种代理配置：

1. 环境变量：`HTTPS_PROXY=http://127.0.0.1:7890` 自动生效。
2. 命令行：`--proxy-server http://host:port`。

如果服务器在中国大陆，**BBC / The Guardian / AP News 默认都无法直连**，必须配置代理，见下文排障。

## 🩹 常见问题

- **抓取失败 / feed timeout**：多为网络不通，配置代理；必要时加 `--relax-feed-ssl --ignore-https-errors`。
- **PDF 字体缺失**：WeasyPrint 依赖系统字体，Dockerfile 已内置；本地需安装 `fonts-noto-cjk`。
- **NapCat 未登录**：打开 WebUI 扫码，首次登录后 `docker-data/napcat/qq` 会持久化凭据。
- **无魔法或部署到服务器上无法访问国外网站**：将scrape_articles.py中的`ARTICLE_SELECTORS`和`FEEDS`中的内容换成cn.py中的内容

## 📜 License

仅供学习研究，文章版权归原站点所有。禁止商用。
