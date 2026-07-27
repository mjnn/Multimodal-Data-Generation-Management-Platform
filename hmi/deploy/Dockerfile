# Rosbag HMI — 单容器：FastAPI + 预构建 SPA
FROM m.daocloud.io/docker.io/library/python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r /app/backend/requirements.txt

COPY backend /app/backend
COPY config /app/config
COPY config.yaml /app/config.yaml
COPY clip_id.py cloud_config.py /app/
COPY scripts/sync_hmi_local.py /app/scripts/sync_hmi_local.py
COPY scripts/seed_demo_clip_data.py scripts/import_real_data_clips.py scripts/mock_pipeline_artifacts.py scripts/mock_pipeline_run.py /app/scripts/
COPY dataworks/label_merge.py /app/dataworks/label_merge.py
COPY frontend/dist /app/frontend/dist

ENV FRONTEND_DIST=/app/frontend/dist
ENV PORT=8000
ENV PYTHONPATH=/app/backend:/app

WORKDIR /app/backend

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "hmi.main:app", "--host", "0.0.0.0", "--port", "8000"]
