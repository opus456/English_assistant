#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -o allexport
    source "$SCRIPT_DIR/.env"
    set +o allexport
fi

LOG_PREFIX="[run_daily $(date '+%Y-%m-%d %H:%M:%S')]"
DATE_LABEL=$(date '+%m-%d')
SCRAPER_REGION=${SCRAPER_REGION:-}
SCRAPER_SCRIPT="$SCRIPT_DIR/scrape_articles.py"

if [ -z "$SCRAPER_REGION" ]; then
    if [ -t 0 ]; then
        echo "请选择爬取环境："
        echo "1) 国内"
        echo "2) 国外"
        read -r -p "请输入 1 或 2 [默认 1]: " REGION_CHOICE
        case "$REGION_CHOICE" in
            2)
                SCRAPER_REGION="国外"
                ;;
            *)
                SCRAPER_REGION="国内"
                ;;
        esac
    else
        SCRAPER_REGION="国内"
        echo "$LOG_PREFIX 未检测到交互终端，默认使用国内爬虫源"
    fi
fi

if [ "$SCRAPER_REGION" = "国外" ]; then
    SCRAPER_SCRIPT="$SCRIPT_DIR/scrape_articles_cn.py"
fi

SENDER_RUNTIME=${CET6_BOT_SENDER_RUNTIME:-}

if [ -z "$SENDER_RUNTIME" ]; then
    if [ -t 0 ]; then
        echo "请选择发送环境："
        echo "1) 本地"
        echo "2) Docker"
        read -r -p "请输入 1 或 2 [默认 1]: " SENDER_CHOICE
        case "$SENDER_CHOICE" in
            2)
                SENDER_RUNTIME="docker"
                ;;
            *)
                SENDER_RUNTIME="local"
                ;;
        esac
    else
        SENDER_RUNTIME="docker"
        echo "$LOG_PREFIX 未检测到交互终端，默认使用 Docker 发送模式"
    fi
fi

echo "$LOG_PREFIX 开始每日任务，日期：$DATE_LABEL"
echo "$LOG_PREFIX 当前爬取环境：$SCRAPER_REGION"
echo "$LOG_PREFIX 当前发送环境：$SENDER_RUNTIME"

echo "$LOG_PREFIX 步骤 1/3：抓取今日文章"
uv run "$SCRAPER_SCRIPT" --output-dir "articles/$DATE_LABEL"

echo "$LOG_PREFIX 步骤 2/3：生成六级材料和 PDF"
uv run "$SCRIPT_DIR/generate_cet6_materials.py" \
    --input-dir "articles/$DATE_LABEL" \
    --output-dir "articles/$DATE_LABEL"

echo "$LOG_PREFIX 步骤 3/3：发送 QQ 消息"
uv run "$SCRIPT_DIR/qq_daily_sender.py" --mode once --sender-runtime "$SENDER_RUNTIME"

echo "$LOG_PREFIX 所有任务完成！"