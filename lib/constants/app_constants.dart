class AppConstants {
  const AppConstants._();

  static const appTitle = 'XLine Rover';
  static const roverTitle = 'XLine 划线小车';
  static const defaultDeviceName = 'XLine-Car-01';
  static const defaultIp = '192.168.0.100';
  static const defaultPort = 8000;
  static const defaultDomainId = 0;
  static const defaultBridgeType = 'FastAPI Backend';

  static const coreTopics = [
    '/imu',
    '/robot_pose',
    '/reflector_position',
    '/printer_status',
  ];
}
