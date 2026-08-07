import 'package:flutter/material.dart';

/// 一台可连接的 XLine 小车配置。
///
/// 页面添加设备后会创建该对象，[bridgeUrl] 根据 IP 和端口
/// 自动生成 WebSocket 地址。
class RoverDevice {
  const RoverDevice({
    required this.name,
    required this.ip,
    required this.port,
    required this.domainId,
    required this.type,
    required this.connected,
  });

  final String name;
  final String ip;
  final int port;
  final int domainId;
  final String type;
  final bool connected;

  String get bridgeUrl => 'ws://$ip:$port';
}

/// App 到 FastAPI/ROS2 Bridge 的连接状态机。
enum BridgeState { disconnected, connecting, connected, failed }

/// 将连接状态转成界面可直接使用的文字和颜色。
extension BridgeStateLabel on BridgeState {
  String get label {
    switch (this) {
      case BridgeState.connecting:
        return '连接中';
      case BridgeState.connected:
        return '已连接';
      case BridgeState.failed:
        return '连接失败';
      case BridgeState.disconnected:
        return '未连接';
    }
  }

  Color get color {
    switch (this) {
      case BridgeState.connected:
        return const Color(0xff22c55e);
      case BridgeState.connecting:
        return const Color(0xfff59e0b);
      case BridgeState.failed:
        return const Color(0xffef4444);
      case BridgeState.disconnected:
        return const Color(0xff64748b);
    }
  }
}
