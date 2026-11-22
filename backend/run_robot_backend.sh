#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/humble/setup.bash
source /home/qingz/xline_ws3/install/setup.bash

if [[ -f /home/qingz/.config/xline-agent-ws3.env ]]; then
  set -a
  source /home/qingz/.config/xline-agent-ws3.env
  set +a
fi

# xline_ws3 resolves CAD, visualization and planned-result paths from this root.
export XLINE_WS_ROOT="${XLINE_WS_ROOT:-/home/qingz/xline_ws3}"

cd /home/qingz/xline_app_backend1

# Read-only fail-closed admission.  Nothing below this line may import an
# application persistence module until the explicit production paths pass.
python3 startup_preflight.py --profile production
export XLINE_STARTUP_PREFLIGHT_OK=1

exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
