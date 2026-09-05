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
    required this.preferTotalStation,
    required this.showRelativeMap,
    required this.onLnCommand,
    required this.onTotalStationChanged,
    required this.onMapModeChanged,
    required this.onRefreshMap,
    required this.onCalibrateLocalization,
    required this.printerStatus,
    required this.printerStatusData,
    required this.onPrinterChanged,
    required this.onPrinterEnabledChanged,
    required this.onPrinterCommand,
    required this.onPrinterRawCommand,
    required this.linearSpeed,
    required this.angularSpeed,
    required this.onLinearSpeedChanged,
    required this.onAngularSpeedChanged,
    required this.onDriveCommand,
    required this.missionReady,
    required this.onStartMission,
    required this.onAddDevice,
    required this.onConnect,
    required this.onOpenMap,
    required this.onOpenControl,
    required this.controlOverlayVisible,
    required this.onToggleControlOverlay,
    required this.onOpenDrawingEditor,
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
  final bool preferTotalStation;
  final bool showRelativeMap;
  final ValueChanged<int> onLnCommand;
  final ValueChanged<bool> onTotalStationChanged;
  final ValueChanged<bool> onMapModeChanged;
  final VoidCallback onRefreshMap;
  final VoidCallback onCalibrateLocalization;
  final String printerStatus;
  final Map<String, dynamic> printerStatusData;
  final void Function(String printerName, bool active) onPrinterChanged;
  final void Function(String printerName, bool enabled) onPrinterEnabledChanged;
  final void Function(String printerName, String action) onPrinterCommand;
  final void Function(String printerName, String jsonData) onPrinterRawCommand;
  final double linearSpeed;
  final double angularSpeed;
  final ValueChanged<double> onLinearSpeedChanged;
  final ValueChanged<double> onAngularSpeedChanged;
  final void Function(double linear, double angular) onDriveCommand;
  final bool missionReady;
  final VoidCallback onStartMission;
  final VoidCallback onAddDevice;
  final VoidCallback onConnect;
  final VoidCallback onOpenMap;
  final VoidCallback onOpenControl;
  final bool controlOverlayVisible;
  final VoidCallback onToggleControlOverlay;
  final VoidCallback onOpenDrawingEditor;
  final VoidCallback onOpenDevices;

  @override
  Widget build(BuildContext context) {
    if (bridgeState != BridgeState.connected) {
      return _buildLegacy(context);
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final controlWidth = math.min(270.0, constraints.maxWidth * 0.23);
        final controlHeight = math.min(340.0, constraints.maxHeight * 0.46);
        return Stack(
          key: const ValueKey('fullscreen-map-dashboard'),
          fit: StackFit.expand,
          children: [
            ColoredBox(
              color: const Color(0xfff1f5f9),
              child: _HomeMapViewport(
                rosAvailable: rosAvailable,
                pose: robotPose,
                gridMap: gridMap,
                plannedPaths: plannedPaths,
                poseTrace: poseTrace,
                lineRunning: lineRunning,
                height: constraints.maxHeight,
                onMapTap: controlReady ? onToggleControlOverlay : null,
              ),
            ),
            Positioned(
              top: 12,
              right: 12,
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxWidth: math.min(520, constraints.maxWidth * .58),
                ),
                child: FittedBox(
                  alignment: Alignment.centerRight,
                  fit: BoxFit.scaleDown,
                  child: _HomeStatusBar(
                    bridgeState: bridgeState,
                    lineRunning: lineRunning,
                    localizationReady: localizationReady,
                    localizationSource: localizationSource,
                    printerStatus: printerStatusData,
                    battery: battery,
                  ),
                ),
              ),
            ),
            Positioned(
              top: controlOverlayVisible ? 128 : 62,
              left: 12,
              child: _HomeMapLegend(pathCount: plannedPaths.length),
            ),
            Positioned(
              top: 14,
              left: math.max(14.0, (constraints.maxWidth - 320) / 2),
              child: _TransparentOverlay(
                width: math.min(230.0, constraints.maxWidth * 0.27),
                padding: const EdgeInsets.all(2),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _MapOverlayAction(
                      icon: Icons.gamepad_rounded,
                      label: '控制',
                      onPressed: controlReady ? onToggleControlOverlay : null,
                      selected: controlOverlayVisible,
                    ),
                    _MapOverlayAction(
                      icon: Icons.devices_other_rounded,
                      label: '设备',
                      onPressed: onOpenDevices,
                    ),
                    _MapOverlayAction(
                      icon: Icons.design_services_rounded,
                      label: '图纸编辑器',
                      onPressed: onOpenDrawingEditor,
                    ),
                  ],
                ),
              ),
            ),
            if (controlOverlayVisible) ...[
              Positioned(
                top: 14,
                left: 14,
                child: _TransparentOverlay(
                  width: math.min(280.0, constraints.maxWidth * 0.27),
                  padding: const EdgeInsets.all(2),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _CompactPrinterControl(
                        status: printerStatusData,
                        onSprayChanged: onPrinterChanged,
                      ),
                      const SizedBox(height: 4),
                      _CompactLocalizationControl(
                        controlReady: controlReady,
                        localizationSource: localizationSource,
                        localizationCalibration: localizationCalibration,
                        localizationCalibrationAvailable:
                            localizationCalibrationAvailable,
                        ln150Ready: ln150Ready,
                        preferTotalStation: preferTotalStation,
                        onLnCommand: onLnCommand,
                        onTotalStationChanged: onTotalStationChanged,
                        onCalibrateLocalization: onCalibrateLocalization,
                      ),
                    ],
                  ),
                ),
              ),
              Positioned(
                right: 14,
                bottom: 14,
                child: Stack(
                  children: [
                    _TransparentOverlay(
                      width: controlWidth,
                      height: controlHeight,
                      padding: const EdgeInsets.all(4),
                      child: _ControlPage(
                        linearSpeed: linearSpeed,
                        angularSpeed: angularSpeed,
                        onLinearSpeedChanged: onLinearSpeedChanged,
                        onAngularSpeedChanged: onAngularSpeedChanged,
                        onDriveCommand: onDriveCommand,
                        printerStatus: printerStatusData,
                        onPrinterChanged: onPrinterChanged,
                        fixedLayout: true,
                        showPrinterPanel: false,
                        translucent: true,
                        showTopic: false,
                      ),
                    ),
                    Positioned(
                      top: 2,
                      right: 2,
                      child: IconButton(
                        onPressed: onToggleControlOverlay,
                        tooltip: '关闭控制',
                        icon: const Icon(Icons.close_rounded, size: 16),
                        color: const Color(0xff475569),
                        visualDensity: VisualDensity.compact,
                        padding: EdgeInsets.zero,
                        constraints: const BoxConstraints.tightFor(
                          width: 28,
                          height: 28,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        );
      },
    );
  }

  Widget _buildLegacy(BuildContext context) {
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
            enabled: showRelativeMap || localizationReady,
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
      title: showRelativeMap ? '相对地图' : '实时地图',
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          SegmentedButton<bool>(
            segments: [
              ButtonSegment(
                value: true,
                label: const Text('相对'),
                enabled: ln150Ready && localizationSource == 'ln150_imu',
              ),
              const ButtonSegment(value: false, label: Text('实时')),
            ],
            selected: {showRelativeMap},
            showSelectedIcon: false,
            onSelectionChanged: (selection) =>
                onMapModeChanged(selection.first),
          ),
          IconButton(
            tooltip: '刷新并以当前位置为原点',
            onPressed: showRelativeMap || localizationReady
                ? onRefreshMap
                : null,
            icon: const Icon(Icons.refresh_rounded, size: 21),
          ),
          IconButton(
            tooltip: '打开完整地图',
            onPressed: onOpenMap,
            icon: const Icon(Icons.open_in_full_rounded, size: 20),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (showRelativeMap)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                '相对位置  X ${(robotPose['x'] as num? ?? 0).toStringAsFixed(2)} m  ·  Y ${(robotPose['y'] as num? ?? 0).toStringAsFixed(2)} m',
                style: const TextStyle(
                  color: Color(0xff16a66a),
                  fontWeight: FontWeight.w700,
                ),
              ),
            )
          else
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                '当前位置  X ${(robotPose['x'] as num? ?? 0).toStringAsFixed(2)} m  ·  Y ${(robotPose['y'] as num? ?? 0).toStringAsFixed(2)} m',
                style: const TextStyle(
                  color: Color(0xff2563eb),
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          _RealtimeRobotView(
            rosAvailable: rosAvailable,
            pose: robotPose,
            gridMap: gridMap,
            plannedPaths: plannedPaths,
            poseTrace: poseTrace,
            lineRunning: lineRunning,
            onTap: onOpenMap,
            height: height,
          ),
        ],
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
      preferTotalStation: preferTotalStation,
      onLnCommand: onLnCommand,
      onTotalStationChanged: onTotalStationChanged,
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

class _HomeMapViewport extends StatefulWidget {
  const _HomeMapViewport({
    required this.rosAvailable,
    required this.pose,
    required this.gridMap,
    required this.plannedPaths,
    required this.poseTrace,
    required this.lineRunning,
    required this.height,
    required this.onMapTap,
  });

  final bool rosAvailable;
  final Map<String, dynamic> pose;
  final Map<String, dynamic> gridMap;
  final List<Map<String, dynamic>> plannedPaths;
  final List<List<double>> poseTrace;
  final bool lineRunning;
  final double height;
  final VoidCallback? onMapTap;

  @override
  State<_HomeMapViewport> createState() => _HomeMapViewportState();
}

class _HomeMapViewportState extends State<_HomeMapViewport> {
  double zoom = 1;
  Offset pan = Offset.zero;
  double baseZoom = 1;
  Offset basePan = Offset.zero;
  Offset startFocal = Offset.zero;
  bool transforming = false;
  bool followRobot = true;

  @override
  void dispose() {
    super.dispose();
  }

  void _onScaleStart(ScaleStartDetails details) {
    transforming = details.pointerCount > 1;
    if (transforming) {
      followRobot = false;
      baseZoom = zoom;
      basePan = pan;
      startFocal = details.localFocalPoint;
    }
  }

  void _onScaleUpdate(ScaleUpdateDetails details) {
    if (!transforming && details.pointerCount > 1) {
      transforming = true;
      followRobot = false;
      baseZoom = zoom;
      basePan = pan;
      startFocal = details.localFocalPoint;
    }
    if (!transforming) return;
    setState(() {
      zoom = (baseZoom * details.scale).clamp(0.05, 100000.0).toDouble();
      pan = basePan + (details.localFocalPoint - startFocal);
    });
  }

  void _onScaleEnd(ScaleEndDetails details) {
    transforming = false;
  }

  void _resetView() {
    setState(() {
      zoom = 1;
      pan = Offset.zero;
      followRobot = true;
    });
  }

  double get _zoomPercent => zoom * 100;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onScaleStart: _onScaleStart,
      onScaleUpdate: _onScaleUpdate,
      onScaleEnd: _onScaleEnd,
      child: Stack(
        fit: StackFit.expand,
        children: [
          ClipRect(
            child: _RealtimeRobotView(
              rosAvailable: widget.rosAvailable,
              pose: widget.pose,
              gridMap: widget.gridMap,
              plannedPaths: widget.plannedPaths,
              poseTrace: widget.poseTrace,
              lineRunning: widget.lineRunning,
              onTap: widget.onMapTap ?? () {},
              height: widget.height,
              showPoseOverlay: false,
              cameraZoom: zoom,
              cameraPan: pan,
              followRobot: followRobot,
            ),
          ),
          Positioned(
            left: 10,
            bottom: 10,
            child: Material(
              color: Colors.white.withValues(alpha: 0.16),
              shape: const StadiumBorder(),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Tooltip(
                      message: followRobot ? '已跟随小车' : '跟随小车',
                      child: IconButton(
                        onPressed: () =>
                            setState(() => followRobot = !followRobot),
                        icon: Icon(
                          followRobot
                              ? Icons.gps_fixed_rounded
                              : Icons.gps_not_fixed_rounded,
                          size: 16,
                        ),
                        color: const Color(0xff475569),
                        visualDensity: VisualDensity.compact,
                        padding: EdgeInsets.zero,
                        constraints: const BoxConstraints.tightFor(
                          width: 29,
                          height: 27,
                        ),
                      ),
                    ),
                    Tooltip(
                      message: '重置视图',
                      child: IconButton(
                        onPressed: _resetView,
                        icon: const Icon(
                          Icons.center_focus_strong_rounded,
                          size: 16,
                        ),
                        color: const Color(0xff475569),
                        visualDensity: VisualDensity.compact,
                        padding: EdgeInsets.zero,
                        constraints: const BoxConstraints.tightFor(
                          width: 29,
                          height: 27,
                        ),
                      ),
                    ),
                    AnimatedSwitcher(
                      duration: const Duration(milliseconds: 100),
                      child: Text(
                        '${_zoomPercent.round()}%',
                        key: ValueKey(_zoomPercent.round()),
                        style: const TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w700,
                          color: Color(0xff475569),
                        ),
                      ),
                    ),
                    const SizedBox(width: 4),
                    const Text(
                      '双指',
                      style: TextStyle(fontSize: 10, color: Color(0xff64748b)),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _HomeStatusBar extends StatelessWidget {
  const _HomeStatusBar({
    required this.bridgeState,
    required this.lineRunning,
    required this.localizationReady,
    required this.localizationSource,
    required this.printerStatus,
    required this.battery,
  });

  final BridgeState bridgeState;
  final bool lineRunning, localizationReady;
  final String localizationSource;
  final Map<String, dynamic> printerStatus;
  final int? battery;

  @override
  Widget build(BuildContext context) {
    final printer = printerStatus['printer_center'] is Map
        ? Map<String, dynamic>.from(printerStatus['printer_center'] as Map)
        : const <String, dynamic>{};
    final sprayState = printer['spray_state']?.toString() ?? 'idle';
    final spraying = printer['spraying'] == true || sprayState == 'spraying';
    final printerText = switch (sprayState) {
      'starting' => '喷码开启中',
      'stopping' => '喷码关闭中',
      'spraying' => '喷墨中',
      'error' => '喷码异常',
      _ => printer['connected'] == true ? '喷码待机' : '喷码离线',
    };
    final printerColor = sprayState == 'error'
        ? const Color(0xffdc2626)
        : spraying
        ? const Color(0xff16a66a)
        : const Color(0xff64748b);
    final localizationText = localizationReady
        ? localizationSource == 'ln150_imu'
              ? '全站仪定位'
              : '相对定位'
        : '定位未就绪';
    return Material(
      color: const Color(0xeefeffff),
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0xffdbe4ec)),
          boxShadow: const [
            BoxShadow(
              color: Color(0x140f172a),
              blurRadius: 8,
              offset: Offset(0, 2),
            ),
          ],
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _HomeStatusItem(
              icon: Icons.link_rounded,
              text: bridgeState == BridgeState.connected ? '已连接' : '未连接',
              color: bridgeState == BridgeState.connected
                  ? const Color(0xff16a66a)
                  : const Color(0xffdc2626),
            ),
            const _HomeStatusDivider(),
            _HomeStatusItem(
              icon: Icons.gps_fixed_rounded,
              text: localizationText,
              color: localizationReady
                  ? const Color(0xff2563eb)
                  : const Color(0xffb45309),
            ),
            const _HomeStatusDivider(),
            _HomeStatusItem(
              icon: Icons.print_rounded,
              text: printerText,
              color: printerColor,
            ),
            if (battery != null) ...[
              const _HomeStatusDivider(),
              _HomeStatusItem(
                icon: Icons.battery_std_rounded,
                text: '${battery}%',
                color: battery! > 20
                    ? const Color(0xff16a66a)
                    : const Color(0xffdc2626),
              ),
            ],
            if (lineRunning) ...[
              const _HomeStatusDivider(),
              const _HomeStatusItem(
                icon: Icons.edit_rounded,
                text: '划线中',
                color: Color(0xfff59e0b),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _HomeStatusItem extends StatelessWidget {
  const _HomeStatusItem({
    required this.icon,
    required this.text,
    required this.color,
  });
  final IconData icon;
  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Icon(icon, size: 15, color: color),
      const SizedBox(width: 4),
      Text(
        text,
        style: TextStyle(
          fontSize: 11,
          color: color,
          fontWeight: FontWeight.w700,
        ),
      ),
    ],
  );
}

class _HomeStatusDivider extends StatelessWidget {
  const _HomeStatusDivider();
  @override
  Widget build(BuildContext context) => Container(
    width: 1,
    height: 16,
    margin: const EdgeInsets.symmetric(horizontal: 8),
    color: const Color(0xffdbe4ec),
  );
}

class _HomeMapLegend extends StatelessWidget {
  const _HomeMapLegend({required this.pathCount});
  final int pathCount;

  @override
  Widget build(BuildContext context) => Material(
    color: const Color(0xeefeffff),
    borderRadius: BorderRadius.circular(8),
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xffdbe4ec)),
        boxShadow: const [
          BoxShadow(
            color: Color(0x140f172a),
            blurRadius: 8,
            offset: Offset(0, 2),
          ),
        ],
      ),
      child: Wrap(
        spacing: 8,
        runSpacing: 5,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          const _HomeLegendItem('划线路径', Color(0xff2563eb)),
          const _HomeLegendItem('转场路径', Color(0xffd97706)),
          const _HomeLegendItem('轨迹', Color(0xffea580c)),
          const _HomeLegendItem('车体', Color(0xff16a34a)),
          _HomeLegendItem(
            pathCount == 0 ? '暂无路径' : '$pathCount 条路径',
            const Color(0xff64748b),
          ),
        ],
      ),
    ),
  );
}

class _HomeLegendItem extends StatelessWidget {
  const _HomeLegendItem(this.label, this.color);
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 8,
        height: 8,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      ),
      const SizedBox(width: 4),
      Text(
        label,
        style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700),
      ),
    ],
  );
}

class _CompactPrinterControl extends StatelessWidget {
  const _CompactPrinterControl({
    required this.status,
    required this.onSprayChanged,
  });

  final Map<String, dynamic> status;
  final void Function(String printerName, bool spraying) onSprayChanged;

  @override
  Widget build(BuildContext context) {
    final printers =
        status.keys
            .where((key) => key.startsWith('printer_') && status[key] is Map)
            .toList()
          ..sort();
    if (printers.isEmpty) {
      return const _CompactOverlayRow(
        icon: Icons.print_disabled_rounded,
        label: '喷码机',
        detail: '未检测到',
      );
    }
    final key = printers.first;
    final name = key.substring('printer_'.length);
    final item = Map<String, dynamic>.from(status[key] as Map);
    final connected = item['connected'] == true;
    final spraying = connected && item['spraying'] == true;
    final state = item['spray_state']?.toString() ?? 'idle';
    final busy = state == 'starting' || state == 'stopping';
    final inkLevel = item['ink_level'];
    final label = switch (state) {
      'starting' => '开启中',
      'stopping' => '关闭中',
      'spraying' => '喷墨中',
      'triggered_unverified' => '待确认',
      'error' => '失败',
      _ => '待机',
    };
    final stateColor = state == 'error'
        ? const Color(0xffdc2626)
        : state == 'triggered_unverified'
        ? const Color(0xffb45309)
        : spraying
        ? const Color(0xff16a66a)
        : const Color(0xff64748b);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.print_rounded, size: 17, color: Color(0xff16a66a)),
        const SizedBox(width: 6),
        Flexible(
          child: Text(
            name.toUpperCase(),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
          ),
        ),
        const SizedBox(width: 5),
        _StatusChip(
          text: connected ? '已连接' : '离线',
          color: connected ? const Color(0xff16a66a) : const Color(0xff94a3b8),
        ),
        const SizedBox(width: 4),
        Text(label, style: TextStyle(fontSize: 11, color: stateColor)),
        if (inkLevel is num) ...[
          const SizedBox(width: 4),
          Text(
            '余量 ${inkLevel.toStringAsFixed(0)}%',
            style: const TextStyle(fontSize: 10, color: Color(0xff64748b)),
          ),
        ],
        if (busy)
          const Padding(
            padding: EdgeInsets.only(left: 4),
            child: SizedBox(
              width: 12,
              height: 12,
              child: CircularProgressIndicator(strokeWidth: 1.8),
            ),
          ),
        Transform.scale(
          scale: .72,
          child: Switch(
            value: spraying || state == 'starting',
            onChanged: connected && !busy
                ? (value) => onSprayChanged(name, value)
                : null,
          ),
        ),
      ],
    );
  }
}

class _CompactLocalizationControl extends StatelessWidget {
  const _CompactLocalizationControl({
    required this.controlReady,
    required this.localizationSource,
    required this.localizationCalibration,
    required this.localizationCalibrationAvailable,
    required this.ln150Ready,
    required this.preferTotalStation,
    required this.onLnCommand,
    required this.onTotalStationChanged,
    required this.onCalibrateLocalization,
  });

  final bool controlReady;
  final String localizationSource;
  final String localizationCalibration;
  final bool localizationCalibrationAvailable;
  final bool ln150Ready;
  final bool preferTotalStation;
  final ValueChanged<int> onLnCommand;
  final ValueChanged<bool> onTotalStationChanged;
  final VoidCallback onCalibrateLocalization;

  @override
  Widget build(BuildContext context) {
    final usingTotalStation = preferTotalStation && ln150Ready;
    final mode = usingTotalStation ? '全站仪' : '相对定位';
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.gps_fixed_rounded, size: 17, color: Color(0xff2563eb)),
        const SizedBox(width: 6),
        Text(
          mode,
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
        ),
        const SizedBox(width: 4),
        _StatusChip(
          text: controlReady ? '就绪' : '未就绪',
          color: controlReady
              ? const Color(0xff16a66a)
              : const Color(0xfff59e0b),
        ),
        Tooltip(
          message: ln150Ready ? '切换全站仪模式' : '未检测到全站仪',
          child: Transform.scale(
            scale: .72,
            child: Switch(
              value: preferTotalStation,
              onChanged: ln150Ready ? onTotalStationChanged : null,
            ),
          ),
        ),
        if (usingTotalStation)
          PopupMenuButton<int>(
            tooltip: '全站仪操作',
            onSelected: onLnCommand,
            icon: const Icon(Icons.tune_rounded, size: 17),
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints.tightFor(width: 30, height: 30),
            itemBuilder: (context) => const [
              PopupMenuItem(value: 1, child: Text('LN150 初始化')),
              PopupMenuItem(value: 2, child: Text('自动追踪')),
              PopupMenuItem(value: 3, child: Text('自动调平')),
            ],
          ),
        IconButton(
          tooltip: localizationCalibration == 'calibrating'
              ? '定位校准中'
              : '重置定位原点',
          onPressed:
              localizationCalibrationAvailable &&
                  localizationCalibration != 'calibrating'
              ? onCalibrateLocalization
              : null,
          icon: const Icon(Icons.my_location_rounded, size: 17),
          visualDensity: VisualDensity.compact,
        ),
      ],
    );
  }
}

class _CompactOverlayRow extends StatelessWidget {
  const _CompactOverlayRow({
    required this.icon,
    required this.label,
    required this.detail,
  });

  final IconData icon;
  final String label;
  final String detail;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Icon(icon, size: 17, color: const Color(0xff64748b)),
      const SizedBox(width: 6),
      Text(
        label,
        style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
      ),
      const SizedBox(width: 6),
      Text(
        detail,
        style: const TextStyle(fontSize: 11, color: Color(0xff64748b)),
      ),
    ],
  );
}

class _TransparentOverlay extends StatelessWidget {
  const _TransparentOverlay({
    required this.child,
    this.width,
    this.height,
    this.padding = const EdgeInsets.all(12),
  });

  final Widget child;
  final double? width;
  final double? height;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white.withValues(alpha: 0.06),
      elevation: 1,
      shadowColor: const Color(0x220f172a),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(7),
        side: const BorderSide(color: Color(0x227c8da6)),
      ),
      clipBehavior: Clip.antiAlias,
      child: SizedBox(
        width: width,
        height: height,
        child: Padding(padding: padding, child: child),
      ),
    );
  }
}

class _MapOverlayAction extends StatelessWidget {
  const _MapOverlayAction({
    required this.icon,
    required this.label,
    required this.onPressed,
    this.selected = false,
  });

  final IconData icon;
  final String label;
  final VoidCallback? onPressed;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      onPressed: onPressed,
      tooltip: label,
      visualDensity: VisualDensity.compact,
      constraints: const BoxConstraints.tightFor(width: 34, height: 30),
      padding: EdgeInsets.zero,
      style: IconButton.styleFrom(
        backgroundColor: selected
            ? const Color(0x553b82f6)
            : Colors.transparent,
        shape: const CircleBorder(),
      ),
      icon: Icon(icon, size: 18),
      color: const Color(0xff1e3a8a),
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
    required this.preferTotalStation,
    required this.onLnCommand,
    required this.onTotalStationChanged,
    required this.onCalibrateLocalization,
  });

  final bool controlReady;
  final String localizationSource;
  final String localizationCalibration;
  final bool localizationCalibrationAvailable;
  final bool ln150Ready;
  final bool preferTotalStation;
  final ValueChanged<int> onLnCommand;
  final ValueChanged<bool> onTotalStationChanged;
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
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            value: preferTotalStation,
            onChanged: onTotalStationChanged,
            title: const Text('全站仪模式'),
            subtitle: Text(
              ln150Ready ? 'LN-150 已就绪，可手动开启或关闭' : '没有全站仪时默认关闭，使用相对地图与里程计定位',
            ),
          ),
          Wrap(
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
