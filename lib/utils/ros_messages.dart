class RosMessages {
  const RosMessages._();

  static Map<String, Object?> subscribe(String topic) {
    return {'op': 'subscribe', 'topic': topic};
  }

  static Map<String, Object?> cmdVel(double linear, double angular) {
    return {
      'op': 'publish',
      'topic': '/cmd_vel',
      'type': 'geometry_msgs/msg/Twist',
      'msg': {
        'linear': {'x': linear, 'y': 0.0, 'z': 0.0},
        'angular': {'x': 0.0, 'y': 0.0, 'z': angular},
      },
    };
  }

  static Map<String, Object?> printerCommand(String action) {
    return {
      'op': 'call_service',
      'service': '/printer/quick_command',
      'type': 'xline_msgs/srv/QuickCommand',
      'args': {'printer_name': 'center', 'action': action, 'param': 0},
    };
  }

  static Map<String, Object?> lnCommand(int commandType) {
    return {
      'op': 'call_service',
      'service': '/ln_driver/command_srv',
      'type': 'xline_msgs/srv/LnCommand',
      'args': {'command_type': commandType},
    };
  }

  static Map<String, Object?> missionControl(bool running) {
    return {
      'op': 'publish',
      'topic': '/xline/mission_control',
      'type': 'std_msgs/msg/String',
      'msg': {'data': running ? 'start_line_task' : 'stop_line_task'},
    };
  }
}
