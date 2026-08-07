// XLine 划线小车 App 的当前主实现文件。
//
// 本文件集中了应用入口、页面切换、WebSocket 通信、业务页面、
// 通用组件和地图绘制。修改功能前可根据下方的分区注释定位。
import 'dart:async';
import 'dart:convert';
import 'dart:io';

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
  double speed = 0.34;
  double lineWidth = 80;
  bool rosAvailable = false;
  bool backendOnline = false;
  bool controlReady = false;
  bool missionNodesReady = false;
  int? batteryPercent;
  double? linearVelocity;
  double? localizationAccuracyMm;
  Map<String, dynamic> robotPose = const {};
  Map<String, dynamic> reflectorPosition = const {};
  String? printerStatus;
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
      printerStatus != null;

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
          onToggle: _toggleMission,
          onLnCommand: _sendLnCommand,
        );
      case 2:
        return _SettingsPage(
          device: activeDevice,
          lineWidth: lineWidth,
          onLineWidthChanged: (value) => setState(() => lineWidth = value),
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
          child: _MapPage(lineRunning: lineRunning),
        );
      case 2:
        return _HomeModulePage(
          title: '手动控制',
          onBack: () => setState(() => homeModule = 0),
          child: _ControlPage(
            speed: speed,
            printerEnabled: printerEnabled,
            onSpeedChanged: (value) => setState(() => speed = value),
            onPrinterChanged: (value) => setState(() => printerEnabled = value),
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
          batteryPercent: batteryPercent,
          linearVelocity: linearVelocity,
          localizationAccuracyMm: localizationAccuracyMm,
          robotPose: robotPose,
          localizationReady: localizationReady,
          printerStatus: printerStatus,
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
        missionNodesReady = status['mission_nodes_ready'] == true;
        batteryPercent = (status['battery'] as num?)?.round();
        linearVelocity = (status['linear_velocity'] as num?)?.toDouble();
        localizationAccuracyMm = (status['localization_accuracy_mm'] as num?)
            ?.toDouble();
        robotPose = _asStringMap(status['robot_pose']);
        reflectorPosition = _asStringMap(status['reflector_position']);
        final rawPrinter = status['printer_status']?.toString();
        printerStatus =
            rawPrinter == null || rawPrinter.isEmpty || rawPrinter == 'unknown'
            ? null
            : rawPrinter;
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

  /// 连接成功后订阅 [AppConstants.coreTopics] 中的所有话题。
  void _subscribeCoreTopics() {
    for (final topic in AppConstants.coreTopics) {
      _sendBridge(RosMessages.subscribe(topic));
    }
  }

  /// 将线速度和角速度转成 `/cmd_vel` 指令。
  void _sendDriveCommand(double linear, double angular) {
    _sendBridge(RosMessages.cmdVel(linear, angular));
  }

  /// 调用喷码机指令，[action] 例如 `start_print` 或 `stop_print`。
  void _sendPrinterCommand(String action) {
    _sendBridge(RosMessages.printerCommand(action));
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
    setState(() => lineRunning = next);
    _sendBridge(RosMessages.missionControl(next));
    if (next) {
      _sendPrinterCommand('start_print');
    } else {
      _sendPrinterCommand('stop_print');
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
    required this.batteryPercent,
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
  final int? batteryPercent;
  final double? linearVelocity;
  final double? localizationAccuracyMm;
  final Map<String, dynamic> robotPose;
  final bool localizationReady;
  final String? printerStatus;
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
          _MetricStrip(
            batteryPercent: batteryPercent,
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
                  done: lineRunning && printerStatus != null,
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
        const SizedBox(height: 14),
        const _Panel(
          title: '添加方式',
          child: Column(
            children: [
              _InfoRow(
                Icons.edit_location_alt_rounded,
                '手动输入 IP',
                '适合实验室局域网，默认连接 ws://小车IP:8000。',
              ),
              _InfoRow(
                Icons.qr_code_scanner_rounded,
                '扫码绑定',
                '后续可扫描贴在小车上的二维码自动填入配置。',
              ),
              _InfoRow(
                Icons.wifi_find_rounded,
                '局域网发现',
                '后续可通过 mDNS/UDP 广播发现在线小车。',
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
  String type = 'FastAPI Backend';
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
            DropdownButtonFormField<String>(
              initialValue: type,
              decoration: _inputDecoration(
                '连接类型',
                Icons.wifi_tethering_rounded,
              ),
              items: const [
                DropdownMenuItem(
                  value: 'FastAPI Backend',
                  child: Text('FastAPI Backend'),
                ),
                DropdownMenuItem(
                  value: 'Foxglove Bridge',
                  child: Text('Foxglove Bridge'),
                ),
                DropdownMenuItem(
                  value: 'ROS2 Web Bridge',
                  child: Text('ROS2 Web Bridge'),
                ),
                DropdownMenuItem(
                  value: 'Mock Device',
                  child: Text('Mock Device'),
                ),
              ],
              onChanged: (value) => setState(() => type = value ?? type),
            ),
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

  /// 表单内的连接检查。
  /// 当前为 UI 流程检查；若要进行真实网络测试，应在此请求 `/health`。
  Future<void> _testConnection() async {
    setState(() {
      testing = true;
      testStatus = '正在测试 Foxglove / ROS2 Bridge...';
    });
    await Future<void>.delayed(const Duration(milliseconds: 900));
    if (!mounted) return;
    setState(() {
      testing = false;
      testStatus = ipController.text.trim().isEmpty
          ? '失败：请填写机器人 IP'
          : '测试通过：可保存设备';
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

/// 地图与划线路径页。当前由 [_MapPainter] 绘制演示地图。
class _MapPage extends StatelessWidget {
  const _MapPage({required this.lineRunning});

  final bool lineRunning;

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const ValueKey('map'),
      padding: const EdgeInsets.all(14),
      children: [
        _Panel(
          title: '地图与划线路径',
          trailing: const Text(
            'grid_maps/site_a.yaml',
            style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
          ),
          child: SizedBox(
            height: 390,
            child: CustomPaint(painter: _MapPainter(lineRunning: lineRunning)),
          ),
        ),
        const SizedBox(height: 14),
        const Row(
          children: [
            Expanded(
              child: _MetricCard(
                title: '航点',
                value: '12',
                note: 'A* 路径',
                icon: Icons.timeline_rounded,
              ),
            ),
            SizedBox(width: 12),
            Expanded(
              child: _MetricCard(
                title: '剩余',
                value: '18.6m',
                note: '划线长度',
                icon: Icons.straighten_rounded,
              ),
            ),
          ],
        ),
        const SizedBox(height: 14),
        const _LogPanel(),
      ],
    );
  }
}

/// 手动控制页：速度调节、方向控制和喷码机快捷指令。
class _ControlPage extends StatelessWidget {
  const _ControlPage({
    required this.speed,
    required this.onSpeedChanged,
    required this.printerEnabled,
    required this.onPrinterChanged,
    required this.onDriveCommand,
    required this.onPrinterCommand,
  });

  final double speed;
  final ValueChanged<double> onSpeedChanged;
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
            '/cmd_vel',
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
                  _CommandButton(
                    label: '前进',
                    icon: Icons.arrow_upward_rounded,
                    onPressed: () => onDriveCommand(speed, 0),
                  ),
                  _CommandButton(
                    label: '左转',
                    icon: Icons.turn_left_rounded,
                    onPressed: () => onDriveCommand(0, speed),
                  ),
                  _CommandButton(
                    label: '停止',
                    icon: Icons.stop_rounded,
                    onPressed: () => onDriveCommand(0, 0),
                  ),
                  _CommandButton(
                    label: '右转',
                    icon: Icons.turn_right_rounded,
                    onPressed: () => onDriveCommand(0, -speed),
                  ),
                  _CommandButton(
                    label: '后退',
                    icon: Icons.arrow_downward_rounded,
                    onPressed: () => onDriveCommand(-speed, 0),
                  ),
                ],
              ),
              const SizedBox(height: 18),
              Row(
                children: [
                  const Text('速度限制'),
                  Expanded(
                    child: Slider(
                      value: speed,
                      min: 0.1,
                      max: 1.2,
                      divisions: 11,
                      label: '${speed.toStringAsFixed(2)} m/s',
                      onChanged: onSpeedChanged,
                    ),
                  ),
                  Text('${speed.toStringAsFixed(2)}m/s'),
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
                    label: '模拟打印',
                    icon: Icons.science_rounded,
                    onPressed: () => onPrinterCommand('simulate'),
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
    required this.onToggle,
    required this.onLnCommand,
  });

  final bool lineRunning;
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
            lineRunning ? '执行中' : '待启动',
            style: const TextStyle(color: Color(0xff94a3b8)),
          ),
          child: Column(
            children: [
              _TaskTile('导入 CAD / DXF 路径', 'cad/line_task_0728.dxf', true),
              _TaskTile('生成划线路径', 'xline_path_planner', true),
              _TaskTile('LN150 定位闭环', '/reflector_position', true),
              _TaskTile('底盘跟随控制', 'xline_base_controller', lineRunning),
              _TaskTile('喷码机同步喷印', 'xline_inkjet_printer', lineRunning),
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
                    lineRunning
                        ? Icons.pause_rounded
                        : Icons.play_arrow_rounded,
                  ),
                  label: Text(lineRunning ? '暂停任务' : '执行任务'),
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
              _TopicRow('/cmd_vel', 'geometry_msgs/Twist'),
            ],
          ),
        ),
      ],
    );
  }
}

/// 设置页：查看当前设备并调整划线宽度等 App 参数。
class _SettingsPage extends StatelessWidget {
  const _SettingsPage({
    required this.device,
    required this.lineWidth,
    required this.onLineWidthChanged,
    required this.onAddDevice,
    required this.bridgeState,
  });

  final RoverDevice device;
  final double lineWidth;
  final ValueChanged<double> onLineWidthChanged;
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
        _Panel(
          title: '划线参数',
          child: Column(
            children: [
              Row(
                children: [
                  const Text('线宽'),
                  Expanded(
                    child: Slider(
                      value: lineWidth,
                      min: 40,
                      max: 160,
                      divisions: 12,
                      label: '${lineWidth.round()} mm',
                      onChanged: onLineWidthChanged,
                    ),
                  ),
                  Text('${lineWidth.round()}mm'),
                ],
              ),
              const _ConfigRow('喷码高度', '≤ 15mm'),
              const _ConfigRow('定位来源', 'LN150 + IMU'),
              const _ConfigRow('控制模式', '自动 / 手动'),
            ],
          ),
        ),
      ],
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
class _MetricStrip extends StatelessWidget {
  const _MetricStrip({
    required this.batteryPercent,
    required this.linearVelocity,
    required this.localizationAccuracyMm,
    required this.localizationReady,
    required this.printerStatus,
  });

  final int? batteryPercent;
  final double? linearVelocity;
  final double? localizationAccuracyMm;
  final bool localizationReady;
  final String? printerStatus;

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
          child: _MiniMetric(
            label: '电量',
            value: batteryPercent == null ? '--' : '$batteryPercent%',
          ),
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
          child: _MiniMetric(label: '喷码', value: printerStatus ?? '未知'),
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

/// 简化的 ROS2 运行日志面板。
class _LogPanel extends StatelessWidget {
  const _LogPanel();

  @override
  Widget build(BuildContext context) {
    return const _Panel(
      title: '运行日志',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _LogLine('12:01', 'LN150 初始化完成，开始自动追踪。'),
          _LogLine('12:02', '加载 CAD 任务，生成 12 个航点。'),
          _LogLine('12:03', '定位融合启动，发布 /robot_pose。'),
          _LogLine('12:05', '等待 start_print 指令。'),
        ],
      ),
    );
  }
}

/// 一条带颜色状态点的日志。
class _LogLine extends StatelessWidget {
  const _LogLine(this.time, this.text);

  final String time;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Row(
        children: [
          Text(
            time,
            style: const TextStyle(
              color: Color(0xff60a5fa),
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(text, style: const TextStyle(color: Color(0xffcbd5e1))),
          ),
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

/// 带图标、标题和说明的信息行。
class _InfoRow extends StatelessWidget {
  const _InfoRow(this.icon, this.title, this.desc);

  final IconData icon;
  final String title;
  final String desc;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(icon, color: const Color(0xff60a5fa)),
      title: Text(title),
      subtitle: Text(desc),
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
// Canvas 地图与路径演示绘制
// -----------------------------------------------------------------------------

/// 绘制完整地图、网格、路径、小车和终点。
/// 要接入真实地图时，应将路径点、位姿和地图数据作为构造参数传入。
class _MapPainter extends CustomPainter {
  _MapPainter({required this.lineRunning});

  final bool lineRunning;

  @override
  void paint(Canvas canvas, Size size) {
    final gridPaint = Paint()
      ..color = const Color(0xff22304a)
      ..strokeWidth = 1;
    for (double x = 0; x < size.width; x += 28) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), gridPaint);
    }
    for (double y = 0; y < size.height; y += 28) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), gridPaint);
    }

    final obstaclePaint = Paint()..color = const Color(0x33ef4444);
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(size.width * .12, size.height * .18, 92, 54),
        const Radius.circular(10),
      ),
      obstaclePaint,
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(size.width * .58, size.height * .26, 110, 70),
        const Radius.circular(10),
      ),
      obstaclePaint,
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(size.width * .34, size.height * .68, 120, 46),
        const Radius.circular(10),
      ),
      obstaclePaint,
    );

    final path = Path()
      ..moveTo(size.width * .12, size.height * .82)
      ..cubicTo(
        size.width * .26,
        size.height * .72,
        size.width * .30,
        size.height * .52,
        size.width * .46,
        size.height * .52,
      )
      ..cubicTo(
        size.width * .62,
        size.height * .52,
        size.width * .58,
        size.height * .18,
        size.width * .86,
        size.height * .14,
      );

    canvas.drawPath(
      path,
      Paint()
        ..color = const Color(0xff60a5fa)
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeWidth = 5,
    );

    final markPaint = Paint()
      ..color = lineRunning ? const Color(0xfff59e0b) : const Color(0xff22c55e)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3;
    for (int i = 0; i < 7; i++) {
      final y = size.height * .30 + i * 20;
      canvas.drawLine(
        Offset(size.width * .13, y),
        Offset(size.width * .38, y),
        markPaint,
      );
    }

    final rover = Offset(size.width * .44, size.height * .52);
    canvas.drawCircle(rover, 15, Paint()..color = const Color(0xff22c55e));
    canvas.drawCircle(rover, 27, Paint()..color = const Color(0x3322c55e));
    canvas.drawCircle(
      Offset(size.width * .86, size.height * .14),
      10,
      Paint()..color = const Color(0xfff59e0b),
    );
  }

  @override
  bool shouldRepaint(covariant _MapPainter oldDelegate) =>
      oldDelegate.lineRunning != lineRunning;
}

/// 底部导航项的简单数据模型。
class _TabItem {
  const _TabItem(this.label, this.icon);

  final String label;
  final IconData icon;
}
