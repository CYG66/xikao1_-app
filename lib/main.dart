// XLine 划线小车 App 的当前主实现文件。
//
// 本文件集中了应用入口、页面切换、WebSocket 通信、业务页面、
// 通用组件和地图绘制。修改功能前可根据下方的分区注释定位。
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'constants/app_constants.dart';
import 'utils/ros_messages.dart';
import 'viewmodels/rover_device.dart';

void main() => runApp(const XLineCarApp());

// -----------------------------------------------------------------------------
// 应用入口与全局主题
// -----------------------------------------------------------------------------

/// App 根组件：设置 Material 3 主题、色彩和首页。
/// 如需修改全局配色、字体或按钮样式，从这里入手。
class XLineCarApp extends StatelessWidget {
  const XLineCarApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: AppConstants.appTitle,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xff2563eb),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xff0b1220),
        useMaterial3: true,
        cardTheme: CardThemeData(
          color: const Color(0xff111827),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
          ),
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            minimumSize: const Size(0, 44),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(14),
            ),
          ),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(
            minimumSize: const Size(0, 42),
            side: const BorderSide(color: Color(0xff273449)),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(14),
            ),
          ),
        ),
      ),
      home: const RoverHomePage(),
    );
  }
}

/// App 的主容器，承载“首页 / 任务 / 设置”三个底部栏入口。
class RoverHomePage extends StatefulWidget {
  const RoverHomePage({super.key});

  @override
  State<RoverHomePage> createState() => _RoverHomePageState();
}

/// 主页面运行状态和业务调度中心。
///
/// 这里管理页面切换、设备列表、WebSocket、任务、速度和日志。
/// 项目扩展后，建议将通信与状态逐步拆分到 `api/` 和 `stores/`。
class _RoverHomePageState extends State<RoverHomePage> {
  int tabIndex = 0;
  int homeModule = 0;
  bool lineRunning = false;
  bool printerEnabled = true;
  double linearSpeed = 0.05;
  double angularSpeed = 0.40;
  bool rosAvailable = false;
  bool backendOnline = false;
  bool controlReady = false;
  bool driveDeviceConnected = false;
  bool motorDriverReady = false;
  String driveTransport = 'usb2can';
  bool missionNodesReady = false;
  double? linearVelocity;
  double? localizationAccuracyMm;
  Map<String, dynamic> robotPose = const {};
  Map<String, dynamic> odometry = const {};
  Map<String, dynamic> reflectorPosition = const {};
  Map<String, dynamic> gridMap = const {};
  List<Map<String, dynamic>> plannedPaths = const [];
  Map<String, dynamic> printerStatus = const {};
  String missionStage = 'idle';
  String missionFile = 'test_pattern.json';
  int? missionCurrentId;
  int missionCompleted = 0;
  int missionTotal = 0;
  String missionError = '';
  String connectionMessage = '已加载默认设备，等待连接测试';
  BridgeState bridgeState = BridgeState.disconnected;
  WebSocket? socket;
  StreamSubscription? socketSub;
  final List<String> bridgeLogs = ['App 已就绪，可连接小车端 ROS2 Bridge'];

  final List<RoverDevice> devices = [
    const RoverDevice(
      name: AppConstants.defaultDeviceName,
      ip: AppConstants.defaultIp,
      port: AppConstants.defaultPort,
      domainId: AppConstants.defaultDomainId,
      type: AppConstants.defaultBridgeType,
      connected: true,
    ),
  ];

  /// 返回当前选中的小车；若无已连接设备，则返回第一台。
  RoverDevice get activeDevice {
    return devices.firstWhere(
      (device) => device.connected,
      orElse: () => devices.first,
    );
  }

  bool get localizationReady =>
      robotPose.isNotEmpty || reflectorPosition.isNotEmpty;

  bool get missionReady =>
      bridgeState == BridgeState.connected &&
      rosAvailable &&
      backendOnline &&
      missionNodesReady &&
      localizationReady &&
      centerPrinterConnected;

  Map<String, dynamic> get centerPrinter =>
      _asStringMap(printerStatus['printer_center']);

  bool get centerPrinterConnected =>
      centerPrinter['connected'] == true && centerPrinter['enabled'] == true;

  String get centerPrinterLabel {
    if (centerPrinter.isEmpty) return '未知';
    return centerPrinter['status']?.toString() ??
        (centerPrinter['connected'] == true ? '已连接' : '已断开');
  }

  @override
  void dispose() {
    socketSub?.cancel();
    socket?.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tabs = const [
      _TabItem('首页', Icons.home_rounded),
      _TabItem('任务', Icons.route_rounded),
      _TabItem('设置', Icons.tune_rounded),
    ];

    return Scaffold(
      floatingActionButton: FloatingActionButton.small(
        heroTag: 'agent_fab',
        tooltip: '智能助手',
        onPressed: _openAgentSheet,
        backgroundColor: const Color(0xff2563eb),
        foregroundColor: Colors.white,
        child: const Icon(Icons.smart_toy_rounded),
      ),
      floatingActionButtonLocation: FloatingActionButtonLocation.endFloat,
      body: SafeArea(
        child: Column(
          children: [
            _Header(
              device: activeDevice,
              lineRunning: lineRunning,
              bridgeState: bridgeState,
            ),
            Expanded(
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 220),
                child: _buildPage(),
              ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: NavigationBar(
        height: 66,
        selectedIndex: tabIndex,
        backgroundColor: const Color(0xff0f172a),
        indicatorColor: const Color(0xff1d4ed8),
        onDestinationSelected: (value) => setState(() {
          tabIndex = value;
          if (value == 0) homeModule = 0;
        }),
        destinations: [
          for (final tab in tabs)
            NavigationDestination(icon: Icon(tab.icon), label: tab.label),
        ],
      ),
    );
  }

  /// 根据底部栏索引组装三个一级页面。
  /// 任务页在离线时会被连接引导页替代。
  Widget _buildPage() {
    switch (tabIndex) {
      case 1:
        if (bridgeState != BridgeState.connected) {
          return _ConnectionRequiredPage(
            onConnect: _connectActiveDevice,
            onManageDevices: () => setState(() {
              tabIndex = 0;
              homeModule = 3;
            }),
          );
        }
        return _MissionPage(
          lineRunning: lineRunning,
          missionStage: missionStage,
          missionFile: missionFile,
          missionCurrentId: missionCurrentId,
          completed: missionCompleted,
          total: missionTotal,
          error: missionError,
          onFileChanged: (value) => setState(() => missionFile = value),
          onToggle: _toggleMission,
          onLnCommand: _sendLnCommand,
        );
      case 2:
        return _SettingsPage(
          device: activeDevice,
          onAddDevice: _openAddDeviceSheet,
          bridgeState: bridgeState,
        );
      default:
        return _buildHomePage();
    }
  }

  /// 组装首页内部模块：概览、地图、控制和设备管理。
  Widget _buildHomePage() {
    switch (homeModule) {
      case 1:
        return _HomeModulePage(
          title: '地图与路径',
          onBack: () => setState(() => homeModule = 0),
          child: _MapPage(
            connected: bridgeState == BridgeState.connected,
            lineRunning: lineRunning,
            gridMap: gridMap,
            plannedPaths: plannedPaths,
            robotPose: robotPose,
          ),
        );
      case 2:
        return _HomeModulePage(
          title: '手动控制',
          onBack: () => setState(() => homeModule = 0),
          child: _ControlPage(
            linearSpeed: linearSpeed,
            angularSpeed: angularSpeed,
            printerEnabled: printerEnabled,
            onLinearSpeedChanged: (value) =>
                setState(() => linearSpeed = value),
            onAngularSpeedChanged: (value) =>
                setState(() => angularSpeed = value),
            onPrinterChanged: _setPrinterActive,
            onDriveCommand: _sendDriveCommand,
            onPrinterCommand: _sendPrinterCommand,
          ),
        );
      case 3:
        return _HomeModulePage(
          title: '设备管理',
          onBack: () => setState(() => homeModule = 0),
          child: _DevicePage(
            devices: devices,
            message: connectionMessage,
            bridgeState: bridgeState,
            logs: bridgeLogs,
            onAddDevice: _openAddDeviceSheet,
            onConnect: _connectDevice,
            onTestActive: _connectActiveDevice,
            onDisconnect: _disconnectBridge,
          ),
        );
      default:
        return _DashboardPage(
          device: activeDevice,
          lineRunning: lineRunning,
          bridgeState: bridgeState,
          rosAvailable: rosAvailable,
          controlReady: controlReady,
          driveDeviceConnected: driveDeviceConnected,
          motorDriverReady: motorDriverReady,
          driveTransport: driveTransport,
          linearVelocity: linearVelocity,
          localizationAccuracyMm: localizationAccuracyMm,
          robotPose: robotPose,
          localizationReady: localizationReady,
          printerStatus: centerPrinterLabel,
          missionReady: missionReady,
          onStartMission: _toggleMission,
          onAddDevice: _openAddDeviceSheet,
          onConnect: _connectActiveDevice,
          onOpenMap: () => setState(() => homeModule = 1),
          onOpenControl: () => setState(() => homeModule = 2),
          onOpenDevices: () => setState(() => homeModule = 3),
        );
    }
  }

  Future<void> _openAgentSheet() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: const Color(0xff0b1220),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => FractionallySizedBox(
        heightFactor: 0.92,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 8, 4),
              child: Row(
                children: [
                  const Icon(Icons.smart_toy_rounded, color: Color(0xff60a5fa)),
                  const SizedBox(width: 10),
                  const Expanded(
                    child: Text(
                      '智能助手',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: '关闭助手',
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
            ),
            Expanded(
              child: _AgentPage(
                device: activeDevice,
                bridgeConnected: bridgeState == BridgeState.connected,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// 打开“添加设备”弹窗，保存后切换到新设备并尝试连接。
  Future<void> _openAddDeviceSheet() async {
    final device = await showModalBottomSheet<RoverDevice>(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xff0f172a),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (context) => const _AddDeviceSheet(),
    );

    if (device == null) return;
    setState(() {
      for (var index = 0; index < devices.length; index++) {
        devices[index] = RoverDevice(
          name: devices[index].name,
          ip: devices[index].ip,
          port: devices[index].port,
          domainId: devices[index].domainId,
          type: devices[index].type,
          connected: false,
        );
      }
      devices.add(device);
      connectionMessage = '已添加并连接 ${device.name}';
      tabIndex = 0;
      homeModule = 3;
    });
    unawaited(_connectActiveDevice());
  }

  /// 将指定设备设为当前设备，然后重新连接。
  void _connectDevice(int selectedIndex) {
    setState(() {
      for (var index = 0; index < devices.length; index++) {
        final device = devices[index];
        devices[index] = RoverDevice(
          name: device.name,
          ip: device.ip,
          port: device.port,
          domainId: device.domainId,
          type: device.type,
          connected: index == selectedIndex,
        );
      }
      connectionMessage = '已切换到 ${devices[selectedIndex].name}';
    });
    unawaited(_connectActiveDevice());
  }

  /// 关闭旧连接，然后连接当前设备的 WebSocket Bridge。
  /// 成功后订阅核心 ROS2 话题；4 秒内未成功则进入失败状态。
  Future<void> _connectActiveDevice() async {
    await socketSub?.cancel();
    await socket?.close();
    setState(() {
      bridgeState = BridgeState.connecting;
      connectionMessage = '正在连接 ${activeDevice.bridgeUrl}';
      _addLog('connect ${activeDevice.bridgeUrl}');
    });

    try {
      final ws = await WebSocket.connect(
        activeDevice.bridgeUrl,
      ).timeout(const Duration(seconds: 4));
      socket = ws;
      socketSub = ws.listen(
        _handleBridgeMessage,
        onDone: () {
          if (!mounted) return;
          setState(() {
            bridgeState = BridgeState.disconnected;
            connectionMessage = 'Bridge 已断开';
            _addLog('bridge closed');
          });
        },
        onError: (error) {
          if (!mounted) return;
          setState(() {
            bridgeState = BridgeState.failed;
            connectionMessage = 'Bridge 错误：$error';
            _addLog('error $error');
          });
        },
      );
      setState(() {
        bridgeState = BridgeState.connected;
        connectionMessage = '已连接 ${activeDevice.name}';
        _addLog('connected');
      });
      _subscribeCoreTopics();
    } catch (error) {
      setState(() {
        bridgeState = BridgeState.failed;
        connectionMessage = '连接失败：请确认小车端 Bridge 已启动';
        _addLog('connect failed $error');
      });
    }
  }

  /// 主动断开 WebSocket，清理订阅并将界面设为离线。
  Future<void> _disconnectBridge() async {
    await socketSub?.cancel();
    await socket?.close();
    setState(() {
      socket = null;
      socketSub = null;
      bridgeState = BridgeState.disconnected;
      connectionMessage = '已断开 Bridge';
      _addLog('disconnect');
    });
  }

  /// 处理后端推送的消息。
  ///
  /// 当前先写入通信日志。要展示真实电量、位姿和喷码状态，
  /// 需在此将 JSON 解析为遥测数据模型并更新界面。
  void _handleBridgeMessage(dynamic data) {
    if (!mounted) return;
    try {
      final decoded = data is String ? jsonDecode(data) : data;
      if (decoded is! Map) return;
      final envelope = Map<String, dynamic>.from(decoded);
      final rawStatus = envelope['op'] == 'status' ? envelope['msg'] : envelope;
      if (rawStatus is! Map) return;
      final status = Map<String, dynamic>.from(rawStatus);
      setState(() {
        rosAvailable = status['ros_available'] == true;
        backendOnline = status['online'] == true;
        controlReady = status['control_ready'] == true;
        driveDeviceConnected = status['drive_device_connected'] == true;
        motorDriverReady = status['motor_driver_ready'] == true;
        driveTransport = status['drive_transport']?.toString() ?? 'usb2can';
        missionNodesReady = status['mission_nodes_ready'] == true;
        linearVelocity = (status['linear_velocity'] as num?)?.toDouble();
        localizationAccuracyMm = (status['localization_accuracy_mm'] as num?)
            ?.toDouble();
        robotPose = _asStringMap(status['robot_pose']);
        odometry = _asStringMap(status['odometry']);
        reflectorPosition = _asStringMap(status['reflector_position']);
        gridMap = _asStringMap(status['grid_map']);
        plannedPaths = _asMapList(status['planned_paths']);
        printerStatus = _asStringMap(status['printer_status']);
        final center = _asStringMap(printerStatus['printer_center']);
        if (center['enabled'] is bool) {
          printerEnabled = center['enabled'] as bool;
        }
        missionStage = status['mission_stage']?.toString() ?? 'idle';
        missionCurrentId = (status['mission_current_id'] as num?)?.toInt();
        missionCompleted = (status['mission_completed'] as num?)?.toInt() ?? 0;
        missionTotal = (status['mission_total'] as num?)?.toInt() ?? 0;
        missionError = status['mission_error']?.toString() ?? '';
        if (status['mission_running'] is bool) {
          lineRunning = status['mission_running'] as bool;
        }
        _addLog('status updated');
      });
    } catch (error) {
      setState(() => _addLog('invalid bridge message: $error'));
    }
  }

  Map<String, dynamic> _asStringMap(Object? value) {
    return value is Map ? Map<String, dynamic>.from(value) : const {};
  }

  List<Map<String, dynamic>> _asMapList(Object? value) {
    if (value is! List) return const [];
    return value.whereType<Map>().map(Map<String, dynamic>.from).toList();
  }

  /// 连接成功后订阅 [AppConstants.coreTopics] 中的所有话题。
  void _subscribeCoreTopics() {
    for (final topic in AppConstants.coreTopics) {
      _sendBridge(RosMessages.subscribe(topic));
    }
  }

  /// 将线速度和角速度转成 `/cmd_vel` 指令。
  void _sendDriveCommand(double linear, double angular) {
    if ((linear != 0 || angular != 0) && !controlReady) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('USB2CAN 电机驱动尚未就绪')));
      return;
    }
    _sendBridge(RosMessages.cmdVel(linear, angular));
  }

  /// 调用喷码机指令，[action] 例如 `start_print` 或 `stop_print`。
  void _sendPrinterCommand(String action) {
    _sendBridge(RosMessages.printerCommand(action));
  }

  void _setPrinterActive(bool active) {
    setState(() => printerEnabled = active);
    _sendBridge(RosMessages.printerActive(active));
  }

  /// 发送 LN150 命令类型，其数字含义须与小车端定义一致。
  void _sendLnCommand(int commandType) {
    _sendBridge(RosMessages.lnCommand(commandType));
  }

  /// 启动或停止划线任务，并联动喷码机与底盘停车。
  /// 离线时会直接拦截，不会修改任务状态。
  void _toggleMission() {
    if (bridgeState != BridgeState.connected) {
      setState(() {
        connectionMessage = '小车未连接，无法执行任务';
        _addLog('mission blocked: bridge offline');
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('请先连接小车')));
      return;
    }
    if (!lineRunning && !missionReady) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('定位或喷码设备尚未上报，任务暂不可执行')));
      return;
    }
    final next = !lineRunning;
    _sendBridge(RosMessages.missionControl(next, fileName: missionFile));
    if (!next) {
      _sendDriveCommand(0, 0);
    }
  }

  /// 所有 ROS Bridge 指令的统一发送入口。
  /// 只有 WebSocket 已连接时才真正发送，否则只记录拦截日志。
  void _sendBridge(Map<String, Object?> payload) {
    final text = jsonEncode(payload);
    if (bridgeState == BridgeState.connected && socket != null) {
      socket!.add(text);
      setState(() => _addLog('send $text'));
    } else {
      setState(() => _addLog('blocked while offline $text'));
    }
  }

  /// 插入一条带时间的界面日志，最多保留 30 条。
  void _addLog(String line) {
    final time = TimeOfDay.now().format(context);
    bridgeLogs.insert(0, '$time  $line');
    if (bridgeLogs.length > 30) bridgeLogs.removeLast();
  }
}

// -----------------------------------------------------------------------------
// 业务页面与页面级导航
// -----------------------------------------------------------------------------

/// 顶部栏：显示 App 名称、当前设备地址和 Bridge 状态。
class _Header extends StatelessWidget {
  const _Header({
    required this.device,
    required this.lineRunning,
    required this.bridgeState,
  });

  final RoverDevice device;
  final bool lineRunning;
  final BridgeState bridgeState;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 6),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(16),
              gradient: const LinearGradient(
                colors: [Color(0xff2563eb), Color(0xff22c55e)],
              ),
            ),
            child: const Icon(Icons.precision_manufacturing_rounded),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'XLine 划线小车',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                ),
                Text(
                  '${device.name} · ${device.bridgeUrl}',
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: Color(0xff94a3b8),
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
          _StatusChip(
            text: lineRunning ? '划线中' : bridgeState.label,
            color: lineRunning ? const Color(0xfff59e0b) : bridgeState.color,
          ),
        ],
      ),
    );
  }
}

/// 首页概览：快捷入口、连接区、实时状态和当前任务。
/// 离线时隐藏所有遥测值，只显示连接引导。
class _DashboardPage extends StatelessWidget {
  const _DashboardPage({
    required this.device,
    required this.lineRunning,
    required this.bridgeState,
    required this.rosAvailable,
    required this.controlReady,
    required this.driveDeviceConnected,
    required this.motorDriverReady,
    required this.driveTransport,
    required this.linearVelocity,
    required this.localizationAccuracyMm,
    required this.robotPose,
    required this.localizationReady,
    required this.printerStatus,
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
  final bool controlReady;
  final bool driveDeviceConnected;
  final bool motorDriverReady;
  final String driveTransport;
  final double? linearVelocity;
  final double? localizationAccuracyMm;
  final Map<String, dynamic> robotPose;
  final bool localizationReady;
  final String printerStatus;
  final bool missionReady;
  final VoidCallback onStartMission;
  final VoidCallback onAddDevice;
  final VoidCallback onConnect;
  final VoidCallback onOpenMap;
  final VoidCallback onOpenControl;
  final VoidCallback onOpenDevices;

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const ValueKey('dashboard'),
      padding: const EdgeInsets.fromLTRB(14, 8, 14, 14),
      children: [
        _Panel(
          title: '快捷功能',
          child: Row(
            children: [
              Expanded(
                child: _HomeShortcut(
                  icon: Icons.map_rounded,
                  label: '地图',
                  onTap: onOpenMap,
                  enabled: localizationReady,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _HomeShortcut(
                  icon: Icons.gamepad_rounded,
                  label: '控制',
                  onTap: onOpenControl,
                  enabled: controlReady,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _HomeShortcut(
                  icon: Icons.devices_other_rounded,
                  label: '设备',
                  onTap: onOpenDevices,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        _Panel(
          title: '状态概览',
          trailing: _StatusChip(
            text: bridgeState.label,
            color: bridgeState.color,
          ),
          child: Column(
            children: [
              _CompactDeviceRow(device: device),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: onConnect,
                      icon: const Icon(Icons.wifi_tethering_rounded),
                      label: Text(
                        bridgeState == BridgeState.connected ? '重连' : '连接',
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: onAddDevice,
                      icon: const Icon(Icons.add_rounded),
                      label: const Text('添加设备'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        if (bridgeState != BridgeState.connected)
          _OfflinePanel(
            connecting: bridgeState == BridgeState.connecting,
            onConnect: onConnect,
            onManageDevices: onOpenDevices,
          ),
        if (bridgeState == BridgeState.connected)
          _DriveStatusPanel(
            transport: driveTransport,
            deviceConnected: driveDeviceConnected,
            motorDriverReady: motorDriverReady,
            controlReady: controlReady,
          ),
        if (bridgeState == BridgeState.connected) const SizedBox(height: 12),
        if (bridgeState == BridgeState.connected)
          _MetricStrip(
            controlReady: controlReady,
            linearVelocity: linearVelocity,
            localizationAccuracyMm: localizationAccuracyMm,
            localizationReady: localizationReady,
            printerStatus: printerStatus,
          ),
        if (bridgeState == BridgeState.connected) const SizedBox(height: 12),
        if (bridgeState == BridgeState.connected)
          _Panel(
            title: '实时视图',
            trailing: Text(
              robotPose.isEmpty ? '等待数据' : '/robot_pose',
              style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
            ),
            child: _RealtimeRobotView(
              rosAvailable: rosAvailable,
              pose: robotPose,
            ),
          ),
        if (bridgeState == BridgeState.connected) const SizedBox(height: 12),
        if (bridgeState == BridgeState.connected)
          _Panel(
            title: '当前任务',
            trailing: _StatusChip(
              text: lineRunning
                  ? '执行中'
                  : missionReady
                  ? '可执行'
                  : '未就绪',
              color: lineRunning
                  ? const Color(0xfff59e0b)
                  : missionReady
                  ? const Color(0xff22c55e)
                  : const Color(0xff64748b),
            ),
            child: Column(
              children: [
                _MissionStep(title: '定位与追踪', done: localizationReady),
                _MissionStep(
                  title: '路径执行',
                  done: lineRunning && localizationReady,
                ),
                _MissionStep(
                  title: '喷码同步',
                  done: lineRunning && printerStatus != '未知',
                ),
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: lineRunning || missionReady
                        ? onStartMission
                        : null,
                    icon: Icon(
                      lineRunning
                          ? Icons.stop_rounded
                          : Icons.play_arrow_rounded,
                    ),
                    label: Text(
                      lineRunning
                          ? '停止划线任务'
                          : missionReady
                          ? '开始划线任务'
                          : '等待定位与喷码设备',
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
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
        padding: const EdgeInsets.symmetric(vertical: 18),
        child: Column(
          children: [
            Container(
              width: 64,
              height: 64,
              decoration: const BoxDecoration(
                color: Color(0xff172554),
                shape: BoxShape.circle,
              ),
              child: Icon(
                connecting ? Icons.sync_rounded : Icons.sensors_off_rounded,
                size: 30,
                color: const Color(0xff60a5fa),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              connecting ? '正在连接小车' : '小车尚未连接',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            const Text(
              '连接成功后将显示实时状态、地图和任务信息',
              textAlign: TextAlign.center,
              style: TextStyle(color: Color(0xff94a3b8)),
            ),
            const SizedBox(height: 18),
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
      padding: const EdgeInsets.all(14),
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
      borderRadius: BorderRadius.circular(12),
      child: Container(
        height: 76,
        decoration: BoxDecoration(
          color: const Color(0xff101d33),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xff22304a)),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              icon,
              color: enabled
                  ? const Color(0xff60a5fa)
                  : const Color(0xff475569),
            ),
            const SizedBox(height: 7),
            Text(
              label,
              style: TextStyle(
                color: enabled ? null : const Color(0xff64748b),
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 设备管理页：切换小车、测试/断开连接、查看 Bridge 日志。
class _DevicePage extends StatelessWidget {
  const _DevicePage({
    required this.devices,
    required this.message,
    required this.bridgeState,
    required this.logs,
    required this.onAddDevice,
    required this.onConnect,
    required this.onTestActive,
    required this.onDisconnect,
  });

  final List<RoverDevice> devices;
  final String message;
  final BridgeState bridgeState;
  final List<String> logs;
  final VoidCallback onAddDevice;
  final ValueChanged<int> onConnect;
  final VoidCallback onTestActive;
  final VoidCallback onDisconnect;

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const ValueKey('devices'),
      padding: const EdgeInsets.all(14),
      children: [
        _Panel(
          title: '设备管理',
          trailing: FilledButton.icon(
            onPressed: onAddDevice,
            icon: const Icon(Icons.add_rounded),
            label: const Text('添加'),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(message, style: const TextStyle(color: Color(0xff94a3b8))),
              const SizedBox(height: 12),
              Row(
                children: [
                  _StatusChip(
                    text: bridgeState.label,
                    color: bridgeState.color,
                  ),
                  const Spacer(),
                  TextButton.icon(
                    onPressed: onTestActive,
                    icon: const Icon(Icons.network_check_rounded),
                    label: const Text('连接测试'),
                  ),
                  TextButton.icon(
                    onPressed: onDisconnect,
                    icon: const Icon(Icons.link_off_rounded),
                    label: const Text('断开'),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              for (var i = 0; i < devices.length; i++)
                _DeviceTile(device: devices[i], onConnect: () => onConnect(i)),
            ],
          ),
        ),
        const SizedBox(height: 14),
        _Panel(
          title: 'Bridge 通信日志',
          trailing: const Text(
            'JSON ROS Bridge',
            style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final line in logs.take(10))
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Text(
                    line,
                    style: const TextStyle(
                      color: Color(0xffcbd5e1),
                      fontSize: 12,
                    ),
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 添加小车的底部弹窗入口。
class _AddDeviceSheet extends StatefulWidget {
  const _AddDeviceSheet();

  @override
  State<_AddDeviceSheet> createState() => _AddDeviceSheetState();
}

/// 管理设备表单、输入校验和测试状态。
class _AddDeviceSheetState extends State<_AddDeviceSheet> {
  final nameController = TextEditingController(text: 'XLine-Car-02');
  final ipController = TextEditingController(text: '192.168.0.100');
  final portController = TextEditingController(text: '8000');
  final domainController = TextEditingController(text: '0');
  static const String type = 'FastAPI Backend';
  String testStatus = '未测试';
  bool testing = false;

  @override
  void dispose() {
    nameController.dispose();
    ipController.dispose();
    portController.dispose();
    domainController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(
        18,
        18,
        18,
        MediaQuery.of(context).viewInsets.bottom + 18,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    '添加划线小车',
                    style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900),
                  ),
                ),
                IconButton(
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(Icons.close_rounded),
                ),
              ],
            ),
            const SizedBox(height: 12),
            _Field(
              label: '设备名称',
              controller: nameController,
              icon: Icons.badge_rounded,
            ),
            _Field(
              label: '机器人 IP',
              controller: ipController,
              icon: Icons.router_rounded,
              keyboardType: TextInputType.number,
            ),
            Row(
              children: [
                Expanded(
                  child: _Field(
                    label: '端口',
                    controller: portController,
                    icon: Icons.settings_ethernet_rounded,
                    keyboardType: TextInputType.number,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: _Field(
                    label: 'ROS Domain',
                    controller: domainController,
                    icon: Icons.hub_rounded,
                    keyboardType: TextInputType.number,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            const _ConfigRow('连接类型', 'FastAPI ROS2 Bridge'),
            const SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(16),
                color: const Color(0xff101d33),
                border: Border.all(color: const Color(0xff22304a)),
              ),
              child: Text(
                '连接地址：ws://${ipController.text}:${portController.text}\n状态：$testStatus',
                style: const TextStyle(color: Color(0xffcbd5e1), height: 1.5),
              ),
            ),
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: testing ? null : _testConnection,
                    icon: testing
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.network_check_rounded),
                    label: const Text('连接测试'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: FilledButton.icon(
                    onPressed: _saveDevice,
                    icon: const Icon(Icons.save_rounded),
                    label: const Text('保存并连接'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// 请求后端 `/health`，只有收到 `ok: true` 才判定连接测试成功。
  Future<void> _testConnection() async {
    setState(() {
      testing = true;
      testStatus = '正在检查 FastAPI ROS2 Bridge...';
    });
    final ip = ipController.text.trim();
    final port = int.tryParse(portController.text.trim());
    String result;
    if (ip.isEmpty || port == null) {
      result = '失败：请填写有效的 IP 和端口';
    } else {
      final client = HttpClient()
        ..connectionTimeout = const Duration(seconds: 3);
      try {
        final request = await client.getUrl(
          Uri.parse('http://$ip:$port/health'),
        );
        final response = await request.close().timeout(
          const Duration(seconds: 4),
        );
        final body = await utf8.decoder.bind(response).join();
        final decoded = jsonDecode(body);
        result =
            response.statusCode == 200 &&
                decoded is Map &&
                decoded['ok'] == true
            ? '测试通过：后端健康检查正常'
            : '失败：后端响应无效';
      } catch (error) {
        result = '失败：无法访问后端';
      } finally {
        client.close(force: true);
      }
    }
    if (!mounted) return;
    setState(() {
      testing = false;
      testStatus = result;
    });
  }

  /// 校验必填项，生成 [RoverDevice] 并关闭弹窗。
  void _saveDevice() {
    final ip = ipController.text.trim();
    final name = nameController.text.trim();
    final port = int.tryParse(portController.text.trim()) ?? 8000;
    final domainId = int.tryParse(domainController.text.trim()) ?? 0;
    if (ip.isEmpty || name.isEmpty) {
      setState(() => testStatus = '失败：设备名称和 IP 不能为空');
      return;
    }
    Navigator.pop(
      context,
      RoverDevice(
        name: name,
        ip: ip,
        port: port,
        domainId: domainId,
        type: type,
        connected: true,
      ),
    );
  }
}

/// 地图与划线路径页，严格显示规划器发布的栅格、MarkerArray 和定位位姿。
class _MapPage extends StatelessWidget {
  const _MapPage({
    required this.connected,
    required this.lineRunning,
    required this.gridMap,
    required this.plannedPaths,
    required this.robotPose,
  });

  final bool connected;
  final bool lineRunning;
  final Map<String, dynamic> gridMap;
  final List<Map<String, dynamic>> plannedPaths;
  final Map<String, dynamic> robotPose;

  int get waypointCount => plannedPaths.fold<int>(
    0,
    (total, path) => total + ((path['points'] as List?)?.length ?? 0),
  );

  double get pathLength {
    var total = 0.0;
    for (final path in plannedPaths) {
      final points = path['points'] as List? ?? const [];
      for (var index = 1; index < points.length; index++) {
        final a = points[index - 1] as List;
        final b = points[index] as List;
        final dx = (b[0] as num).toDouble() - (a[0] as num).toDouble();
        final dy = (b[1] as num).toDouble() - (a[1] as num).toDouble();
        total += Offset(dx, dy).distance;
      }
    }
    return total;
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const ValueKey('map'),
      padding: const EdgeInsets.all(14),
      children: [
        _Panel(
          title: '地图与划线路径',
          trailing: Text(
            gridMap['frame_id']?.toString() ?? '等待 map frame',
            style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
          ),
          child: SizedBox(
            height: 390,
            child: !connected
                ? const _MapEmptyState(text: '连接小车后显示规划地图')
                : gridMap.isEmpty && plannedPaths.isEmpty
                ? const _MapEmptyState(text: '等待路径规划器发布地图')
                : ClipRect(
                    child: InteractiveViewer(
                      minScale: 0.7,
                      maxScale: 8,
                      boundaryMargin: const EdgeInsets.all(120),
                      child: CustomPaint(
                        size: const Size(700, 700),
                        painter: _MapPainter(
                          lineRunning: lineRunning,
                          gridMap: gridMap,
                          plannedPaths: plannedPaths,
                          robotPose: robotPose,
                        ),
                      ),
                    ),
                  ),
          ),
        ),
        const SizedBox(height: 14),
        Row(
          children: [
            Expanded(
              child: _MetricCard(
                title: '航点',
                value: waypointCount == 0 ? '--' : '$waypointCount',
                note: '规划器轨迹点',
                icon: Icons.timeline_rounded,
              ),
            ),
            SizedBox(width: 12),
            Expanded(
              child: _MetricCard(
                title: '总长度',
                value: pathLength == 0
                    ? '--'
                    : '${pathLength.toStringAsFixed(2)}m',
                note: '真实规划路径',
                icon: Icons.straighten_rounded,
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _MapEmptyState extends StatelessWidget {
  const _MapEmptyState({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.map_outlined, size: 42, color: Color(0xff64748b)),
        const SizedBox(height: 12),
        Text(text, style: const TextStyle(color: Color(0xff94a3b8))),
      ],
    ),
  );
}

/// 手动控制页：速度调节、方向控制和喷码机快捷指令。
class _ControlPage extends StatelessWidget {
  const _ControlPage({
    required this.linearSpeed,
    required this.angularSpeed,
    required this.onLinearSpeedChanged,
    required this.onAngularSpeedChanged,
    required this.printerEnabled,
    required this.onPrinterChanged,
    required this.onDriveCommand,
    required this.onPrinterCommand,
  });

  final double linearSpeed;
  final double angularSpeed;
  final ValueChanged<double> onLinearSpeedChanged;
  final ValueChanged<double> onAngularSpeedChanged;
  final bool printerEnabled;
  final ValueChanged<bool> onPrinterChanged;
  final void Function(double linear, double angular) onDriveCommand;
  final ValueChanged<String> onPrinterCommand;

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const ValueKey('control'),
      padding: const EdgeInsets.all(14),
      children: [
        _Panel(
          title: '遥控底盘',
          trailing: const Text(
            '/tablet_cmd_vel',
            style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
          ),
          child: Column(
            children: [
              const SizedBox(height: 12),
              const _Joystick(),
              const SizedBox(height: 14),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                alignment: WrapAlignment.center,
                children: [
                  _DriveCommandButton(
                    label: '前进',
                    icon: Icons.arrow_upward_rounded,
                    onStart: () => onDriveCommand(linearSpeed, 0),
                    onStop: () => onDriveCommand(0, 0),
                  ),
                  _DriveCommandButton(
                    label: '左转',
                    icon: Icons.turn_left_rounded,
                    onStart: () => onDriveCommand(0, angularSpeed),
                    onStop: () => onDriveCommand(0, 0),
                  ),
                  _CommandButton(
                    label: '停止',
                    icon: Icons.stop_rounded,
                    onPressed: () => onDriveCommand(0, 0),
                  ),
                  _DriveCommandButton(
                    label: '右转',
                    icon: Icons.turn_right_rounded,
                    onStart: () => onDriveCommand(0, -angularSpeed),
                    onStop: () => onDriveCommand(0, 0),
                  ),
                  _DriveCommandButton(
                    label: '后退',
                    icon: Icons.arrow_downward_rounded,
                    onStart: () => onDriveCommand(-linearSpeed, 0),
                    onStop: () => onDriveCommand(0, 0),
                  ),
                ],
              ),
              const SizedBox(height: 18),
              Row(
                children: [
                  const SizedBox(width: 72, child: Text('线速度')),
                  Expanded(
                    child: Slider(
                      value: linearSpeed,
                      min: 0.01,
                      max: 1.0,
                      divisions: 99,
                      label: '${linearSpeed.toStringAsFixed(2)} m/s',
                      onChanged: onLinearSpeedChanged,
                    ),
                  ),
                  SizedBox(
                    width: 70,
                    child: Text('${linearSpeed.toStringAsFixed(2)}m/s'),
                  ),
                ],
              ),
              Row(
                children: [
                  const SizedBox(width: 72, child: Text('角速度')),
                  Expanded(
                    child: Slider(
                      value: angularSpeed,
                      min: 0.1,
                      max: 1.5,
                      divisions: 14,
                      label: '${angularSpeed.toStringAsFixed(1)} rad/s',
                      onChanged: onAngularSpeedChanged,
                    ),
                  ),
                  SizedBox(
                    width: 70,
                    child: Text('${angularSpeed.toStringAsFixed(1)}rad/s'),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        _Panel(
          title: '喷码机控制',
          trailing: _StatusChip(
            text: printerEnabled ? 'Ready' : 'Off',
            color: printerEnabled
                ? const Color(0xff22c55e)
                : const Color(0xff64748b),
          ),
          child: Column(
            children: [
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: printerEnabled,
                onChanged: onPrinterChanged,
                title: const Text('center 喷码机'),
                subtitle: const Text('对应 /printer/quick_command'),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  _CommandButton(
                    label: '蜂鸣测试',
                    icon: Icons.volume_up_rounded,
                    onPressed: () => onPrinterCommand('beep'),
                  ),
                  _CommandButton(
                    label: '开始打印',
                    icon: Icons.play_circle_rounded,
                    onPressed: () => onPrinterCommand('start_print'),
                  ),
                  _CommandButton(
                    label: '测试打印',
                    icon: Icons.science_rounded,
                    onPressed: () => onPrinterCommand('test_print'),
                  ),
                  _CommandButton(
                    label: '停止打印',
                    icon: Icons.stop_circle_rounded,
                    onPressed: () => onPrinterCommand('stop_print'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 任务页：展示划线步骤，控制任务并发送 LN150 指令。
class _MissionPage extends StatelessWidget {
  const _MissionPage({
    required this.lineRunning,
    required this.missionStage,
    required this.missionFile,
    required this.missionCurrentId,
    required this.completed,
    required this.total,
    required this.error,
    required this.onFileChanged,
    required this.onToggle,
    required this.onLnCommand,
  });

  final bool lineRunning;
  final String missionStage;
  final String missionFile;
  final int? missionCurrentId;
  final int completed;
  final int total;
  final String error;
  final ValueChanged<String> onFileChanged;
  final VoidCallback onToggle;
  final ValueChanged<int> onLnCommand;

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const ValueKey('mission'),
      padding: const EdgeInsets.all(14),
      children: [
        _Panel(
          title: '划线任务编排',
          trailing: Text(
            _missionStageLabel(missionStage),
            style: const TextStyle(color: Color(0xff94a3b8)),
          ),
          child: Column(
            children: [
              DropdownButtonFormField<String>(
                initialValue: missionFile,
                decoration: _inputDecoration(
                  'CAD 转换任务',
                  Icons.description_rounded,
                ),
                items: const [
                  DropdownMenuItem(
                    value: 'test_pattern.json',
                    child: Text('test_pattern.json'),
                  ),
                  DropdownMenuItem(
                    value: 'huanong_skeleton.json',
                    child: Text('huanong_skeleton.json'),
                  ),
                  DropdownMenuItem(
                    value: 'square_image.json',
                    child: Text('square_image.json'),
                  ),
                ],
                onChanged: lineRunning
                    ? null
                    : (value) {
                        if (value != null) onFileChanged(value);
                      },
              ),
              const SizedBox(height: 12),
              _TaskTile(
                '路径规划',
                '/plan_path',
                missionStage != 'idle' && missionStage != 'failed',
              ),
              _TaskTile('定位闭环', '/robot_pose', lineRunning || completed > 0),
              _TaskTile('路径执行', '/execute_plan', lineRunning || completed > 0),
              _TaskTile(
                '执行进度',
                total == 0
                    ? '等待规划结果'
                    : '$completed / $total · 当前 ID ${missionCurrentId ?? '--'}',
                missionStage == 'completed',
              ),
              if (error.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(error, style: const TextStyle(color: Color(0xffef4444))),
              ],
              const SizedBox(height: 10),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
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
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: onToggle,
                  icon: Icon(
                    lineRunning ? Icons.stop_rounded : Icons.play_arrow_rounded,
                  ),
                  label: Text(lineRunning ? '取消并停车' : '规划并执行'),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        const _Panel(
          title: '关键话题',
          child: Column(
            children: [
              _TopicRow('/imu', 'sensor_msgs/Imu'),
              _TopicRow('/robot_pose', 'geometry_msgs/PoseStamped'),
              _TopicRow('/reflector_position', 'geometry_msgs/PointStamped'),
              _TopicRow('/plan_path', 'xline_path_planner/PlanPath'),
              _TopicRow('/execute_plan', 'xline_msgs/ExecutePlan'),
              _TopicRow('/tablet_cmd_vel', 'geometry_msgs/Twist'),
            ],
          ),
        ),
      ],
    );
  }

  static String _missionStageLabel(String stage) {
    const labels = {
      'idle': '待启动',
      'planning': '规划中',
      'executing': '执行中',
      'completed': '已完成',
      'cancelled': '已取消',
      'failed': '失败',
    };
    return labels[stage] ?? stage;
  }
}

/// 设置页：查看当前设备并调整划线宽度等 App 参数。
class _AgentPage extends StatefulWidget {
  const _AgentPage({required this.device, required this.bridgeConnected});

  final RoverDevice device;
  final bool bridgeConnected;

  @override
  State<_AgentPage> createState() => _AgentPageState();
}

class _AgentPageState extends State<_AgentPage> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<_AgentChatItem> _messages = [
    const _AgentChatItem(
      role: 'assistant',
      content: '我可以检查设备状态、解释故障、规划操作，并在你确认后调用机器人工具。',
    ),
  ];
  bool _sending = false;
  int _inputTokens = 0;
  int _outputTokens = 0;

  int get _totalTokens => _inputTokens + _outputTokens;

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _send([String? suggested]) async {
    final text = (suggested ?? _controller.text).trim();
    if (text.isEmpty || _sending) return;
    if (!widget.bridgeConnected) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('请先连接小车后端')));
      return;
    }

    final history = _messages
        .where((item) => item.content.isNotEmpty)
        .map((item) => {'role': item.role, 'content': item.content})
        .toList();
    setState(() {
      _messages.add(_AgentChatItem(role: 'user', content: text));
      _controller.clear();
      _sending = true;
    });
    _scrollToBottom();

    try {
      final result = await _post('/api/agent/chat', {
        'message': text,
        'history': history,
      });
      final usage = result['usage'] is Map
          ? Map<String, dynamic>.from(result['usage'] as Map)
          : const <String, dynamic>{};
      final pending = result['pending_action'] is Map
          ? Map<String, dynamic>.from(result['pending_action'] as Map)
          : null;
      if (!mounted) return;
      setState(() {
        _inputTokens += (usage['input_tokens'] as num?)?.toInt() ?? 0;
        _outputTokens += (usage['output_tokens'] as num?)?.toInt() ?? 0;
        _messages.add(
          _AgentChatItem(
            role: 'assistant',
            content: result['message']?.toString() ?? '助手没有返回内容。',
            pendingAction: pending,
            isError: result['ok'] != true,
          ),
        );
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _messages.add(
          _AgentChatItem(
            role: 'assistant',
            content: '请求失败：$error',
            isError: true,
          ),
        );
      });
    } finally {
      if (mounted) {
        setState(() => _sending = false);
        _scrollToBottom();
      }
    }
  }

  Future<void> _confirm(Map<String, dynamic> action, bool approved) async {
    final id = action['id']?.toString();
    if (id == null || _sending) return;
    setState(() => _sending = true);
    try {
      final result = await _post('/api/agent/confirm', {
        'action_id': id,
        'approved': approved,
      });
      if (!mounted) return;
      setState(() {
        for (var index = 0; index < _messages.length; index++) {
          if (_messages[index].pendingAction?['id'] == id) {
            _messages[index] = _messages[index].copyWith(pendingAction: null);
          }
        }
        _messages.add(
          _AgentChatItem(
            role: 'assistant',
            content: result['message']?.toString() ?? '操作已处理。',
            isError: result['ok'] != true,
          ),
        );
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _messages.add(
          _AgentChatItem(
            role: 'assistant',
            content: '确认失败：$error',
            isError: true,
          ),
        );
      });
    } finally {
      if (mounted) {
        setState(() => _sending = false);
        _scrollToBottom();
      }
    }
  }

  Future<Map<String, dynamic>> _post(
    String path,
    Map<String, Object?> body,
  ) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    try {
      final request = await client.postUrl(
        Uri.parse('http://${widget.device.ip}:${widget.device.port}$path'),
      );
      request.headers.contentType = ContentType.json;
      request.write(jsonEncode(body));
      final response = await request.close().timeout(
        const Duration(seconds: 55),
      );
      final raw = await response.transform(utf8.decoder).join();
      final decoded = jsonDecode(raw);
      if (decoded is! Map) throw const FormatException('后端响应格式错误');
      if (response.statusCode >= 400) {
        throw HttpException(
          decoded['detail']?.toString() ?? 'HTTP ${response.statusCode}',
        );
      }
      return Map<String, dynamic>.from(decoded);
    } finally {
      client.close(force: true);
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    const suggestions = ['检查小车是否可以开始任务', '解释当前未就绪的原因', '规划一个 5×3 米矩形'];
    return Column(
      children: [
        Container(
          margin: const EdgeInsets.fromLTRB(14, 8, 14, 0),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(
            color: const Color(0xff111827),
            border: Border.all(color: const Color(0xff22304a)),
            borderRadius: BorderRadius.circular(16),
          ),
          child: Row(
            children: [
              const Icon(Icons.smart_toy_rounded, color: Color(0xff60a5fa)),
              const SizedBox(width: 10),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'XLine Agent',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
                    Text(
                      '建议可直接查看，设备操作需要确认',
                      style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
                    ),
                  ],
                ),
              ),
              _StatusChip(
                text: widget.bridgeConnected ? '在线' : '离线',
                color: widget.bridgeConnected
                    ? const Color(0xff22c55e)
                    : const Color(0xff64748b),
              ),
            ],
          ),
        ),
        Expanded(
          child: ListView(
            controller: _scrollController,
            padding: const EdgeInsets.fromLTRB(14, 14, 14, 8),
            children: [
              if (_messages.length == 1)
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final suggestion in suggestions)
                      ActionChip(
                        avatar: const Icon(
                          Icons.auto_awesome_rounded,
                          size: 16,
                        ),
                        label: Text(suggestion),
                        onPressed: () => _send(suggestion),
                      ),
                  ],
                ),
              if (_messages.length == 1) const SizedBox(height: 14),
              for (final message in _messages)
                _AgentBubble(
                  item: message,
                  onConfirm: message.pendingAction == null
                      ? null
                      : (approved) =>
                            _confirm(message.pendingAction!, approved),
                ),
              if (_sending)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Row(
                    children: [
                      SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                      SizedBox(width: 10),
                      Text('正在分析机器人状态…'),
                    ],
                  ),
                ),
            ],
          ),
        ),
        Container(
          padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
          decoration: const BoxDecoration(
            color: Color(0xff0f172a),
            border: Border(top: BorderSide(color: Color(0xff22304a))),
          ),
          child: SafeArea(
            top: false,
            child: Column(
              children: [
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _controller,
                        enabled: !_sending,
                        minLines: 1,
                        maxLines: 4,
                        textInputAction: TextInputAction.send,
                        onSubmitted: (_) => _send(),
                        decoration: _inputDecoration(
                          '输入任务或问题',
                          Icons.chat_bubble_outline_rounded,
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    IconButton.filled(
                      tooltip: '发送',
                      onPressed: _sending ? null : _send,
                      icon: const Icon(Icons.send_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 7),
                Row(
                  children: [
                    const Icon(
                      Icons.token_rounded,
                      size: 15,
                      color: Color(0xff64748b),
                    ),
                    const SizedBox(width: 5),
                    Text(
                      '输入 $_inputTokens · 输出 $_outputTokens · 总计 $_totalTokens tokens',
                      style: const TextStyle(
                        color: Color(0xff64748b),
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _AgentChatItem {
  const _AgentChatItem({
    required this.role,
    required this.content,
    this.pendingAction,
    this.isError = false,
  });

  final String role;
  final String content;
  final Map<String, dynamic>? pendingAction;
  final bool isError;

  _AgentChatItem copyWith({Map<String, dynamic>? pendingAction}) {
    return _AgentChatItem(
      role: role,
      content: content,
      pendingAction: pendingAction,
      isError: isError,
    );
  }
}

class _AgentBubble extends StatelessWidget {
  const _AgentBubble({required this.item, this.onConfirm});

  final _AgentChatItem item;
  final ValueChanged<bool>? onConfirm;

  @override
  Widget build(BuildContext context) {
    final user = item.role == 'user';
    final color = item.isError
        ? const Color(0xff3b1720)
        : user
        ? const Color(0xff1d4ed8)
        : const Color(0xff111827);
    return Align(
      alignment: user ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 620),
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(13),
        decoration: BoxDecoration(
          color: color,
          border: Border.all(
            color: item.isError
                ? const Color(0xffef4444)
                : const Color(0xff22304a),
          ),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(item.content, style: const TextStyle(height: 1.45)),
            if (item.pendingAction != null) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xff0b1220),
                  borderRadius: BorderRadius.circular(7),
                ),
                child: Row(
                  children: [
                    const Icon(
                      Icons.build_circle_outlined,
                      color: Color(0xfff59e0b),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        item.pendingAction!['label']?.toString() ?? '机器人操作',
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => onConfirm?.call(false),
                      child: const Text('取消'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: () => onConfirm?.call(true),
                      icon: const Icon(Icons.check_rounded),
                      label: const Text('确认执行'),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SettingsPage extends StatelessWidget {
  const _SettingsPage({
    required this.device,
    required this.onAddDevice,
    required this.bridgeState,
  });

  final RoverDevice device;
  final VoidCallback onAddDevice;
  final BridgeState bridgeState;

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const ValueKey('settings'),
      padding: const EdgeInsets.all(14),
      children: [
        _Panel(
          title: '连接配置',
          trailing: TextButton.icon(
            onPressed: onAddDevice,
            icon: const Icon(Icons.add_link_rounded),
            label: const Text('添加设备'),
          ),
          child: Column(
            children: [
              _ConfigRow('当前设备', device.name),
              _ConfigRow('机器人 IP', device.ip),
              _ConfigRow('Bridge', device.bridgeUrl),
              _ConfigRow('ROS Domain ID', '${device.domainId}'),
              _ConfigRow('连接状态', bridgeState.label),
            ],
          ),
        ),
        const SizedBox(height: 14),
        const _Panel(
          title: 'ROS2 接口',
          child: Column(
            children: [
              _ConfigRow('定位来源', 'LN150 + IMU'),
              _ConfigRow('手动控制', '/tablet_cmd_vel'),
              _ConfigRow('路径规划', '/plan_path'),
              _ConfigRow('任务执行', '/execute_plan'),
            ],
          ),
        ),
        const SizedBox(height: 14),
        _AiSettingsPanel(
          device: device,
          bridgeConnected: bridgeState == BridgeState.connected,
        ),
      ],
    );
  }
}

class _AiSettingsPanel extends StatefulWidget {
  const _AiSettingsPanel({required this.device, required this.bridgeConnected});

  final RoverDevice device;
  final bool bridgeConnected;

  @override
  State<_AiSettingsPanel> createState() => _AiSettingsPanelState();
}

class _AiSettingsPanelState extends State<_AiSettingsPanel> {
  static const Map<String, String> providerLabels = {
    'openai': 'OpenAI',
    'anthropic': 'Claude（Anthropic）',
    'gemini': 'Gemini（Google）',
    'deepseek': 'DeepSeek',
    'qwen': '通义千问（Qwen）',
    'kimi': 'Kimi（月之暗面）',
    'glm': '智谱 GLM',
    'minimax': 'MiniMax',
    'local': '本地诊断助手（零 Token）',
  };

  static const Map<String, List<String>> modelsByProvider = {
    'openai': ['gpt-5.1', 'gpt-5-mini', 'gpt-5-nano', 'gpt-4.1'],
    'anthropic': ['claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5'],
    'gemini': [
      'gemini-3.6-flash',
      'gemini-3.5-flash',
      'gemini-3.1-pro-preview',
      'gemini-2.5-pro',
    ],
    'deepseek': ['deepseek-v4-pro', 'deepseek-v4-flash'],
    'qwen': ['qwen3.7-max', 'qwen3.7-plus', 'qwen3.6-flash'],
    'kimi': ['kimi-k2.5', 'kimi-k2-thinking', 'moonshot-v1-auto'],
    'glm': ['glm-5', 'glm-4.7', 'glm-4.5-air'],
    'minimax': ['MiniMax-M2.7', 'MiniMax-M2.7-highspeed', 'MiniMax-M2.5'],
    'local': ['xline-local-diagnostics'],
  };

  final TextEditingController apiKeyController = TextEditingController();
  String mode = 'openai';
  String model = 'gpt-5.1';
  bool apiKeyConfigured = false;
  Set<String> configuredProviders = {};
  bool showApiKey = false;
  bool loading = false;
  String message = '连接小车后读取 AI 配置';

  @override
  void initState() {
    super.initState();
    if (widget.bridgeConnected) unawaited(_load());
  }

  @override
  void didUpdateWidget(covariant _AiSettingsPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!oldWidget.bridgeConnected && widget.bridgeConnected) {
      unawaited(_load());
    }
  }

  @override
  void dispose() {
    apiKeyController.dispose();
    super.dispose();
  }

  Future<Map<String, dynamic>> _request(String method, {Object? body}) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
    try {
      final uri = Uri.parse(
        'http://${widget.device.ip}:${widget.device.port}/api/agent/config',
      );
      final request = method == 'GET'
          ? await client.getUrl(uri)
          : await client.postUrl(uri);
      request.headers.contentType = ContentType.json;
      if (body != null) request.write(jsonEncode(body));
      final response = await request.close().timeout(
        const Duration(seconds: 6),
      );
      final text = await utf8.decoder.bind(response).join();
      final decoded = jsonDecode(text);
      if (response.statusCode != 200 || decoded is! Map) {
        throw const FormatException('AI 配置响应无效');
      }
      return Map<String, dynamic>.from(decoded);
    } finally {
      client.close(force: true);
    }
  }

  Future<void> _load() async {
    setState(() => loading = true);
    try {
      final result = await _request('GET');
      if (!mounted) return;
      setState(() {
        final loadedMode = result['mode']?.toString() ?? 'openai';
        mode = modelsByProvider.containsKey(loadedMode) ? loadedMode : 'openai';
        final loadedModel = result['model']?.toString();
        model = modelsByProvider[mode]!.contains(loadedModel)
            ? loadedModel!
            : modelsByProvider[mode]!.first;
        apiKeyConfigured = result['api_key_configured'] == true;
        configuredProviders = ((result['configured_providers'] as List?) ?? const [])
            .map((item) => item.toString())
            .toSet();
        message = '配置已同步';
      });
    } catch (_) {
      if (mounted) setState(() => message = '无法读取后端 AI 配置');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _save() async {
    if (!widget.bridgeConnected) {
      setState(() => message = '请先连接小车');
      return;
    }
    setState(() {
      loading = true;
      message = '正在保存...';
    });
    try {
      final result = await _request(
        'POST',
        body: {
          'mode': mode,
          'model': model,
          if (apiKeyController.text.trim().isNotEmpty)
            'api_key': apiKeyController.text.trim(),
          'clear_api_key': false,
        },
      );
      if (!mounted) return;
      setState(() {
        apiKeyConfigured = result['api_key_configured'] == true;
        configuredProviders = ((result['configured_providers'] as List?) ?? const [])
            .map((item) => item.toString())
            .toSet();
        apiKeyController.clear();
        message = 'AI 配置已保存';
      });
    } catch (_) {
      if (mounted) setState(() => message = '保存失败，请检查后端连接');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }


  Future<void> _clearApiKey() async {
    if (!widget.bridgeConnected) {
      setState(() => message = '请先连接小车');
      return;
    }
    setState(() => loading = true);
    try {
      final result = await _request(
        'POST',
        body: {
          'mode': mode,
          'model': model,
          'clear_api_key': true,
        },
      );
      if (!mounted) return;
      setState(() {
        apiKeyConfigured = result['api_key_configured'] == true;
        configuredProviders = ((result['configured_providers'] as List?) ?? const [])
            .map((item) => item.toString())
            .toSet();
        apiKeyController.clear();
        message = 'API Key 已清除';
      });
    } catch (_) {
      if (mounted) setState(() => message = '清除失败，请检查后端连接');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _testConnection() async {
    if (!widget.bridgeConnected) {
      setState(() => message = '请先连接小车');
      return;
    }
    setState(() {
      loading = true;
      message = '正在测试 AI 服务...';
    });
    try {
      final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
      final request = await client.postUrl(
        Uri.parse('http://${widget.device.ip}:${widget.device.port}/api/agent/test'),
      );
      request.headers.contentType = ContentType.json;
      final response = await request.close().timeout(const Duration(seconds: 18));
      final result = jsonDecode(await utf8.decoder.bind(response).join());
      client.close(force: true);
      if (!mounted) return;
      setState(() => message = result is Map
          ? result['message']?.toString() ?? '测试完成'
          : 'AI 服务响应无效');
    } catch (_) {
      if (mounted) setState(() => message = '测试失败，请检查网络和后端');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cloudProvider = mode != 'local';
    final serviceReady = !cloudProvider || apiKeyConfigured;
    final availableModels = modelsByProvider[mode]!;
    return _Panel(
      title: 'AI 服务',
      trailing: _StatusChip(
        text: serviceReady ? '可用' : '缺少 API Key',
        color: serviceReady ? const Color(0xff22c55e) : const Color(0xfff59e0b),
      ),
      child: Column(
        children: [
          DropdownButtonFormField<String>(
            key: ValueKey('agent-mode-$mode'),
            initialValue: mode,
            decoration: _inputDecoration('AI 类型', Icons.psychology_rounded),
            items: providerLabels.entries
                .map(
                  (entry) => DropdownMenuItem(
                    value: entry.key,
                    child: Text(
                      configuredProviders.contains(entry.key)
                          ? '${entry.value}  ·  已配置'
                          : entry.value,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                )
                .toList(),
            onChanged: loading
                ? null
                : (value) => setState(() {
                    mode = value ?? mode;
                    model = modelsByProvider[mode]!.first;
                    apiKeyConfigured = configuredProviders.contains(mode);
                    apiKeyController.clear();
                    message = mode == 'local' ? '本地模式无需密钥' : '请选择模型并保存配置';
                  }),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            key: ValueKey('agent-model-$model-$mode'),
            initialValue: availableModels.contains(model) ? model : availableModels.first,
            decoration: _inputDecoration('模型', Icons.memory_rounded),
            items: availableModels
                .map((item) => DropdownMenuItem(value: item, child: Text(item)))
                .toList(),
            onChanged: !loading
                ? (value) => setState(() => model = value ?? model)
                : null,
          ),
          const SizedBox(height: 10),
          if (cloudProvider) ...[
            TextField(
              controller: apiKeyController,
              obscureText: !showApiKey,
              enableSuggestions: false,
              autocorrect: false,
              decoration: _inputDecoration(
                apiKeyConfigured ? 'API Key（已配置，留空则保持）' : 'API Key',
                Icons.key_rounded,
              ).copyWith(
                suffixIcon: IconButton(
                  tooltip: showApiKey ? '隐藏 API Key' : '显示 API Key',
                  onPressed: () => setState(() => showApiKey = !showApiKey),
                  icon: Icon(showApiKey ? Icons.visibility_off : Icons.visibility),
                ),
              ),
            ),
            const SizedBox(height: 8),
            _ConfigRow('密钥状态', apiKeyConfigured ? '已安全保存在小车' : '未配置'),
          ],
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              message,
              style: const TextStyle(color: Color(0xff94a3b8)),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: loading ? null : _testConnection,
                  icon: const Icon(Icons.wifi_tethering_rounded),
                  label: const Text('测试连接'),
                ),
              ),
              if (cloudProvider && apiKeyConfigured) ...[
                const SizedBox(width: 10),
                IconButton.outlined(
                  tooltip: '清除 API Key',
                  onPressed: loading ? null : _clearApiKey,
                  icon: const Icon(Icons.delete_outline_rounded),
                ),
              ],
            ],
          ),
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: loading ? null : _save,
              icon: loading
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.save_rounded),
              label: const Text('保存 AI 配置'),
            ),
          ),
        ],
      ),
    );
  }
}

// -----------------------------------------------------------------------------
// 可复用界面组件
// -----------------------------------------------------------------------------

/// 紧凑的当前设备摘要行。
class _CompactDeviceRow extends StatelessWidget {
  const _CompactDeviceRow({required this.device});

  final RoverDevice device;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 42,
          height: 42,
          decoration: BoxDecoration(
            color: const Color(0xff172033),
            borderRadius: BorderRadius.circular(14),
          ),
          child: const Icon(
            Icons.precision_manufacturing_rounded,
            color: Color(0xff60a5fa),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                device.name,
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 2),
              Text(
                device.bridgeUrl,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: Color(0xff94a3b8), fontSize: 12),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 首页遥测指标条。所有值均来自后端状态，未上报时显示未知状态。
class _DriveStatusPanel extends StatelessWidget {
  const _DriveStatusPanel({
    required this.transport,
    required this.deviceConnected,
    required this.motorDriverReady,
    required this.controlReady,
  });

  final String transport;
  final bool deviceConnected;
  final bool motorDriverReady;
  final bool controlReady;

  @override
  Widget build(BuildContext context) {
    final ready = controlReady;
    return _Panel(
      title: '底盘驱动',
      trailing: _StatusChip(
        text: ready ? '可控制' : '未就绪',
        color: ready ? const Color(0xff22c55e) : const Color(0xfff59e0b),
      ),
      child: Column(
        children: [
          _ConfigRow('通信方式', transport.toUpperCase()),
          _ConfigRow('电机型号', 'M1505'),
          _ConfigRow('USB2CAN', deviceConnected ? '已识别' : '未识别'),
          _ConfigRow('电机节点', motorDriverReady ? '运行中' : '未运行'),
        ],
      ),
    );
  }
}

class _MetricStrip extends StatelessWidget {
  const _MetricStrip({
    required this.controlReady,
    required this.linearVelocity,
    required this.localizationAccuracyMm,
    required this.localizationReady,
    required this.printerStatus,
  });

  final bool controlReady;
  final double? linearVelocity;
  final double? localizationAccuracyMm;
  final bool localizationReady;
  final String printerStatus;

  @override
  Widget build(BuildContext context) {
    final localizationText = localizationAccuracyMm != null
        ? '±${localizationAccuracyMm!.toStringAsFixed(0)}mm'
        : localizationReady
        ? '已定位'
        : '未定位';
    return Row(
      children: [
        Expanded(
          child: _MiniMetric(label: '底盘', value: controlReady ? '已就绪' : '未就绪'),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _MiniMetric(
            label: '速度',
            value: linearVelocity == null
                ? '--'
                : '${linearVelocity!.toStringAsFixed(2)}m/s',
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _MiniMetric(label: '定位', value: localizationText),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _MiniMetric(label: '喷码', value: printerStatus),
        ),
      ],
    );
  }
}

/// 显示后端实际上报的机器人位姿。
/// 没有 `/robot_pose` 数据时不绘制虚构地图或路径。
class _RealtimeRobotView extends StatelessWidget {
  const _RealtimeRobotView({required this.rosAvailable, required this.pose});

  final bool rosAvailable;
  final Map<String, dynamic> pose;

  String _number(String key) {
    final value = pose[key];
    return value is num ? value.toStringAsFixed(2) : '--';
  }

  @override
  Widget build(BuildContext context) {
    if (pose.isEmpty) {
      return SizedBox(
        height: 178,
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                rosAvailable
                    ? Icons.location_searching_rounded
                    : Icons.hub_outlined,
                size: 38,
                color: const Color(0xff64748b),
              ),
              const SizedBox(height: 12),
              Text(
                rosAvailable ? '等待定位数据' : 'ROS2 节点未就绪',
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 6),
              const Text(
                '收到 /robot_pose 后将显示实时位姿',
                style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
              ),
            ],
          ),
        ),
      );
    }

    return SizedBox(
      height: 178,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(
            Icons.my_location_rounded,
            size: 36,
            color: Color(0xff22c55e),
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: _PoseValue(label: 'X', value: _number('x')),
              ),
              Expanded(
                child: _PoseValue(label: 'Y', value: _number('y')),
              ),
              Expanded(
                child: _PoseValue(label: '航向', value: _number('theta')),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PoseValue extends StatelessWidget {
  const _PoseValue({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(label, style: const TextStyle(color: Color(0xff94a3b8))),
        const SizedBox(height: 4),
        Text(
          value,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
        ),
      ],
    );
  }
}

/// 单个紧凑遥测值卡片。
class _MiniMetric extends StatelessWidget {
  const _MiniMetric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 74,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xff111827),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xff22304a)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: const TextStyle(color: Color(0xff94a3b8), fontSize: 12),
          ),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              value,
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900),
            ),
          ),
        ],
      ),
    );
  }
}

/// 设备列表项，显示小车配置并允许切换连接。
class _DeviceTile extends StatelessWidget {
  const _DeviceTile({required this.device, required this.onConnect});

  final RoverDevice device;
  final VoidCallback onConnect;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: const Color(0xff101d33),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(
          color: device.connected
              ? const Color(0xff22c55e)
              : const Color(0xff22304a),
        ),
      ),
      child: ListTile(
        leading: Icon(
          Icons.precision_manufacturing_rounded,
          color: device.connected
              ? const Color(0xff22c55e)
              : const Color(0xff60a5fa),
        ),
        title: Text(device.name),
        subtitle: Text(
          '${device.type} · ${device.bridgeUrl} · Domain ${device.domainId}',
        ),
        trailing: device.connected
            ? const _StatusChip(text: '已连接', color: Color(0xff22c55e))
            : TextButton(onPressed: onConnect, child: const Text('连接')),
      ),
    );
  }
}

/// 主文件内使用的标准内容面板，统一标题、边框和内边距。
class _Panel extends StatelessWidget {
  const _Panel({required this.title, required this.child, this.trailing});

  final String title;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xff111827),
        border: Border.all(color: const Color(0xff22304a)),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              ?trailing,
            ],
          ),
          const SizedBox(height: 12),
          child,
        ],
      ),
    );
  }
}

/// 大型指标卡，用于航点数、路径长度等统计值。
class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.title,
    required this.value,
    required this.note,
    required this.icon,
  });

  final String title;
  final String value;
  final String note;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 96,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xff111827),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xff22304a)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 20, color: const Color(0xff60a5fa)),
              const SizedBox(width: 8),
              Text(title, style: const TextStyle(color: Color(0xff94a3b8))),
            ],
          ),
          const Spacer(),
          Text(
            value,
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
          ),
          Text(
            note,
            style: const TextStyle(color: Color(0xff64748b), fontSize: 12),
          ),
        ],
      ),
    );
  }
}

/// 状态标签，文字和颜色由上层业务状态决定。
class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.text, required this.color});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.45)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 7,
            height: 7,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(
            text,
            style: TextStyle(
              color: color,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

/// 任务流程中的单个步骤和完成状态。
class _MissionStep extends StatelessWidget {
  const _MissionStep({required this.title, required this.done});

  final String title;
  final bool done;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Icon(
            done
                ? Icons.check_circle_rounded
                : Icons.radio_button_unchecked_rounded,
            color: done ? const Color(0xff22c55e) : const Color(0xff64748b),
          ),
          const SizedBox(width: 10),
          Expanded(child: Text(title)),
        ],
      ),
    );
  }
}

/// 方向控制区，将按钮点击映射为线速度和角速度。
class _Joystick extends StatelessWidget {
  const _Joystick();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Container(
        width: 190,
        height: 190,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: const Color(0xff101d33),
          border: Border.all(color: const Color(0xff22304a), width: 2),
        ),
        child: Center(
          child: Container(
            width: 82,
            height: 82,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: const LinearGradient(
                colors: [Color(0xff2563eb), Color(0xff22c55e)],
              ),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xff2563eb).withValues(alpha: 0.35),
                  blurRadius: 26,
                ),
              ],
            ),
            child: const Icon(Icons.open_with_rounded, size: 32),
          ),
        ),
      ),
    );
  }
}

/// 带图标的通用指令按钮。
class _DriveCommandButton extends StatefulWidget {
  const _DriveCommandButton({
    required this.label,
    required this.icon,
    required this.onStart,
    required this.onStop,
  });

  final String label;
  final IconData icon;
  final VoidCallback onStart;
  final VoidCallback onStop;

  @override
  State<_DriveCommandButton> createState() => _DriveCommandButtonState();
}

class _DriveCommandButtonState extends State<_DriveCommandButton> {
  Timer? _repeatTimer;

  void _start() {
    _repeatTimer?.cancel();
    widget.onStart();
    _repeatTimer = Timer.periodic(
      const Duration(milliseconds: 100),
      (_) => widget.onStart(),
    );
  }

  void _stop() {
    _repeatTimer?.cancel();
    _repeatTimer = null;
    widget.onStop();
  }

  @override
  void dispose() {
    _repeatTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Listener(
      onPointerDown: (_) => _start(),
      onPointerUp: (_) => _stop(),
      onPointerCancel: (_) => _stop(),
      child: OutlinedButton.icon(
        onPressed: () {},
        icon: Icon(widget.icon),
        label: Text(widget.label),
      ),
    );
  }
}

class _CommandButton extends StatelessWidget {
  const _CommandButton({
    required this.label,
    required this.icon,
    required this.onPressed,
  });

  final String label;
  final IconData icon;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: onPressed,
      icon: Icon(icon),
      label: Text(label),
    );
  }
}

/// 任务列表项，展示业务名称、ROS2 模块名和运行状态。
class _TaskTile extends StatelessWidget {
  const _TaskTile(this.title, this.subtitle, this.done);

  final String title;
  final String subtitle;
  final bool done;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(
        done ? Icons.task_alt_rounded : Icons.pending_rounded,
        color: done ? const Color(0xff22c55e) : const Color(0xfff59e0b),
      ),
      title: Text(title),
      subtitle: Text(subtitle),
    );
  }
}

/// ROS2 Topic 名称与消息类型说明行。
class _TopicRow extends StatelessWidget {
  const _TopicRow(this.topic, this.type);

  final String topic;
  final String type;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.topic_rounded, color: Color(0xff60a5fa)),
      title: Text(topic),
      subtitle: Text(type),
    );
  }
}

/// 设置页中的键值配置行。
class _ConfigRow extends StatelessWidget {
  const _ConfigRow(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: const TextStyle(color: Color(0xff94a3b8)),
            ),
          ),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    );
  }
}

/// 添加设备表单使用的统一输入框。
class _Field extends StatelessWidget {
  const _Field({
    required this.label,
    required this.controller,
    required this.icon,
    this.keyboardType,
  });

  final String label;
  final TextEditingController controller;
  final IconData icon;
  final TextInputType? keyboardType;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextField(
        controller: controller,
        keyboardType: keyboardType,
        decoration: _inputDecoration(label, icon),
        onChanged: (_) => (context as Element).markNeedsBuild(),
      ),
    );
  }
}

InputDecoration _inputDecoration(String label, IconData icon) {
  return InputDecoration(
    labelText: label,
    prefixIcon: Icon(icon),
    filled: true,
    fillColor: const Color(0xff101d33),
    border: OutlineInputBorder(borderRadius: BorderRadius.circular(16)),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(16),
      borderSide: const BorderSide(color: Color(0xff22304a)),
    ),
  );
}

// -----------------------------------------------------------------------------
// ROS2 栅格地图与规划路径绘制
// -----------------------------------------------------------------------------

/// 数据源严格对应 xline_path_planner 的 foxglove/grid_map、
/// foxglove/planned_paths，以及 xline_localization 的 /robot_pose。
class _MapPainter extends CustomPainter {
  _MapPainter({
    required this.lineRunning,
    required this.gridMap,
    required this.plannedPaths,
    required this.robotPose,
  });

  final bool lineRunning;
  final Map<String, dynamic> gridMap;
  final List<Map<String, dynamic>> plannedPaths;
  final Map<String, dynamic> robotPose;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xff07111f),
    );
    final width = (gridMap['width'] as num?)?.toInt() ?? 0;
    final height = (gridMap['height'] as num?)?.toInt() ?? 0;
    final resolution = (gridMap['resolution'] as num?)?.toDouble() ?? 0;
    final originX = (gridMap['origin_x'] as num?)?.toDouble() ?? 0;
    final originY = (gridMap['origin_y'] as num?)?.toDouble() ?? 0;
    if (width <= 0 || height <= 0 || resolution <= 0) return;

    const margin = 24.0;
    final scale = (size.width - margin * 2) / (width * resolution);
    final scaleY = (size.height - margin * 2) / (height * resolution);
    final pixelsPerMeter = scale < scaleY ? scale : scaleY;
    final mapWidth = width * resolution * pixelsPerMeter;
    final mapHeight = height * resolution * pixelsPerMeter;
    final left = (size.width - mapWidth) / 2;
    final top = (size.height - mapHeight) / 2;
    final cellW = mapWidth / width;
    final cellH = mapHeight / height;

    Offset world(double x, double y) => Offset(
      left + (x - originX) * pixelsPerMeter,
      top + mapHeight - (y - originY) * pixelsPerMeter,
    );

    for (final raw in gridMap['runs'] as List? ?? const []) {
      if (raw is! List || raw.length < 3 || (raw[2] as num).toInt() < 50) {
        continue;
      }
      var index = (raw[0] as num).toInt();
      var remaining = (raw[1] as num).toInt();
      while (remaining > 0) {
        final row = index ~/ width;
        final column = index % width;
        final count = remaining < width - column ? remaining : width - column;
        canvas.drawRect(
          Rect.fromLTWH(
            left + column * cellW,
            top + mapHeight - (row + 1) * cellH,
            count * cellW + .5,
            cellH + .5,
          ),
          Paint()..color = const Color(0xff475569),
        );
        index += count;
        remaining -= count;
      }
    }

    for (final segment in plannedPaths) {
      final points = segment['points'] as List? ?? const [];
      if (points.length < 2) continue;
      final path = Path();
      for (var i = 0; i < points.length; i++) {
        final point = points[i] as List;
        final offset = world(
          (point[0] as num).toDouble(),
          (point[1] as num).toDouble(),
        );
        i == 0
            ? path.moveTo(offset.dx, offset.dy)
            : path.lineTo(offset.dx, offset.dy);
      }
      final drawing =
          segment['namespace'] == 'path_lines' &&
          (((segment['color'] as Map?)?['b'] as num?)?.toDouble() ?? 0) > .8;
      canvas.drawPath(
        path,
        Paint()
          ..color = drawing
              ? (lineRunning
                    ? const Color(0xff22c55e)
                    : const Color(0xff3b82f6))
              : const Color(0xfffacc15)
          ..style = PaintingStyle.stroke
          ..strokeCap = StrokeCap.round
          ..strokeJoin = StrokeJoin.round
          ..strokeWidth = drawing ? 3.5 : 2.5,
      );
    }

    final poseFrame = robotPose['frame_id']?.toString();
    final mapFrame = gridMap['frame_id']?.toString();
    if (robotPose.isNotEmpty && (poseFrame == null || poseFrame == mapFrame)) {
      final rover = world(
        (robotPose['x'] as num).toDouble(),
        (robotPose['y'] as num).toDouble(),
      );
      final theta = (robotPose['theta'] as num?)?.toDouble() ?? 0;
      canvas.drawCircle(rover, 13, Paint()..color = const Color(0xff22c55e));
      canvas.drawCircle(rover, 21, Paint()..color = const Color(0x3322c55e));
      canvas.drawLine(
        rover,
        rover + Offset(22 * math.cos(theta), -22 * math.sin(theta)),
        Paint()
          ..color = Colors.white
          ..strokeWidth = 3
          ..strokeCap = StrokeCap.round,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _MapPainter oldDelegate) =>
      oldDelegate.lineRunning != lineRunning ||
      oldDelegate.gridMap != gridMap ||
      oldDelegate.plannedPaths != plannedPaths ||
      oldDelegate.robotPose != robotPose;
}

/// 底部导航项的简单数据模型。
class _TabItem {
  const _TabItem(this.label, this.icon);

  final String label;
  final IconData icon;
}
