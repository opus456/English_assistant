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

echo "$LOG_PREFIX 开始每日任务，日期：$DATE_LABEL"

echo "$LOG_PREFIX 步骤 1/3：抓取今日文章"
uv run "$SCRIPT_DIR/scrape_articles.py" --output-dir "articles/$DATE_LABEL"

echo "$LOG_PREFIX 步骤 2/3：生成六级材料和 PDF"
uv run "$SCRIPT_DIR/generate_cet6_materials.py" \
    --input-dir "articles/$DATE_LABEL" \
    --output-dir "articles/$DATE_LABEL"

echo "$LOG_PREFIX 步骤 3/3：发送 QQ 消息"
uv run "$SCRIPT_DIR/qq_daily_sender.py" --mode once

echo "$LOG_PREFIX 所有任务完成！"