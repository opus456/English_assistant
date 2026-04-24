# CET6 Daily Flow 部署指南

## 这个系统是做什么的？

```
每天 06:00  →  自动抓取 BBC 文章
             →  调用 DeepSeek AI 生成六级题目+解析
             →  生成 test.pdf（试卷）和 answer.pdf（解析卷）
每天 07:30  →  通过机器人 QQ 账号把两个 PDF 发给你
```

## 名词解释

- **NapCat**：一个程序，帮你登录一个 QQ 小号（机器人账号），让代码能自动发 QQ 消息。
- **Token / WebUI Token**：你自己随便设的密码字符串，不需要去任何平台申请，保证安全即可。
- **DeepSeek API Key**：去 [platform.deepseek.com](https://platform.deepseek.com/) 注册并充值少量金额（每天调用费用约几分钱）即可获得。

## 准备清单

- [ ] 一台安装了 Docker 的 Linux 服务器
- [ ] 一个 QQ 小号（作为机器人账号，不能是你自己常用的号）
- [ ] DeepSeek API Key（[platform.deepseek.com](https://platform.deepseek.com/) 注册）
- [ ] 知道你自己的 QQ 号（接收消息用）

## 文件说明

- `scrape_articles.py`：每日抓取英文文章
- `generate_cet6_materials.py`：AI 生成六级材料并输出 PDF
- `qq_daily_sender.py`：定时通过 QQ 推送 PDF
- `run_daily.sh`：每日自动化脚本（抓取+生成）
- `Dockerfile`：服务镜像
- `docker-compose.yml`：启动全部服务
- `.env.example`：环境变量模板

## 第一步：上传项目到服务器

```bash
# 在本机执行，把项目上传到服务器
scp -r English_assistant 你的用户名@服务器IP:/home/你的用户名/english_assistant

# 登录服务器
ssh 你的用户名@服务器IP
cd /home/你的用户名/english_assistant
```

## 第二步：配置环境变量

```bash
cp .env.example .env
nano .env   # 或 vim .env
```

**必须修改的项目：**

| 变量 | 说明 | 示例 |
|------|------|------|
| `QQ_TARGET_ID` | 你自己的 QQ 号（接收消息） | `123456789` |
| `NAPCAT_WEBUI_TOKEN` | 浏览器登录机器人 QQ 的密码，自己编 | `my-webui-pass-2024` |
| `NAPCAT_ACCESS_TOKEN` | API 访问令牌，自己编一个字符串 | `my-secret-abc123` |
| `DEEPSEEK_API_KEY` | DeepSeek AI 的 API 密钥 | `sk-xxxx...` |

**可选修改：**

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `GENERATE_TIME` | 每天几点生成文章+PDF | `06:00` |
| `CET6_BOT_SEND_TIME` | 每天几点发 QQ 消息 | `07:30` |

## 第三步：启动所有容器

```bash
docker compose up -d --build
```

启动后会有 **三个** 容器：

- `cet6-napcat` — 机器人 QQ 程序
- `cet6-daily-generator` — 每天自动抓取文章并生成 PDF
- `cet6-qq-pusher` — 每天定时发 QQ 消息

## 第四步：登录机器人 QQ 账号（一次性操作）

用浏览器打开：

```
http://你的服务器IP:6099/webui
```

输入 `.env` 里的 `NAPCAT_WEBUI_TOKEN` 登录，然后：

1. **扫码登录**：用你的 QQ 小号（机器人账号）扫码登录
2. **配置 OneBot HTTP Server**：进入 "网络配置" → "新建" → 选 "HTTP Server"：
   ```
   Host:  0.0.0.0
   Port:  3000
   Token: 填写 .env 里的 NAPCAT_ACCESS_TOKEN（必须完全一致）
   ```
   点击保存并启用。

## 第五步：手动测试（验证一切正常）

```bash
# 先手动触发一次生成
docker compose run --rm cet6-daily-generator bash /app/run_daily.sh

# 再手动触发一次发送（不等到 07:30）
docker compose run --rm cet6-qq-pusher python /app/qq_daily_sender.py --mode once
```

如果你的 QQ 收到了 PDF，说明部署成功！以后每天会全自动运行。

## 目录共享为什么这样设计

推送服务容器和 NapCat 容器不是同一个文件系统。

如果不做共享挂载，推送服务虽然能找到 `/app/articles/...pdf`，但 NapCat 在它自己的容器里看不到这个路径，`upload_private_file` 会失败。

所以 compose 里做了同一宿主机目录的双挂载：

- 推送服务看到的是 `/app/articles`
- NapCat 看到的是 `/data/shared/articles`

脚本会自动把本地路径转换成 NapCat 容器内路径再调用 API。

## 常用命令

查看日志：

```bash
docker compose logs -f cet6-qq-pusher
docker compose logs -f cet6-napcat
```

重新发送一次当天内容：

```bash
docker compose run --rm cet6-qq-pusher python /app/qq_daily_sender.py --mode once --force
```

发送指定日期目录：

```bash
docker compose run --rm cet6-qq-pusher python /app/qq_daily_sender.py --mode once --date-label 04-23
```

## 安全建议

1. 不要把 NapCat 的 OneBot HTTP 端口直接暴露到公网
2. 一定要配置 `NAPCAT_ACCESS_TOKEN`
3. 一定要修改 `NAPCAT_WEBUI_TOKEN`
4. 如果服务器有防火墙，只开放你需要访问的 `6099`