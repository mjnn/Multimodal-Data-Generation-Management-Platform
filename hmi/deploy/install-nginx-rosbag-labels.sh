#!/usr/bin/env bash
set -euo pipefail

SNIPPET_SRC="${1:-deploy/nginx-rosbag-labels-locations.conf}"
SNIPPET_DST="/etc/nginx/snippets/rosbag-labels-locations.conf"
DEFAULT_SITE="/etc/nginx/sites-enabled/default"
INCLUDE_LINE="include /etc/nginx/snippets/rosbag-labels-locations.conf;"

if [[ ! -f "$SNIPPET_SRC" ]]; then
  echo "missing snippet: $SNIPPET_SRC" >&2
  exit 1
fi

cp "$SNIPPET_SRC" "$SNIPPET_DST"
echo "installed $SNIPPET_DST"

if grep -qF "$INCLUDE_LINE" "$DEFAULT_SITE"; then
  echo "include already present in $DEFAULT_SITE"
else
  sed -i "/ecs-service-manage-generated-locations.conf/i\\    $INCLUDE_LINE" "$DEFAULT_SITE"
  echo "added include to $DEFAULT_SITE"
fi

nginx -t
systemctl reload nginx
echo "nginx reloaded"
