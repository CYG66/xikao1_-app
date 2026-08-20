# XLine Rover Backend

这是划线小车 App 的 FastAPI + rclpy 后端。

## 功能

- HTTP 接口：状态查询、平板底盘控制、喷码机控制、LN150 控制、规划与 Action 任务执行
- WebSocket：向 App 推送实时状态
- ROS2 接入：有 `rclpy` 时连接真实小车；开发机没有 ROS2 时仅提供不可控的离线状态

## Ubuntu 小车端启动

```bash
cd ~/xline_cyg
source /opt/ros/humble/setup.bash
source install_ws3/setup.bash

cd /path/to/test1/backend
python3 -m pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

部署到小车后也可以直接运行：

```bash
~/xline_app_backend/run_robot_backend.sh
```

后端仅在 HDSC USB2CAN 设备和 `differential_wheels_driver` 节点都存在时开放非零速度控制。
手动速度发布到 `/tablet_cmd_vel`，由 `cmd_vel_mux` 输出最终 `/cmd_vel`。任务启动时先调用
`/plan_path`，再读取 `other/planned_results/planned_*.json` 并逐段调用 `/execute_plan`；取消或失败会停车。

## 智能助手配置

API Key 只保存在小车端，不要写入 Flutter 源码或 APK：

```bash
mkdir -p ~/.config
cp ~/xline_app_backend/xline-agent.env.example ~/.config/xline-agent.env
chmod 600 ~/.config/xline-agent.env
nano ~/.config/xline-agent.env
```

修改配置后重启后端。智能助手会显示每次请求的输入、输出和总 Token；移动、任务、LN150 与喷码操作必须在 App 内二次确认。

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
