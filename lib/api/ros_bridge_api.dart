/// ROS2 Bridge 的通信约定集中配置。
///
/// 如果小车后端更换了端口、Topic 或 Service 名称，
/// 应优先在这里修改，避免在多个页面中写死字符串。
class RosBridgeApi {
  const RosBridgeApi._();

  static const protocolName = 'JSON ROS Bridge'; // App 和后端之间的消息协议名称。
  static const defaultPort = 8000;
  static const commandVelocityTopic = '/tablet_cmd_vel';
  static const missionAction = '/execute_plan';
  static const printerService = '/printer/quick_command';
  static const lnDriverService = '/ln_driver/command_srv';
}
