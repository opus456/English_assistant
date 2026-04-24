FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

# 安装系统依赖：reportlab 中文字体支持 + playwright 浏览器依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        tzdata \
        fonts-wqy-zenhei \
        fonts-noto-cjk \
        chromium \
        chromium-driver \
        libglib2.0-0 \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && pip install --no-cache-dir playwright reportlab \
    && python -m playwright install chromium --with-deps 2>/dev/null || true

COPY qq_daily_sender.py /app/qq_daily_sender.py
COPY scrape_articles.py /app/scrape_articles.py
COPY generate_cet6_materials.py /app/generate_cet6_materials.py
COPY cet6_generation_prompt.md /app/cet6_generation_prompt.md
COPY run_daily.sh /app/run_daily.sh

RUN mkdir -p /app/articles /app/runtime \
    && useradd --system --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app \
    && chmod +x /app/run_daily.sh

USER appuser

CMD ["python", "/app/qq_daily_sender.py", "--mode", "scheduler"]