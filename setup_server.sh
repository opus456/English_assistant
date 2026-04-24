#!/bin/bash
# 服务器一键部署脚本
# 用法：bash setup_server.sh
# 需要：Python 3.11+，git

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo " CET6 Daily Flow - 服务器部署"
echo "========================================"

# 1. 安装系统依赖（Debian/Ubuntu）
echo "[1/5] 安装系统依赖..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    fonts-noto-cjk \
    chromium-browser \
    libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2

# 2. 创建虚拟环境
uv venv "$SCRIPT_DIR/.venv"
source "$SCRIPT_DIR/.venv/bin/activate"

# 3.安装python依赖
uv pip install -r "$SCRIPT_DIR/requirements.txt"
python -m playwright install chromium

# 4. 创建必要目录和配置文件
echo "[4/5] 初始化目录..."
mkdir -p "$SCRIPT_DIR/articles" "$SCRIPT_DIR/logs" "$SCRIPT_DIR/runtime"

if [ ! -f "$SCRIPT_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo ""
    echo "⚠️  已创建 .env 文件，请编辑填写你的配置："
    echo "   nano $SCRIPT_DIR/.env"
    echo ""
fi

chmod +x "$SCRIPT_DIR/run_daily.sh"

# 5. 配置 cron 定时任务（每天 06:30 执行）
echo "[5/5] 配置 cron 定时任务..."
CRON_JOB="30 6 * * * /bin/bash $SCRIPT_DIR/run_daily.sh >> $SCRIPT_DIR/logs/daily.log 2>&1"

# 检查是否已经存在相同的 cron 任务
if crontab -l 2>/dev/null | grep -qF "run_daily.sh"; then
    echo "   cron 任务已存在，跳过"
else
    # 追加 cron 任务
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "   已添加 cron 任务：每天 06:30 运行"
fi

echo ""
echo "========================================"
echo " 部署完成！"
echo "========================================"
echo ""
echo "下一步操作："
echo "  1. 编辑配置文件：nano $SCRIPT_DIR/.env"
echo "     - 填写 QQ_TARGET_ID（你的QQ号）"
echo "     - 填写 DEEPSEEK_API_KEY"
echo "     - 填写 NAPCAT_ACCESS_TOKEN"
echo ""
echo "  2. 手动测试运行一次："
echo "     bash $SCRIPT_DIR/run_daily.sh"
echo ""
echo "  3. 查看定时任务："
echo "     crontab -l"
echo ""
echo "  4. 查看运行日志："
echo "     tail -f $SCRIPT_DIR/logs/daily.log"
