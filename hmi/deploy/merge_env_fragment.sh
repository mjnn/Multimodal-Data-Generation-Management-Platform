#!/usr/bin/env bash
set -euo pipefail
APP=/srv/apps/rosbag-to-labels-hmi
FRAG="${1:-/tmp/hmi_ecs_sdk.env}"
cd "$APP"
sed -i 's/\r$//' "$FRAG"
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "$line" || "$line" =~ ^# ]] && continue
  key="${line%%=*}"
  sed -i "/^${key}=/d" .env.runtime
  printf '%s\n' "$line" >> .env.runtime
done < "$FRAG"
sed -i 's/\r$//' .env.runtime
rm -f "$FRAG"
