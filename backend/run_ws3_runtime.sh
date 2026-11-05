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
cd /home/qingz/xline_ws3

if [[ "${XLINE_USE_TOTAL_STATION:-false}" =~ ^(1|true|yes|on)$ ]]; then
  exec ros2 launch xline_bringup system_test.launch.py \
    enable_hardware:=true enable_foxglove:=false
fi

enable_printer=false
if [[ "${XLINE_ENABLE_PRINTER:-true}" =~ ^(1|true|yes|on)$ ]]; then
  enable_printer=true
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
