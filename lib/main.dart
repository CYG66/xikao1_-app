import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

import 'auth_transport.dart';
import 'control_lease.dart';

void main() => runApp(const XLineCarApp());

/// Single source of truth for whether authenticated control commands may leave
/// the App.  A WebSocket connection alone is not enough: the backend must have
/// granted a control lease, and neither a local auth error nor a lost lease may
/// be present.
bool controlCommandsAllowed(
  BridgeState state,
  String? authError, {
  String? controlError,
  ControlLeaseState lease = ControlLeaseState.idle,
}) {
  return state == BridgeState.connected &&
      authError == null &&
      controlError == null &&
      lease == ControlLeaseState.granted;
}

class XLineCarApp extends StatelessWidget {
  const XLineCarApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'XLine Rover',
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

class RoverDevice {
  const RoverDevice({
    required this.name,
    required this.ip,
    required this.port,
    required this.domainId,
    required this.type,
    required this.connected,
    this.secure = true,
  });

  final String name;
  final String ip;
  final int port;
  final int domainId;
  final String type;
  final bool connected;
  final bool secure;

  String get bridgeUrl => '${secure ? 'wss' : 'ws'}://$ip:$port';
}

enum BridgeState { disconnected, connecting, connected, failed }

extension BridgeStateLabel on BridgeState {
  String get label {
    switch (this) {
      case BridgeState.connecting:
        return '连接中';
      case BridgeState.connected:
        return '已连接';
      case BridgeState.failed:
        return '连接失败';
      case BridgeState.disconnected:
        return '未连接';
    }
  }

  Color get color {
    switch (this) {
      case BridgeState.connected:
        return const Color(0xff22c55e);
      case BridgeState.connecting:
        return const Color(0xfff59e0b);
      case BridgeState.failed:
        return const Color(0xffef4444);
      case BridgeState.disconnected:
        return const Color(0xff64748b);
    }
  }
}

class RoverHomePage extends StatefulWidget {
  const RoverHomePage({super.key});

  @override
  State<RoverHomePage> createState() => _RoverHomePageState();
}

class _RoverHomePageState extends State<RoverHomePage> {
  int tabIndex = 0;
  bool lineRunning = false;
  bool printerEnabled = true;
  double speed = 0.34;
  double lineWidth = 80;
  String connectionMessage = '已加载默认设备，等待连接测试';
  BridgeState bridgeState = BridgeState.disconnected;
  WebSocket? socket;
  StreamSubscription? socketSub;
  AuthTransport? transport;
  String controlToken = '';
  String? authError;
  String? controlError;
  bool _closingIntentionally = false;
  bool _lockInProgress = false;
  int _connectionGeneration = 0;
  late final ControlLeaseManager _lease;
  Timer? _heartbeatTimer;
  final TextEditingController tokenController = TextEditingController();
  final List<String> bridgeLogs = ['App 已就绪，可连接小车端 ROS2 Bridge'];

  bool get controlReady => controlCommandsAllowed(
    bridgeState,
    authError,
    controlError: controlError,
    lease: _lease.state,
  );

  String? get lockReason => controlError ?? authError;

  final List<RoverDevice> devices = [
    const RoverDevice(
      name: 'XLine-Car-01',
      ip: '192.168.31.42',
      port: 8000,
      domainId: 0,
      type: 'FastAPI ROS Bridge',
      connected: true,
      secure: true,
    ),
  ];

  RoverDevice get activeDevice {
    return devices.firstWhere(
      (device) => device.connected,
      orElse: () => devices.first,
    );
  }

  @override
  void initState() {
    super.initState();
    _lease = ControlLeaseManager(
      send: _sendLeasePayload,
      onLock: (reason) => unawaited(_lockControl(reason)),
    );
  }

  @override
  void dispose() {
    _heartbeatTimer?.cancel();
    _lease.release();
    _lease.dispose();
    socketSub?.cancel();
    socket?.close();
    tokenController.dispose();
    transport?.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tabs = const [
      _TabItem('监控', Icons.dashboard_rounded),
      _TabItem('地图', Icons.map_rounded),
      _TabItem('控制', Icons.gamepad_rounded),
      _TabItem('任务', Icons.route_rounded),
      _TabItem('设备', Icons.devices_other_rounded),
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
              authError: authError,
              lockReason: lockReason,
            ),
            if (lockReason != null) AuthStatusBanner(message: lockReason!),
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
        onDestinationSelected: (value) => setState(() => tabIndex = value),
        destinations: [
          for (final tab in tabs)
            NavigationDestination(icon: Icon(tab.icon), label: tab.label),
        ],
      ),
    );
  }

  Widget _buildPage() {
    switch (tabIndex) {
      case 1:
        return _MapPage(lineRunning: lineRunning);
      case 2:
        return _ControlPage(
          speed: speed,
          printerEnabled: printerEnabled,
          onSpeedChanged: (value) => setState(() => speed = value),
          onPrinterChanged: (value) => setState(() => printerEnabled = value),
          onDriveCommand: _sendDriveCommand,
          onPrinterCommand: _sendPrinterCommand,
        );
      case 3:
        return _MissionPage(
          lineRunning: lineRunning,
          onToggle: _toggleMission,
          onLnCommand: _sendLnCommand,
        );
      case 4:
        return _DevicePage(
          devices: devices,
          message: connectionMessage,
          bridgeState: bridgeState,
          logs: bridgeLogs,
          tokenController: tokenController,
          authError: authError,
          controlError: controlError,
          controlReady: controlReady,
          onTokenChanged: _updateControlToken,
          onAddDevice: _openAddDeviceSheet,
          onConnect: _connectDevice,
          onTestActive: _connectActiveDevice,
          onDisconnect: _disconnectBridge,
        );
      case 5:
        return _SettingsPage(
          device: activeDevice,
          lineWidth: lineWidth,
          onLineWidthChanged: (value) => setState(() => lineWidth = value),
          onAddDevice: _openAddDeviceSheet,
          bridgeState: bridgeState,
          authError: authError,
          hasToken: controlToken.isNotEmpty,
        );
      default:
        return _DashboardPage(
          device: activeDevice,
          lineRunning: lineRunning,
          bridgeState: bridgeState,
          onStartMission: _toggleMission,
          onAddDevice: _openAddDeviceSheet,
          onConnect: _connectActiveDevice,
        );
    }
  }

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
          secure: devices[index].secure,
        );
      }
      devices.add(device);
      connectionMessage = '已添加并连接 ${device.name}';
      tabIndex = 4;
    });
    unawaited(_connectActiveDevice());
  }

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
          secure: device.secure,
        );
      }
      connectionMessage = '已切换到 ${devices[selectedIndex].name}';
    });
    unawaited(_connectActiveDevice());
  }

  Future<void> _connectActiveDevice() async {
    final generation = ++_connectionGeneration;
    final token = tokenController.text.trim();
    if (token.isEmpty) {
      _heartbeatTimer?.cancel();
      _lease.reset();
      await socketSub?.cancel();
      await socket?.close();
      if (!mounted) return;
      setState(() {
        socket = null;
        socketSub = null;
        bridgeState = BridgeState.failed;
        authError = '未配置访问令牌，已停止控制';
        controlError = null;
        connectionMessage = '访问令牌为空，未发起连接';
        lineRunning = false;
        _addLog('blocked connect: missing token');
      });
      return;
    }

    _heartbeatTimer?.cancel();
    _lease.reset();
    await socketSub?.cancel();
    await socket?.close();
    final nextTransport = AuthTransport(
      host: activeDevice.ip,
      port: activeDevice.port,
      token: token,
      secure: activeDevice.secure,
    );
    transport?.close();
    transport = nextTransport;
    controlToken = token;
    _closingIntentionally = false;
    setState(() {
      bridgeState = BridgeState.connecting;
      authError = null;
      controlError = null;
      connectionMessage = '正在认证并连接 ${activeDevice.name}';
      _addLog(
        'authenticate ${activeDevice.ip}:${activeDevice.port} '
        '(${activeDevice.secure ? 'TLS' : 'loopback plaintext'})',
      );
    });

    try {
      // Authenticate over HTTP before opening the control WebSocket.  This
      // makes a bad/expired/forbidden token fail with a server response rather
      // than a generic socket error.
      await nextTransport.getJson('/api/status');
      if (!mounted || generation != _connectionGeneration) {
        if (transport == nextTransport) transport = null;
        nextTransport.close();
        return;
      }
      final ws = await nextTransport.connectWebSocket();
      if (!mounted || generation != _connectionGeneration) {
        if (transport == nextTransport) transport = null;
        await ws.close(1000, 'stale connection');
        nextTransport.close();
        return;
      }
      socket = ws;
      socketSub = ws.listen(
        _handleBridgeMessage,
        onDone: () {
          if (!mounted || socket != ws) return;
          _heartbeatTimer?.cancel();
          final failure = AuthTransport.fromClose(ws.closeCode, ws.closeReason);
          final leaseReason = _lease.reason;
          setState(() {
            bridgeState = BridgeState.disconnected;
            socket = null;
            socketSub = null;
            lineRunning = false;
            if (failure != null) {
              authError = failure.message;
              controlError = null;
              connectionMessage = failure.message;
            } else if (!_closingIntentionally) {
              controlError = leaseReason ?? '连接已断开，控制已锁定';
              connectionMessage = controlError!;
            }
            _heartbeatTimer = null;
            _addLog(
              failure == null
                  ? 'bridge closed'
                  : 'auth closed: ${failure.code}',
            );
          });
          _closingIntentionally = false;
        },
        onError: (error) {
          if (!mounted || socket != ws) return;
          _heartbeatTimer?.cancel();
          final failure = AuthTransport.describeError(error);
          setState(() {
            bridgeState = BridgeState.failed;
            socket = null;
            socketSub = null;
            authError = failure.message;
            controlError = '连接异常，控制已锁定';
            lineRunning = false;
            connectionMessage = failure.message;
            _heartbeatTimer = null;
            _addLog('error ${failure.code}');
          });
        },
      );
      setState(() {
        bridgeState = BridgeState.connecting;
        authError = null;
        controlError = null;
        connectionMessage = '认证成功，正在申请控制权';
        _addLog('authenticated; claiming control lease');
      });
      _lease.startClaim();
    } catch (error) {
      if (!mounted || generation != _connectionGeneration) {
        nextTransport.close();
        return;
      }
      final failure = AuthTransport.describeError(error);
      if (transport == nextTransport) transport = null;
      nextTransport.close();
      if (!mounted) return;
      setState(() {
        bridgeState = BridgeState.failed;
        authError = failure.message;
        controlError = null;
        lineRunning = false;
        connectionMessage = failure.message;
        _addLog('connect rejected ${failure.code}');
      });
    }
  }

  /// Lease frames bypass the control gate on purpose: the claim itself must go
  /// out before any motion command is allowed.
  void _sendLeasePayload(Map<String, Object?> payload) {
    final ws = socket;
    if (ws == null) return;
    final text = jsonEncode(payload);
    ws.add(text);
    if (mounted) setState(() => _addLog('send $text'));
  }

  void _startHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = Timer.periodic(_lease.heartbeatInterval, (_) {
      if (!_lease.heartbeat()) {
        final reason = _lease.reason ?? '控制心跳超时，控制权已丢失';
        unawaited(_lockControl(reason));
      }
    });
  }

  void _onLeaseGranted() {
    _startHeartbeat();
    if (!mounted) return;
    setState(() {
      bridgeState = BridgeState.connected;
      authError = null;
      controlError = null;
      connectionMessage = '控制权已获取，控制通道已授权';
      _addLog('control lease granted');
    });
    _subscribeCoreTopics();
  }

  Future<void> _lockControl(String reason) async {
    if (!mounted || _lockInProgress) return;
    _lockInProgress = true;
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
    _connectionGeneration++;
    _lease.lock(reason);
    _closingIntentionally = true;
    final ws = socket;
    final sub = socketSub;
    socket = null;
    socketSub = null;
    await sub?.cancel();
    await ws?.close(1000, 'control lock');
    if (!mounted) {
      _lockInProgress = false;
      return;
    }
    setState(() {
      bridgeState = BridgeState.disconnected;
      controlError = reason;
      lineRunning = false;
      connectionMessage = reason;
      _addLog('control locked: $reason');
    });
    _closingIntentionally = false;
    _lockInProgress = false;
  }

  void _updateControlToken(String value) {
    final changed = value != controlToken;
    controlToken = value;
    if (!changed) return;
    if (bridgeState != BridgeState.disconnected) {
      unawaited(_disconnectBridge());
      setState(() {
        authError = '访问令牌已修改，请重新认证';
        connectionMessage = '访问令牌已修改，当前控制会话已断开';
        _addLog('token changed: control session closed');
      });
    } else {
      setState(() {
        if (authError != null) authError = null;
      });
    }
  }

  Future<void> _disconnectBridge() async {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
    _connectionGeneration++;
    _closingIntentionally = true;
    _lease.release();
    final ws = socket;
    final sub = socketSub;
    socket = null;
    socketSub = null;
    await sub?.cancel();
    await ws?.close(1000, 'app disconnect');
    if (!mounted) return;
    setState(() {
      bridgeState = BridgeState.disconnected;
      controlError = null;
      lineRunning = false;
      connectionMessage = '已断开 Bridge';
      _addLog('disconnect; lease released');
    });
    _closingIntentionally = false;
  }

  void _handleBridgeMessage(dynamic data) {
    if (!mounted) return;
    Map<String, dynamic>? payload;
    if (data is String) {
      try {
        final decoded = jsonDecode(data);
        if (decoded is Map) payload = Map<String, dynamic>.from(decoded);
      } catch (_) {
        payload = null;
      }
    }
    final failure = payload == null
        ? null
        : AuthTransport.fromWsMessage(payload);
    if (failure != null) {
      _heartbeatTimer?.cancel();
      _lease.lock(failure.message);
      unawaited(socket?.close(1008, failure.code));
      setState(() {
        authError = failure.message;
        controlError = null;
        bridgeState = BridgeState.disconnected;
        lineRunning = false;
        connectionMessage = failure.message;
        _addLog('auth rejected ${failure.code}');
      });
      return;
    }

    if (payload != null) {
      final wasGranted = _lease.granted;
      final mustLock = _lease.handleMessage(payload);
      if (!wasGranted && _lease.granted) {
        _onLeaseGranted();
      } else if (mustLock || _lease.state == ControlLeaseState.locked) {
        final reason = _lease.reason ?? '控制租约异常，控制已锁定';
        unawaited(_lockControl(reason));
      }
    }

    setState(() {
      _addLog('recv ${data.toString()}');
    });
  }

  void _subscribeCoreTopics() {
    if (!controlReady) return;
    for (final topic in const [
      '/imu',
      '/robot_pose',
      '/reflector_position',
      '/printer_status',
    ]) {
      _sendBridge({'op': 'subscribe', 'topic': topic});
    }
  }

  void _sendDriveCommand(double linear, double angular) {
    _sendBridge({
      'op': 'publish',
      'topic': '/tablet_cmd_vel',
      'type': 'geometry_msgs/msg/Twist',
      'msg': {
        'linear': {'x': linear, 'y': 0.0, 'z': 0.0},
        'angular': {'x': 0.0, 'y': 0.0, 'z': angular},
      },
    });
  }

  void _sendPrinterCommand(String action) {
    _sendBridge({
      'op': 'call_service',
      'service': '/printer/quick_command',
      'type': 'xline_msgs/srv/QuickCommand',
      'args': {'printer_name': 'center', 'action': action, 'param': 0},
    });
  }

  void _sendLnCommand(int commandType) {
    _sendBridge({
      'op': 'call_service',
      'service': '/ln_driver/command_srv',
      'type': 'xline_msgs/srv/LnCommand',
      'args': {'command_type': commandType},
    });
  }

  void _toggleMission() {
    if (!controlReady) {
      setState(
        () => _addLog('blocked mission: control session not authenticated'),
      );
      return;
    }
    final next = !lineRunning;
    _sendBridge({
      'op': 'mission_control',
      'action': next ? 'start' : 'stop',
      'running': next,
    });
    setState(() => lineRunning = next);
    if (next) {
      _sendPrinterCommand('start_print');
    } else {
      _sendPrinterCommand('stop_print');
      _sendDriveCommand(0, 0);
    }
  }

  void _sendBridge(Map<String, Object?> payload) {
    final text = jsonEncode(payload);
    if (controlReady && socket != null) {
      socket!.add(text);
      setState(() => _addLog('send $text'));
    } else {
      setState(() => _addLog('blocked (auth/lease/not connected) $text'));
    }
  }

  void _addLog(String line) {
    final time = TimeOfDay.now().format(context);
    bridgeLogs.insert(0, '$time  $line');
    if (bridgeLogs.length > 30) bridgeLogs.removeLast();
  }
}

class _Header extends StatelessWidget {
  const _Header({
    required this.device,
    required this.lineRunning,
    required this.bridgeState,
    required this.authError,
    required this.lockReason,
  });

  final RoverDevice device;
  final bool lineRunning;
  final BridgeState bridgeState;
  final String? authError;
  final String? lockReason;

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
            text: authError != null
                ? '认证失败'
                : (lockReason != null
                      ? '控制已锁定'
                      : (lineRunning ? '划线中' : bridgeState.label)),
            color: authError != null
                ? const Color(0xffef4444)
                : (lockReason != null
                      ? const Color(0xffef4444)
                      : (lineRunning
                            ? const Color(0xfff59e0b)
                            : bridgeState.color)),
          ),
        ],
      ),
    );
  }
}

/// Persistent, non-dismissable authentication warning shown above every page.
/// When this is visible the control gate is closed and no motion command may be
/// sent until the operator re-authenticates.
class AuthStatusBanner extends StatelessWidget {
  const AuthStatusBanner({required this.message, super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const ValueKey('auth-status-banner'),
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(14, 0, 14, 6),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: const Color(0xff3f1d24),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xffef4444)),
      ),
      child: Row(
        children: [
          const Icon(Icons.gpp_bad_rounded, color: Color(0xfffecaca), size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(
                color: Color(0xfffecaca),
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          const SizedBox(width: 8),
          const Text(
            '控制已锁定',
            style: TextStyle(color: Color(0xfffca5a5), fontSize: 12),
          ),
        ],
      ),
    );
  }
}

class _DashboardPage extends StatelessWidget {
  const _DashboardPage({
    required this.device,
    required this.lineRunning,
    required this.bridgeState,
    required this.onStartMission,
    required this.onAddDevice,
    required this.onConnect,
  });

  final RoverDevice device;
  final bool lineRunning;
  final BridgeState bridgeState;
  final VoidCallback onStartMission;
  final VoidCallback onAddDevice;
  final VoidCallback onConnect;

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const ValueKey('dashboard'),
      padding: const EdgeInsets.fromLTRB(14, 8, 14, 14),
      children: [
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
        const _MetricStrip(),
        const SizedBox(height: 12),
        _Panel(
          title: '实时视图',
          trailing: const Text(
            'camera / map',
            style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
          ),
          child: SizedBox(
            height: 178,
            child: CustomPaint(
              painter: _MiniOverviewPainter(lineRunning: lineRunning),
              child: const SizedBox.expand(),
            ),
          ),
        ),
        const SizedBox(height: 12),
        _Panel(
          title: '当前任务',
          trailing: _StatusChip(
            text: lineRunning ? 'Running' : 'Ready',
            color: lineRunning
                ? const Color(0xfff59e0b)
                : const Color(0xff22c55e),
          ),
          child: Column(
            children: [
              const _MissionStep(title: '定位与追踪', done: true),
              _MissionStep(title: '路径执行', done: lineRunning),
              _MissionStep(title: '喷码同步', done: lineRunning),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: onStartMission,
                  icon: Icon(
                    lineRunning ? Icons.stop_rounded : Icons.play_arrow_rounded,
                  ),
                  label: Text(lineRunning ? '停止划线任务' : '开始划线任务'),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _DevicePage extends StatelessWidget {
  const _DevicePage({
    required this.devices,
    required this.message,
    required this.bridgeState,
    required this.logs,
    required this.tokenController,
    required this.authError,
    required this.controlError,
    required this.controlReady,
    required this.onTokenChanged,
    required this.onAddDevice,
    required this.onConnect,
    required this.onTestActive,
    required this.onDisconnect,
  });

  final List<RoverDevice> devices;
  final String message;
  final BridgeState bridgeState;
  final List<String> logs;
  final TextEditingController tokenController;
  final String? authError;
  final String? controlError;
  final bool controlReady;
  final ValueChanged<String> onTokenChanged;
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
        _AuthPanel(
          controller: tokenController,
          authError: authError,
          controlError: controlError,
          controlReady: controlReady,
          onTokenChanged: onTokenChanged,
          onConnect: onTestActive,
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
                '适合实验室局域网，连接 wss://小车IP:8000；本机离线演练才允许显式使用明文。',
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

class _AuthPanel extends StatelessWidget {
  const _AuthPanel({
    required this.controller,
    required this.authError,
    required this.controlError,
    required this.controlReady,
    required this.onTokenChanged,
    required this.onConnect,
  });

  final TextEditingController controller;
  final String? authError;
  final String? controlError;
  final bool controlReady;
  final ValueChanged<String> onTokenChanged;
  final VoidCallback onConnect;

  @override
  Widget build(BuildContext context) {
    final configured = controller.text.trim().isNotEmpty;
    return _Panel(
      title: '访问认证',
      trailing: _StatusChip(
        text: authError != null
            ? '认证失败'
            : (controlError != null
                  ? '控制权未确认'
                  : (configured ? '令牌已配置' : '未配置')),
        color: authError != null
            ? const Color(0xffef4444)
            : (controlError != null
                  ? const Color(0xffef4444)
                  : (configured
                        ? const Color(0xff22c55e)
                        : const Color(0xfff59e0b))),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            key: const ValueKey('auth-token-field'),
            controller: controller,
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            onChanged: onTokenChanged,
            decoration: const InputDecoration(
              labelText: '访问令牌',
              hintText: '粘贴由管理员签发的短期令牌',
              border: OutlineInputBorder(),
              isDense: true,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            '令牌只保存在本次运行内存，不写入本地配置；认证失败时会话立即锁定并停止发送控制命令。',
            style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
          ),
          if (controlError != null) ...[
            const SizedBox(height: 6),
            Text(
              controlError!,
              style: const TextStyle(color: Color(0xfffca5a5), fontSize: 12),
            ),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              FilledButton.icon(
                onPressed: onConnect,
                icon: const Icon(Icons.verified_user_rounded),
                label: const Text('认证并连接'),
              ),
              const SizedBox(width: 10),
              Text(
                controlReady ? '控制通道已授权' : '控制通道未授权',
                style: TextStyle(
                  color: controlReady
                      ? const Color(0xff22c55e)
                      : const Color(0xff94a3b8),
                  fontSize: 12,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _AddDeviceSheet extends StatefulWidget {
  const _AddDeviceSheet();

  @override
  State<_AddDeviceSheet> createState() => _AddDeviceSheetState();
}

class _AddDeviceSheetState extends State<_AddDeviceSheet> {
  final nameController = TextEditingController(text: 'XLine-Car-02');
  final ipController = TextEditingController(text: '192.168.31.42');
  final portController = TextEditingController(text: '8000');
  final domainController = TextEditingController(text: '0');
  String type = 'FastAPI ROS Bridge';
  bool secure = true;
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
                  value: 'FastAPI ROS Bridge',
                  child: Text('FastAPI ROS Bridge'),
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
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: secure,
              onChanged: (value) => setState(() => secure = value),
              title: const Text('HTTPS / WSS 加密传输'),
              subtitle: const Text('关闭仅允许 127.0.0.1、::1 或 localhost 的离线演练'),
            ),
            const SizedBox(height: 4),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(16),
                color: const Color(0xff101d33),
                border: Border.all(color: const Color(0xff22304a)),
              ),
              child: Text(
                '连接地址：${secure ? 'wss' : 'ws'}://${ipController.text}:${portController.text}\n状态：$testStatus',
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

  Future<void> _testConnection() async {
    setState(() {
      testing = true;
      testStatus = '正在校验 FastAPI ROS Bridge 配置...';
    });
    await Future<void>.delayed(const Duration(milliseconds: 300));
    if (!mounted) return;
    final host = ipController.text.trim();
    final port = int.tryParse(portController.text.trim());
    setState(() {
      testing = false;
      if (host.isEmpty) {
        testStatus = '失败：请填写机器人 IP';
      } else if (port == null || port < 1 || port > 65535) {
        testStatus = '失败：端口必须为 1-65535';
      } else if (!secure && !AuthTransport.isLoopbackHost(host)) {
        testStatus = '失败：非本机地址禁止使用明文 HTTP/WS';
      } else {
        testStatus = '配置通过：${secure ? 'wss' : 'ws'}://$host:$port';
      }
    });
  }

  void _saveDevice() {
    final ip = ipController.text.trim();
    final name = nameController.text.trim();
    final port = int.tryParse(portController.text.trim()) ?? 8000;
    final domainId = int.tryParse(domainController.text.trim()) ?? 0;
    if (ip.isEmpty || name.isEmpty) {
      setState(() => testStatus = '失败：设备名称和 IP 不能为空');
      return;
    }
    if (!secure && !AuthTransport.isLoopbackHost(ip)) {
      setState(() => testStatus = '失败：非本机地址禁止使用明文 HTTP/WS');
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
        secure: secure,
      ),
    );
  }
}

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

class _SettingsPage extends StatelessWidget {
  const _SettingsPage({
    required this.device,
    required this.lineWidth,
    required this.onLineWidthChanged,
    required this.onAddDevice,
    required this.bridgeState,
    required this.authError,
    required this.hasToken,
  });

  final RoverDevice device;
  final double lineWidth;
  final ValueChanged<double> onLineWidthChanged;
  final VoidCallback onAddDevice;
  final BridgeState bridgeState;
  final String? authError;
  final bool hasToken;

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
              _ConfigRow(
                '访问认证',
                authError ?? (hasToken ? '令牌已配置（仅内存）' : '未配置'),
              ),
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

class _MetricStrip extends StatelessWidget {
  const _MetricStrip();

  @override
  Widget build(BuildContext context) {
    return const Row(
      children: [
        Expanded(
          child: _MiniMetric(label: '电量', value: '82%'),
        ),
        SizedBox(width: 8),
        Expanded(
          child: _MiniMetric(label: '速度', value: '0.34'),
        ),
        SizedBox(width: 8),
        Expanded(
          child: _MiniMetric(label: '定位', value: '±8mm'),
        ),
        SizedBox(width: 8),
        Expanded(
          child: _MiniMetric(label: '喷码', value: 'Ready'),
        ),
      ],
    );
  }
}

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

class _MiniOverviewPainter extends CustomPainter {
  _MiniOverviewPainter({required this.lineRunning});

  final bool lineRunning;

  @override
  void paint(Canvas canvas, Size size) {
    final bg = Paint()..color = const Color(0xff0f172a);
    final border = Paint()
      ..color = const Color(0xff22304a)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    final rect = RRect.fromRectAndRadius(
      Offset.zero & size,
      const Radius.circular(18),
    );
    canvas.drawRRect(rect, bg);
    canvas.drawRRect(rect, border);

    final grid = Paint()
      ..color = const Color(0x3322304a)
      ..strokeWidth = 1;
    for (double x = 18; x < size.width; x += 28) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    }
    for (double y = 18; y < size.height; y += 28) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }

    final path = Path()
      ..moveTo(size.width * .12, size.height * .72)
      ..cubicTo(
        size.width * .30,
        size.height * .42,
        size.width * .56,
        size.height * .76,
        size.width * .82,
        size.height * .24,
      );
    canvas.drawPath(
      path,
      Paint()
        ..color = const Color(0xff60a5fa)
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeWidth = 4,
    );

    final mark = Paint()
      ..color = lineRunning ? const Color(0xfff59e0b) : const Color(0xff22c55e)
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round;
    for (var i = 0; i < 4; i++) {
      canvas.drawLine(
        Offset(size.width * .16, size.height * (.34 + i * .10)),
        Offset(size.width * .40, size.height * (.30 + i * .10)),
        mark,
      );
    }

    final robot = Offset(size.width * .54, size.height * .54);
    canvas.drawCircle(robot, 15, Paint()..color = const Color(0xff22c55e));
    canvas.drawCircle(robot, 25, Paint()..color = const Color(0x2222c55e));
    canvas.drawCircle(
      Offset(size.width * .82, size.height * .24),
      8,
      Paint()..color = const Color(0xfff59e0b),
    );

    final labelPainter = TextPainter(
      text: TextSpan(
        text: lineRunning ? 'RUNNING' : 'READY',
        style: TextStyle(
          color: lineRunning
              ? const Color(0xfffbbf24)
              : const Color(0xff86efac),
          fontSize: 12,
          fontWeight: FontWeight.w800,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    labelPainter.paint(canvas, const Offset(14, 12));
  }

  @override
  bool shouldRepaint(covariant _MiniOverviewPainter oldDelegate) {
    return oldDelegate.lineRunning != lineRunning;
  }
}

class _TabItem {
  const _TabItem(this.label, this.icon);

  final String label;
  final IconData icon;
}
