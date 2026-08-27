# XLine Rover Backend

这是划线小车 App 的 FastAPI + rclpy 后端。

## 功能

- HTTP 接口：状态查询、平板底盘控制、喷码机控制、LN150 控制、规划与 Action 任务执行
- WebSocket：向 App 推送实时状态
- ROS2 接入：有 `rclpy` 时连接真实小车；开发机没有 ROS2 时仅提供不可控的离线状态

## Ubuntu 小车端启动

```bash
cd ~/xline_ws3
source /opt/ros/humble/setup.bash
source install/setup.bash
export XLINE_WS_ROOT=/home/qingz/xline_ws3

cd /path/to/test1/backend
python3 -m pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

部署到小车后由两个 systemd 服务分别管理 ROS2 运行层和 FastAPI：

```bash
sudo systemctl enable --now xline-ws3-runtime.service
sudo systemctl enable --now xline-app-backend1.service
```

当前部署只运行 ws3。`xline-ws3-runtime.service` 常驻管理底盘、定位、规划和喷码节点，
`xline-app-backend1.service` 通过 `Wants/After` 启动并等待运行层进程。运行层异常会自动重启，
FastAPI 保持在线并报告未就绪；重启 FastAPI 不会再结束 ROS2 硬件节点。

```bash
systemctl is-active xline-ws3-runtime.service xline-app-backend1.service
curl --fail http://127.0.0.1:8000/health
```

旧 cyg 服务保持禁用，`xline-backend-switch` 不再安装或使用。

后端仅在 SocketCAN `can0`（或显式配置的旧 USB2CAN）和
`differential_wheels_driver` 节点都就绪时开放非零速度控制。
手动速度发布到 `/tablet_cmd_vel`，由 `cmd_vel_mux` 输出最终 `/cmd_vel`。任务启动时先调用
`/plan_path`，再读取 `other/planned_results/planned_*.json` 并逐段调用 `/execute_plan`；取消或失败会停车。
最终底盘驱动和速度仲裁器不再设置固定线速度/角速度裁剪，轮驱协议边界为每轮 `500 RPM`，
指令断流 `0.5 s` 停车。App 的手动线速度默认值为 `0.10 m/s`、允许上限为 `1.00 m/s`，
角速度上限为 `0.40 rad/s`；
路径跟踪与施工任务按 `xline_ws3` 使用 `0.10 m/s` 上限。方向遵循 REP-103：正线速度前进、
正角速度左转，后端不再叠加电机极性反向。

`XLINE_USE_TOTAL_STATION=true` 时使用 `system_test.launch.py enable_hardware:=true`。
默认无全站仪模式使用 `trajectory_painter` 的常驻底层 launch，并额外常驻启动规划器和
`base_controller_node`；不会为每个 App 任务反复启动 `shape_painter` 进程。

`XLINE_WS_ROOT` 必须指向 `xline_ws3` 工作区；规划器用它解析 `cad`、可视化和
`other/planned_results` 等相对路径。后端只读取该 ROS2 工作区，不会修改其中源码或安装文件。

## 智能助手配置

API Key 只保存在小车端，不要写入 Flutter 源码或 APK：

```bash
mkdir -p ~/.config
cp ~/xline_app_backend1/xline-agent.env.example ~/.config/xline-agent-ws3.env
chmod 600 ~/.config/xline-agent-ws3.env
nano ~/.config/xline-agent-ws3.env
```

修改配置后重启后端。智能助手会显示每次请求的输入、输出和总 Token；移动、任务、LN150 与喷码操作必须在 App 内二次确认。
默认提供商为 DeepSeek，环境文件使用 `DEEPSEEK_API_KEY` 和 `DEEPSEEK_MODEL`；切换提供商时使用对应的
`<PROVIDER>_API_KEY`、`<PROVIDER>_MODEL`，也可以在 App 设置页保存配置。

此版本只支持 `printer_center`。API 和 Agent 不会把 `left`、`right` 或 `all`
作为真实喷头提供。`enabled` 表示允许发送喷码命令，`auto_connect` 表示是否自动连接，
两者不能混为同一个开关。
`printer_ready` 还要求 `/printer_status` 在 5 秒内更新。测试喷墨和基础模式持续喷墨在发送
`simulate` 后最多重试 3 次，只有 `device_state == 1` 且 `print_count` 增长才判定真实触发成功。
部分固件不提供打印计数时，按 ws3 实机记录间隔 `0.3 s` 发送两次软件触发，并显示“已触发·待确认”，
不能把命令提交成功标成已确认出墨；停止、断连或取消会阻止尚未发送的后续触发。

用户在基础模式主动开启喷墨后，正常 AI 运动完成只发布零速度并清理运动状态，不改变喷墨开关，
因此可以连续提交多次运动。急停、控制租约超时、App 断连、运动执行异常或用户明确停止仍使用
fail-safe，同时停车并发送 `stop_print`。

当前 `xline_ws3` 已提供 CAD 规划 `/plan_path` 和执行 `/execute_plan`，因此进阶模式走版本化 JSON 图纸的
规划执行链。文档中预留的直接 `shape_painter` Action 尚未实现，后端不会伪装或反复拉起该接口。

App 连接地址示例：

```text
http://小车IP:8000
ws://小车IP:8000/ws/status
ws://小车IP:8000
```

如果使用当前 Flutter App 的 ROS Bridge 配置页，可以把 IP 填小车 IP，端口填 `8000`。后端根路径 WebSocket 已兼容 App 发送的 ROS Bridge 风格 JSON。

## 主要接口

- `GET /health`
- `GET /api/status`
- `POST /api/cmd_vel`
- `POST /api/printer/quick_command`
- `POST /api/printer/set_active`
- `POST /api/ln150/command`
- `POST /api/mission/control`
- `GET /api/logs`
- `WebSocket /ws/status`
- `WebSocket /` 或 `/ws/rosbridge`
