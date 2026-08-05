# Monorepo context: docker build -f hmi/deploy/Dockerfile .
# Pin digest so rebuilds reuse apt/ffmpeg layers when Debian CDN is flaky.
FROM m.daocloud.io/docker.io/library/python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY piplinesdk /app/piplinesdk
COPY hmi/backend/requirements.txt /tmp/hmi-requirements.txt
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r /app/piplinesdk/requirements.txt \
    -r /tmp/hmi-requirements.txt \
    && pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --no-deps -e /app/piplinesdk

COPY shared /app/shared
# Bust only app COPY layers when tag changes (avoids re-running apt/pip).
ARG APP_REVISION=dev
COPY hmi/backend /app/hmi/backend
COPY hmi/scripts /app/hmi/scripts
COPY hmi/frontend/dist /app/hmi/frontend/dist
RUN echo "app_revision=${APP_REVISION}" > /app/.build_revision

ENV FRONTEND_DIST=/app/hmi/frontend/dist
ENV PORT=8000
ENV PYTHONPATH=/app/piplinesdk:/app/hmi/backend:/app/shared

WORKDIR /app/hmi/backend

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "hmi.main:app", "--host", "0.0.0.0", "--port", "8000"]
