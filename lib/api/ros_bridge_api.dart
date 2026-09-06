class RosBridgeApi {
  const RosBridgeApi._();

  static const protocolName = 'JSON ROS Bridge';
  static const defaultPort = 8000;
  static const commandVelocityTopic = '/cmd_vel';
  static const missionControlTopic = '/xline/mission_control';
  static const printerService = '/printer/quick_command';
  static const lnDriverService = '/ln_driver/command_srv';
}
