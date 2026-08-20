#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/humble/setup.bash
source /home/qingz/xline_cyg/install_ws3/setup.bash

# Keep the generated localization executable runnable without changing src.
localization_src=/home/qingz/xline_cyg/src/xline_bringup/scripts/odom_imu_localization.py
localization_exec=/home/qingz/xline_cyg/install_ws3/xline_bringup/lib/xline_bringup/odom_imu_localization.py
if [[ -f "$localization_src" && ! -x "$localization_exec" ]]; then
  rm -f "$localization_exec"
  install -m 0755 "$localization_src" "$localization_exec"
fi

if [[ -f /home/qingz/.config/xline-agent.env ]]; then
  set -a
  source /home/qingz/.config/xline-agent.env
  set +a
fi

cd /home/qingz/xline_app_backend
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
