#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/humble/setup.bash
source /home/qingz/xline_ws3/install/setup.bash

if [[ -f /home/qingz/.config/xline-agent-ws3.env ]]; then
  set -a
  source /home/qingz/.config/xline-agent-ws3.env
  set +a
fi

export XLINE_WS_ROOT="${XLINE_WS_ROOT:-/home/qingz/xline_ws3}"

# Hardware runtime is never allowed to start merely because systemd started
# this unit.  Run the same read-only production preflight used by the App,
# then require an explicit operator/administrator authorization switch.
if ! python3 /home/qingz/xline_app_backend1/startup_preflight.py --profile production; then
  echo "[runtime] production preflight failed; refusing to start hardware nodes" >&2
  exit 1
fi

if [[ "${XLINE_HARDWARE_RUNTIME_ENABLE:-false}" != "1" && \
      "${XLINE_HARDWARE_RUNTIME_ENABLE:-false}" != "true" ]]; then
  echo "[runtime] hardware runtime is disabled by default; set XLINE_HARDWARE_RUNTIME_ENABLE=1 only after authorization" >&2
  exit 0
fi

enable_printer=false
if [[ "${XLINE_ENABLE_PRINTER:-false}" =~ ^(1|true|yes|on)$ ]]; then
  if [[ "${XLINE_PRINTER_AUTHORIZED:-false}" != "1" && \
        "${XLINE_PRINTER_AUTHORIZED:-false}" != "true" ]]; then
    echo "[runtime] printer requested without XLINE_PRINTER_AUTHORIZED=1; refusing to start" >&2
    exit 78
  fi
  enable_printer=true
fi

cd /home/qingz/xline_ws3

if [[ "${XLINE_USE_TOTAL_STATION:-false}" =~ ^(1|true|yes|on)$ ]]; then
  exec ros2 launch xline_bringup system_test.launch.py \
    enable_hardware:=true enable_foxglove:=false
fi

pids=()
shutdown_runtime() {
  trap - EXIT INT TERM
  if (( ${#pids[@]} )); then
    kill -TERM "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
  fi
}
trap shutdown_runtime EXIT INT TERM

ros2 launch trajectory_painter shape_painting_system.launch.py \
  enable_printer:="${enable_printer}" &
pids+=("$!")
ros2 run xline_path_planner planner_node &
pids+=("$!")
ros2 run xline_base_controller base_controller_node &
pids+=("$!")

wait -n "${pids[@]}"
