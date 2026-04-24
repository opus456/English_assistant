#!/bin/bash
# 每日自动流水线：抓取文章 → 生成 PDF → 发送 QQ 消息
# 用法：bash run_daily.sh
# 建议在 crontab 中调用：0 6 * * * /bin/bash /home/user/english_assistant/run_daily.sh >> /home/user/english_assistant/logs/daily.log 2>&1

set -e

# 脚本所在目录（支持 cron 调用时路径不正确的情况）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 加载 .env 环境变量
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -o allexport
    source "$SCRIPT_DIR/.env"
    set +o allexport
fi

# 激活 Python 虚拟环境
source "$SCRIPT_DIR/venv/bin/activate"

LOG_PREFIX="[run_daily $(date '+%Y-%m-%d %H:%M:%S')]"
DATE_LABEL=$(date '+%m-%d')

echo "$LOG_PREFIX 开始每日任务，日期：$DATE_LABEL"

# 第一步：抓取文章
echo "$LOG_PREFIX 步骤 1/3：抓取今日文章"
python "$SCRIPT_DIR/scrape_articles.py" --output-dir "articles/$DATE_LABEL" || {
    echo "$LOG_PREFIX [ERROR] 抓取失败，退出"
    exit 1
}

# 第二步：生成六级材料和 PDF
echo "$LOG_PREFIX 步骤 2/3：生成六级材料和 PDF"
python "$SCRIPT_DIR/generate_cet6_materials.py" \
    --input-dir "articles/$DATE_LABEL" \
    --output-dir "articles/$DATE_LABEL" || {
    echo "$LOG_PREFIX [ERROR] 生成材料失败，退出"
    exit 1
}

# 第三步：发送 QQ 消息
echo "$LOG_PREFIX 步骤 3/3：发送 QQ 消息"
python "$SCRIPT_DIR/qq_daily_sender.py" --mode once || {
    echo "$LOG_PREFIX [ERROR] QQ 发送失败"
    exit 1
}

echo "$LOG_PREFIX 所有任务完成！"
