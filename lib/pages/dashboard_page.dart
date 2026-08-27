part of '../main.dart';

/// 首页概览：快捷入口、连接区、实时状态和当前任务。
/// 离线时隐藏所有遥测值，只显示连接引导。
class _DashboardPage extends StatelessWidget {
  const _DashboardPage({
    required this.device,
    required this.lineRunning,
    required this.bridgeState,
    required this.rosAvailable,
    required this.backendOnline,
    required this.controlGranted,
    required this.controlOwner,
    required this.controlReady,
    required this.driveDeviceConnected,
    required this.motorDriverReady,
    required this.driveTransport,
    required this.driveDevicePath,
    required this.linearVelocity,
    required this.localizationAccuracyMm,
    required this.telemetryAgeMs,
    required this.robotPose,
    required this.gridMap,
    required this.plannedPaths,
    required this.poseTrace,
    required this.obstacleDistances,
    required this.obstacleAgeMs,
    required this.wheelSpeeds,
    required this.motorStatus,
    required this.battery,
    required this.localizationReady,
    required this.localizationSource,
    required this.localizationCalibration,
    required this.localizationCalibrationAvailable,
    required this.ln150Ready,
    required this.onLnCommand,
    required this.onCalibrateLocalization,
    required this.printerStatus,
    required this.printerStatusData,
    required this.onPrinterChanged,
    required this.onPrinterEnabledChanged,
    required this.onPrinterCommand,
    required this.onPrinterRawCommand,
    required this.missionReady,
    required this.onStartMission,
    required this.onAddDevice,
    required this.onConnect,
    required this.onOpenMap,
    required this.onOpenControl,
    required this.onOpenDevices,
  });

  final RoverDevice device;
  final bool lineRunning;
  final BridgeState bridgeState;
  final bool rosAvailable;
  final bool backendOnline;
  final bool controlGranted;
  final String? controlOwner;
  final bool controlReady;
  final bool driveDeviceConnected;
  final bool motorDriverReady;
  final String driveTransport;
  final String driveDevicePath;
  final double? linearVelocity;
  final double? localizationAccuracyMm;
  final int? telemetryAgeMs;
  final Map<String, dynamic> robotPose;
  final Map<String, dynamic> gridMap;
  final List<Map<String, dynamic>> plannedPaths;
  final List<List<double>> poseTrace;
  final Map<String, dynamic> obstacleDistances;
  final int? obstacleAgeMs;
  final Map<String, dynamic> wheelSpeeds;
  final Map<String, dynamic> motorStatus;
  final int? battery;
  final bool localizationReady;
  final String localizationSource;
  final String localizationCalibration;
  final bool localizationCalibrationAvailable;
  final bool ln150Ready;
  final ValueChanged<int> onLnCommand;
  final VoidCallback onCalibrateLocalization;
  final String printerStatus;
  final Map<String, dynamic> printerStatusData;
  final void Function(String printerName, bool active) onPrinterChanged;
  final void Function(String printerName, bool enabled) onPrinterEnabledChanged;
  final void Function(String printerName, String action) onPrinterCommand;
  final void Function(String printerName, String jsonData) onPrinterRawCommand;
  final bool missionReady;
  final VoidCallback onStartMission;
  final VoidCallback onAddDevice;
  final VoidCallback onConnect;
  final VoidCallback onOpenMap;
  final VoidCallback onOpenControl;
  final VoidCallback onOpenDevices;

  @override
  Widget build(BuildContext context) {
    if (bridgeState != BridgeState.connected) {
      return ListView(
        key: const ValueKey('dashboard'),
        padding: const EdgeInsets.all(16),
        children: [
          _OfflinePanel(
            connecting: bridgeState == BridgeState.connecting,
            onConnect: onConnect,
            onManageDevices: onOpenDevices,
          ),
        ],
      );
    }

    final shortcuts = Row(
      children: [
        Expanded(
          child: _HomeShortcut(
            icon: Icons.map_rounded,
            label: '地图',
            onTap: onOpenMap,
            enabled: localizationReady,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _HomeShortcut(
            icon: Icons.gamepad_rounded,
            label: '控制',
            onTap: onOpenControl,
            enabled: controlReady,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _HomeShortcut(
            icon: Icons.devices_other_rounded,
            label: '设备',
            onTap: onOpenDevices,
          ),
        ),
      ],
    );

    Widget map({double? height}) => _Panel(
      title: '实时地图',
      trailing: IconButton(
        tooltip: '打开完整地图',
        onPressed: onOpenMap,
        icon: const Icon(Icons.open_in_full_rounded, size: 20),
      ),
      child: _RealtimeRobotView(
        rosAvailable: rosAvailable,
        pose: robotPose,
        gridMap: gridMap,
        plannedPaths: plannedPaths,
        poseTrace: poseTrace,
        lineRunning: lineRunning,
        onTap: onOpenMap,
        height: height,
      ),
    );
    final printer = _PrinterControlPanel(
      enabled: printerStatus == 'Ready' || printerStatus == 'ready',
      status: printerStatusData,
      onPrinterChanged: onPrinterChanged,
      onPrinterEnabledChanged: onPrinterEnabledChanged,
      onPrinterCommand: onPrinterCommand,
      onPrinterRawCommand: onPrinterRawCommand,
    );
    final localization = _HomeLocalizationPanel(
      controlReady: controlReady,
      localizationSource: localizationSource,
      localizationCalibration: localizationCalibration,
      localizationCalibrationAvailable: localizationCalibrationAvailable,
      ln150Ready: ln150Ready,
      onLnCommand: onLnCommand,
      onCalibrateLocalization: onCalibrateLocalization,
    );
    final diagnostics = Column(
      children: [
        _RobotTelemetryPanel(
          obstacles: obstacleDistances,
          obstacleAgeMs: obstacleAgeMs,
          wheelSpeeds: wheelSpeeds,
          motorStatus: motorStatus,
          battery: battery,
        ),
        const SizedBox(height: 12),
        _CollapsiblePanel(
          title: '连接链路',
          statusText: backendOnline && rosAvailable && controlReady
              ? '全部正常'
              : '需要检查',
          statusColor: backendOnline && rosAvailable && controlReady
              ? const Color(0xff16a66a)
              : const Color(0xfff59e0b),
          child: Column(
            children: [
              _ConnectionLayerRow(
                label: 'App 后端',
                detail: 'WebSocket / FastAPI',
                ready: backendOnline,
              ),
              _ConnectionLayerRow(
                label: 'ROS2 系统',
                detail: telemetryAgeMs == null
                    ? '等待定位遥测'
                    : '遥测 ${(telemetryAgeMs! / 1000).toStringAsFixed(1)}s',
                ready:
                    rosAvailable &&
                    telemetryAgeMs != null &&
                    telemetryAgeMs! < 3000,
              ),
              _ConnectionLayerRow(
                label: '小车底盘',
                detail: '$driveTransport 电机驱动',
                ready: controlReady,
              ),
              _ConnectionLayerRow(
                label: '控制权限',
                detail: controlGranted
                    ? '当前 App 已获得'
                    : (controlOwner == null ? '正在申请' : '其他客户端占用'),
                ready: controlGranted,
                last: true,
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        _CollapsiblePanel(
          title: '底盘驱动',
          statusText: controlReady ? '可控制' : '未就绪',
          statusColor: controlReady
              ? const Color(0xff16a66a)
              : const Color(0xfff59e0b),
          child: Column(
            children: [
              _ConfigRow('通信方式', driveTransport.toUpperCase()),
              const _ConfigRow('电机型号', 'M1505'),
              _ConfigRow(
                driveTransport == 'socketcan' ? 'CAN 接口' : 'USB2CAN',
                '$driveDevicePath · ${driveDeviceConnected ? '已启用' : '未启用'}',
              ),
              _ConfigRow('电机节点', motorDriverReady ? '运行中' : '未运行'),
            ],
          ),
        ),
      ],
    );

    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 840;
        if (!wide) {
          return ListView(
            key: const ValueKey('dashboard'),
            padding: const EdgeInsets.all(14),
            children: [
              shortcuts,
              const SizedBox(height: 12),
              localization,
              const SizedBox(height: 12),
              printer,
              const SizedBox(height: 12),
              map(),
              const SizedBox(height: 12),
              diagnostics,
            ],
          );
        }
        return Row(
          key: const ValueKey('dashboard-wide'),
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              flex: 36,
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(16, 16, 8, 16),
                child: Column(
                  children: [
                    shortcuts,
                    const SizedBox(height: 12),
                    localization,
                    const SizedBox(height: 12),
                    printer,
                    const SizedBox(height: 12),
                    diagnostics,
                  ],
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              flex: 62,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(8, 16, 16, 16),
                child: map(
                  height: constraints.hasBoundedHeight
                      ? math.max(260, constraints.maxHeight - 32)
                      : null,
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _HomeLocalizationPanel extends StatelessWidget {
  const _HomeLocalizationPanel({
    required this.controlReady,
    required this.localizationSource,
    required this.localizationCalibration,
    required this.localizationCalibrationAvailable,
    required this.ln150Ready,
    required this.onLnCommand,
    required this.onCalibrateLocalization,
  });

  final bool controlReady;
  final String localizationSource;
  final String localizationCalibration;
  final bool localizationCalibrationAvailable;
  final bool ln150Ready;
  final ValueChanged<int> onLnCommand;
  final VoidCallback onCalibrateLocalization;

  @override
  Widget build(BuildContext context) {
    final relative = localizationSource == 'odom_imu_relative';
    final totalStation = localizationSource == 'ln150_imu';
    return _Panel(
      title: totalStation
          ? '全站仪定位准备'
          : relative
          ? '相对定位准备'
          : '定位准备',
      trailing: _StatusChip(
        text: controlReady ? '已就绪' : '未就绪',
        color: controlReady ? const Color(0xff16a66a) : const Color(0xfff59e0b),
      ),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          if (ln150Ready && totalStation) ...[
            _CommandButton(
              label: 'LN150 初始化',
              icon: Icons.power_settings_new_rounded,
              onPressed: () => onLnCommand(1),
            ),
            _CommandButton(
              label: '自动追踪',
              icon: Icons.gps_fixed_rounded,
              onPressed: () => onLnCommand(2),
            ),
            _CommandButton(
              label: '自动调平',
              icon: Icons.balance_rounded,
              onPressed: () => onLnCommand(3),
            ),
          ],
          _CommandButton(
            label: localizationCalibration == 'calibrating'
                ? relative
                      ? '正在重置原点'
                      : '定位校准中'
                : relative
                ? '重置相对原点'
                : '定位校准',
            icon: Icons.my_location_rounded,
            onPressed:
                localizationCalibrationAvailable &&
                    localizationCalibration != 'calibrating'
                ? onCalibrateLocalization
                : null,
          ),
          if (!localizationCalibrationAvailable)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 10),
              child: Text(
                '当前定位模式未提供校准或原点重置服务',
                style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
              ),
            ),
        ],
      ),
    );
  }
}

/// 离线空状态：解释功能不可用的原因，并提供重连和设备管理入口。
class _OfflinePanel extends StatelessWidget {
  const _OfflinePanel({
    required this.connecting,
    required this.onConnect,
    required this.onManageDevices,
  });

  final bool connecting;
  final VoidCallback onConnect;
  final VoidCallback onManageDevices;

  @override
  Widget build(BuildContext context) {
    return _Panel(
      title: '等待连接',
      child: Padding(
        padding: const EdgeInsets.only(top: 4),
        child: Column(
          children: [
            Row(
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: const Color(0xff172554),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Icon(
                    connecting ? Icons.sync_rounded : Icons.sensors_off_rounded,
                    size: 22,
                    color: const Color(0xff60a5fa),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        connecting ? '正在连接小车' : '小车尚未连接',
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 3),
                      const Text(
                        '连接后显示实时状态、地图和任务',
                        style: TextStyle(
                          color: Color(0xff94a3b8),
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: connecting ? null : onConnect,
                    icon: connecting
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.link_rounded),
                    label: Text(connecting ? '连接中' : '重新连接'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: onManageDevices,
                    icon: const Icon(Icons.settings_ethernet_rounded),
                    label: const Text('设备管理'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// 未连接时替代任务页的安全拦截页。
class _ConnectionRequiredPage extends StatelessWidget {
  const _ConnectionRequiredPage({
    required this.onConnect,
    required this.onManageDevices,
  });

  final VoidCallback onConnect;
  final VoidCallback onManageDevices;

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const ValueKey('connection-required'),
      padding: const EdgeInsets.all(12),
      children: [
        _OfflinePanel(
          connecting: false,
          onConnect: onConnect,
          onManageDevices: onManageDevices,
        ),
      ],
    );
  }
}

/// 首页子模块的统一外壳，提供标题和“返回首页”按钮。
class _HomeModulePage extends StatelessWidget {
  const _HomeModulePage({
    required this.title,
    required this.onBack,
    required this.child,
  });

  final String title;
  final VoidCallback onBack;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Column(
      key: ValueKey('home-$title'),
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 4, 14, 0),
          child: Row(
            children: [
              IconButton(
                tooltip: '返回首页',
                onPressed: onBack,
                icon: const Icon(Icons.arrow_back_rounded),
              ),
              const SizedBox(width: 4),
              Text(
                title,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
        ),
        Expanded(child: child),
      ],
    );
  }
}

/// 首页功能入口，支持离线禁用样式。
class _HomeShortcut extends StatelessWidget {
  const _HomeShortcut({
    required this.icon,
    required this.label,
    required this.onTap,
    this.enabled = true,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: enabled ? onTap : null,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        height: 64,
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xffdce3ea)),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              icon,
              size: 22,
              color: enabled
                  ? const Color(0xff16a66a)
                  : const Color(0xff94a3b8),
            ),
            const SizedBox(height: 4),
            Text(
              label,
              style: TextStyle(
                color: enabled ? null : const Color(0xff64748b),
                fontWeight: FontWeight.w700,
                fontSize: 13,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
