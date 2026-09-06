# XLine Rover Backend

这是划线小车 App 的 FastAPI + rclpy 后端。

## 功能

- HTTP 接口：状态查询、底盘控制、喷码机控制、LN150 控制、任务启停
- WebSocket：向 App 推送实时状态
- ROS2 接入：有 `rclpy` 时连接真实小车；没有 ROS2 时自动进入模拟模式

## Ubuntu 小车端启动

```bash
cd ~/xline_ws
source /opt/ros/humble/setup.bash
source install/setup.bash

cd /path/to/test1/backend
python3 -m pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

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
- `POST /api/ln150/command`
- `POST /api/mission/control`
- `GET /api/logs`
- `WebSocket /ws/status`
- `WebSocket /` 或 `/ws/rosbridge`
