#!/usr/bin/env bash
set -eo pipefail

if [[ -f /home/qingz/.config/xline-agent-ws3.env ]]; then
  set -a
  source /home/qingz/.config/xline-agent-ws3.env
  set +a
fi

cd /home/qingz/xline_app_backend1
exec python3 -m app.discovery
