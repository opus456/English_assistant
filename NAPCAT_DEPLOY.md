# NapCat QQ 机器人部署说明

本项目新增了一个独立的 QQ 推送服务，它会读取 `articles/<MM-DD>` 目录下最新的一对 PDF，然后通过 NapCat 暴露的 OneBot HTTP API 发送给指定 QQ。

## 文件说明

- `qq_daily_sender.py`：定时推送脚本
- `Dockerfile`：推送服务镜像
- `docker-compose.yml`：同时启动 NapCat 和推送服务
- `.env.example`：环境变量模板

## 部署前提

1. 服务器已安装 Docker 和 Docker Compose
2. 服务器目录中已经存在你每天生成的 PDF 文件，路径格式如下：

```text
articles/04-23/04-23-xxx-test.pdf
articles/04-23/04-23-xxx-answer.pdf
```

## 第一步：准备环境变量

复制环境变量模板：

```bash
cp .env.example .env
```

至少要改这几项：

- `QQ_TARGET_TYPE=private`
- `QQ_TARGET_ID=你的QQ号`
- `NAPCAT_ACCESS_TOKEN=你准备给 OneBot HTTP 服务配置的 token`
- `NAPCAT_WEBUI_TOKEN=NapCat WebUI 登录口令`
- `CET6_BOT_SEND_TIME=07:30`

## 第二步：启动容器

```bash
docker compose up -d --build
```

启动后会有两个容器：

- `cet6-napcat`
- `cet6-qq-pusher`

## 第三步：登录 NapCat

打开：

```text
http://你的服务器IP:6099/webui
```

使用 `.env` 里的 `NAPCAT_WEBUI_TOKEN` 登录。

然后在 WebUI 中完成：

1. 进入 QQ 登录页面
2. 使用二维码登录你的 QQ
3. 进入 OneBot 网络配置
4. 新建一个 HTTP Server
5. 配置以下参数：

```text
host: 0.0.0.0
port: 3000
token: 与 .env 中的 NAPCAT_ACCESS_TOKEN 保持一致
enable: true
```

保存并启用。

## 第四步：手动测试一次发送

先确保 `articles/<今天日期>` 下已经有 PDF，再执行：

```bash
docker compose run --rm cet6-qq-pusher python /app/qq_daily_sender.py --mode once
```

如果你只想看它会发什么，不真的调用 NapCat：

```bash
docker compose run --rm cet6-qq-pusher python /app/qq_daily_sender.py --mode once --dry-run
```

## 第五步：定时自动发送

默认 `docker-compose.yml` 已经让推送服务用 `scheduler` 模式运行。它会：

1. 按 `CET6_BOT_SEND_TIME` 轮询
2. 找到当天目录下最新的一对 PDF
3. 先发文字摘要
4. 再发试卷 PDF 和解析 PDF
5. 记录当天已发送状态，避免同一天重复发

状态文件默认在：

```text
runtime/qq-push-state.json
```

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