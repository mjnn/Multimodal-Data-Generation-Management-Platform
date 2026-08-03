#!/usr/bin/env bash
set -euo pipefail
APP=/srv/apps/rosbag-to-labels-hmi
cd "$APP"

mkdir -p data/hmi_runtime data/app_meta
if [ -d data/hmi_local ] && [ ! -f data/hmi_runtime/hmi.db ]; then
  echo "Migrating hmi_local to hmi_runtime..."
  cp -a data/hmi_local/. data/hmi_runtime/
fi
for sub in rosbags clips pipeline config reviews datasets; do
  mkdir -p "data/hmi_runtime/oss/$sub"
done
mkdir -p data/hmi_runtime/work/sdk_runs
touch data/hmi_runtime/.initialized

ENV_FILE=.env.runtime
append_if_missing() {
  key="$1"
  val="$2"
  if ! grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
}
sed -i '1s/^\xEF\xBB\xBF//' "$ENV_FILE" 2>/dev/null || true
append_if_missing HMI_PUBLIC_API_BASE /tools/rosbag-labels/api
append_if_missing HMI_RUNTIME_ROOT /app/data/hmi_runtime
append_if_missing HMI_LOCAL_SDK_POLL_ENABLED 1
append_if_missing HMI_LOCAL_SDK_POLL_INTERVAL_SEC 20
append_if_missing HMI_MIRROR_ARTIFACTS_TO_OSS 0

if grep -q '^IMAGE=' "$ENV_FILE"; then
  sed -i 's|^IMAGE=.*|IMAGE=crpi-02k3y8iudey5q0vb.cn-shanghai.personal.cr.aliyuncs.com/mirror_ns/rosbag_to_labels_pipline_hmi:20260803-2|' "$ENV_FILE"
fi

sed -i 's/\r$//' .env.runtime 2>/dev/null || true
docker-compose --env-file .env.runtime pull
docker-compose --env-file .env.runtime up -d
sleep 10
docker-compose --env-file .env.runtime ps
curl -fsS "http://127.0.0.1:8012/api/health" && echo

# First deploy with empty app_meta volume has no users — bootstrap default admin if needed
docker exec "${SERVICE_NAME:-rosbag-to-labels-hmi}" python /app/hmi/scripts/bootstrap_admin.py \
  --username admin --password admin123 2>/dev/null || true
