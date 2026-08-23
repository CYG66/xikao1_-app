/// App 的全局默认参数。
///
/// 常用修改点：默认小车 IP、端口、ROS Domain 和设备名称。
/// 这些只是新安装 App 时的初始值，用户在设备页可以再次修改。
class AppConstants {
  const AppConstants._();

  static const appTitle = 'X-LINE2';
  static const roverTitle = 'XLine 划线小车';
  static const defaultPort = 8000;
  static const defaultDomainId = 0;
  static const defaultBridgeType = 'FastAPI Backend';
  static const maxLinearVelocity = 0.20;
  static const maxAngularVelocity = 0.40;

  /// Temporary UI-only preview for Android layout work.
  /// Use `--dart-define=XLINE_LAYOUT_PREVIEW=false` for a real vehicle build.
  static const layoutPreviewMode = bool.fromEnvironment(
    'XLINE_LAYOUT_PREVIEW',
    defaultValue: true,
  );

  /// WebSocket 连接成功后 App 会自动订阅的 ROS2 话题。
  static const coreTopics = [
    '/imu',
    '/robot_pose',
    '/reflector_position',
    '/printer_status',
  ];
}
