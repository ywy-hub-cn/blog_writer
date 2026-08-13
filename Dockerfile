# Blog-Writer AI Workflow System - Dockerfile
# 多阶段构建；生产默认单 worker（任务/Token 目前为进程内状态）

FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 应用代码（含 nodes / registry / references）
COPY blog_writer/ ./blog_writer/
COPY tools/ ./tools/
COPY brands/ ./brands/

# 运行时数据目录；config.json 通过 docker-compose volume 挂载，不内置
RUN mkdir -p /app/blog_writer/instance /app/brands

ENV BLOG_WRITER_MODE=production
ENV BLOG_WRITER_CONFIG=/app/blog_writer/config.json
ENV PYTHONUNBUFFERED=1

# 单 worker：内存态任务/审核/Webhook 在多 worker 下会分裂
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "blog_writer.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
