FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    APP_ENV=production HOST=0.0.0.0 PORT=8000 RELOAD=false \
    SEED_DEMO=false COOKIE_SECURE=true ENABLE_DOCS=false \
    DB_TYPE=sqlite SQLITE_PATH=/data/taphoa360.db \
    TZ=Asia/Ho_Chi_Minh CONTAINER_RUNTIME=true
WORKDIR /app
RUN groupadd --gid 10001 taphoa && useradd --uid 10001 --gid 10001 --no-create-home taphoa \
    && mkdir /data && chown 10001:10001 /data
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY app.py config.py db.py serve.py ./
COPY retail ./retail
COPY static ./static
COPY templates ./templates
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/health/ready',timeout=4)"
CMD ["python", "serve.py"]
