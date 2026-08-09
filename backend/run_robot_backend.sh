#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/humble/setup.bash
source /home/qingz/xline_ws2/install/setup.bash

if [[ -f /home/qingz/.config/xline-agent.env ]]; then
  set -a
  source /home/qingz/.config/xline-agent.env
  set +a
fi

cd /home/qingz/xline_app_backend
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
