/// 构建 App 发给 FastAPI Bridge 的 JSON ROS Bridge 消息。
///
/// 本类不负责网络发送，只负责产生格式正确的 Map。
/// Topic、Service 类型或自定义消息发生变化时，应在这里同步修改。
class RosMessages {
  const RosMessages._();

  /// 订阅一个 ROS2 话题。
  static Map<String, Object?> subscribe(String topic) {
    return {'op': 'subscribe', 'topic': topic};
  }

  static Map<String, Object?> claimControl() => {'op': 'claim_control'};
  static Map<String, Object?> controlHeartbeat() => {'op': 'control_heartbeat'};
  static Map<String, Object?> releaseControl() => {'op': 'release_control'};
  static Map<String, Object?> stopAgentMotion() => {'op': 'stop_agent_motion'};

  /// 构建平板底盘指令；由 cmd_vel_mux 转发到最终 `/cmd_vel`。
  static Map<String, Object?> cmdVel(double linear, double angular) {
    return {
      'op': 'publish',
      'topic': '/tablet_cmd_vel',
      'type': 'geometry_msgs/msg/Twist',
      'msg': {
        'linear': {'x': linear, 'y': 0.0, 'z': 0.0},
        'angular': {'x': 0.0, 'y': 0.0, 'z': angular},
      },
    };
  }

  /// 调用中间喷码机的快捷指令服务。
  static Map<String, Object?> printerCommand(
    String action, {
    String printerName = 'center',
  }) {
    return {
      'op': 'call_service',
      'service': '/printer/quick_command',
      'type': 'xline_msgs/srv/QuickCommand',
      'args': {'printer_name': printerName, 'action': action, 'param': 0},
    };
  }

  static Map<String, Object?> printerActive(
    bool active, {
    String printerName = 'center',
  }) {
    return {
      'op': 'call_service',
      'service': '/printer/set_active',
      'type': 'xline_msgs/srv/SetPrinterActive',
      'args': {'printer_name': printerName, 'active': active},
    };
  }

  static Map<String, Object?> printerEnabled(
    bool enabled, {
    String printerName = 'center',
  }) => {
    'op': 'call_service',
    'service': '/printer/set_enabled',
    'type': 'xline_msgs/srv/SetPrinterEnabled',
    'args': {'printer_name': printerName, 'enabled': enabled},
  };

  static Map<String, Object?> printerRawCommand(
    String jsonData, {
    String printerName = 'center',
  }) => {
    'op': 'call_service',
    'service': '/printer/send_command',
    'type': 'xline_msgs/srv/PrinterCommand',
    'args': {'printer_name': printerName, 'json_data': jsonData},
  };

  /// 调用 LN150 服务，[commandType] 的含义由小车端 `LnCommand` 定义。
  static Map<String, Object?> lnCommand(int commandType) {
    return {
      'op': 'call_service',
      'service': '/ln_driver/command_srv',
      'type': 'xline_msgs/srv/LnCommand',
      'args': {'command_type': commandType},
    };
  }

  static Map<String, Object?> calibrateLocalization() => {
    'op': 'call_service',
    'service': '/localization/calibrate_pose',
    'type': 'std_srvs/srv/Trigger',
    'args': <String, Object?>{},
  };

  /// 启动或停止划线任务。
  static Map<String, Object?> missionControl(
    bool running, {
    String fileName = 'test_pattern.json',
  }) {
    return {'op': 'mission_control', 'running': running, 'file_name': fileName};
  }

  static Map<String, Object?> missionAction(
    String action, {
    String fileName = 'test_pattern.json',
  }) => {'op': 'mission_control', 'action': action, 'file_name': fileName};

  static Map<String, Object?> emergencyStop(bool active) => {
    'op': 'emergency_stop',
    'active': active,
  };
}
