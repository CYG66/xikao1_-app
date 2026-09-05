// XLine 划线小车 App 入口与主状态调度。
// 页面、通用组件和数据模型按职责拆分到对应目录。
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/foundation.dart' show ValueListenable;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:file_picker/file_picker.dart';

import 'constants/app_constants.dart';
import 'models/vehicle_status.dart';
import 'services/agent_chat_preferences.dart';
import 'services/device_preferences.dart';
import 'services/offline_speech_service.dart';
import 'utils/ros_messages.dart';
import 'viewmodels/rover_device.dart';

part 'components/shell_components.dart';
part 'pages/dashboard_page.dart';
part 'pages/device_page.dart';
part 'pages/map_page.dart';
part 'pages/control_page.dart';
part 'pages/mission_page.dart';
part 'pages/drawing_editor_page.dart';
part 'pages/agent_page.dart';
part 'pages/settings_page.dart';
part 'pages/monitor_page.dart';
part 'components/common_components.dart';
part 'components/map_components.dart';
part 'models/tab_item.dart';

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
          seedColor: const Color(0xff16a66a),
          brightness: Brightness.light,
        ),
        scaffoldBackgroundColor: const Color(0xfff4f6f8),
        useMaterial3: true,
        visualDensity: VisualDensity.compact,
        fontFamilyFallback: const ['HarmonyOS Sans', 'Microsoft YaHei'],
        cardTheme: CardThemeData(
          color: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
            side: const BorderSide(color: Color(0xffdce3ea)),
          ),
        ),
        dividerTheme: const DividerThemeData(
          color: Color(0xffe2e8f0),
          thickness: 1,
          space: 1,
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            minimumSize: const Size(0, 40),
            backgroundColor: const Color(0xff16a66a),
            foregroundColor: Colors.white,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(8),
            ),
          ),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(
            minimumSize: const Size(0, 40),
            foregroundColor: const Color(0xff334155),
            side: const BorderSide(color: Color(0xffcbd5e1)),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(8),
            ),
          ),
        ),
        navigationBarTheme: const NavigationBarThemeData(
          height: 64,
          backgroundColor: Colors.white,
          indicatorColor: Color(0xffd9f3e7),
          labelTextStyle: WidgetStatePropertyAll(
            TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
          ),
          iconTheme: WidgetStatePropertyAll(
            IconThemeData(size: 22, color: Color(0xff334155)),
          ),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: const Color(0xfff8fafc),
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 12,
            vertical: 11,
          ),
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: const BorderSide(color: Color(0xffcbd5e1)),
          ),
        ),
      ),
      home: const RoverHomePage(),
    );
  }
}

/// 可展开的左侧一级导航，适合平板横屏操作。
class _SideNavigation extends StatelessWidget {
  const _SideNavigation({
    required this.tabs,
    required this.selectedIndex,
    required this.expanded,
    required this.device,
    required this.bridgeState,
    required this.lineRunning,
    required this.emergencyStopped,
    required this.onEmergencyPressed,
    required this.onToggle,
    required this.onSelected,
  });

  final List<_TabItem> tabs;
  final int selectedIndex;
  final bool expanded;
  final RoverDevice device;
  final BridgeState bridgeState;
  final bool lineRunning;
  final bool emergencyStopped;
  final VoidCallback onEmergencyPressed;
  final VoidCallback onToggle;
  final ValueChanged<int> onSelected;

  @override
  Widget build(BuildContext context) {
    if (!expanded) {
      return Container(
        width: 44,
        color: const Color(0xfff7fbfa),
        child: Material(
          color: Colors.transparent,
          child: Column(
            children: [
              const SizedBox(height: 12),
              const Icon(
                Icons.precision_manufacturing_rounded,
                size: 20,
                color: Color(0xff16a66a),
              ),
              const SizedBox(height: 18),
              Expanded(
                child: ListView.separated(
                  padding: const EdgeInsets.symmetric(horizontal: 5),
                  itemCount: tabs.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 6),
                  itemBuilder: (context, index) {
                    final tab = tabs[index];
                    final selected = selectedIndex == index;
                    return Tooltip(
                      message: tab.label,
                      child: InkWell(
                        borderRadius: BorderRadius.circular(8),
                        onTap: () => onSelected(index),
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 160),
                          height: 42,
                          alignment: Alignment.center,
                          decoration: BoxDecoration(
                            color: selected
                                ? const Color(0xffdff7eb)
                                : Colors.transparent,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Icon(
                            tab.icon,
                            size: 21,
                            color: selected
                                ? const Color(0xff16865a)
                                : const Color(0xff64748b),
                          ),
                        ),
                      ),
                    );
                  },
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(4, 8, 4, 12),
                child: Tooltip(
                  message: '展开导航栏',
                  child: IconButton(
                    onPressed: onToggle,
                    icon: const Icon(Icons.chevron_right_rounded),
                    color: const Color(0xff475569),
                    constraints: const BoxConstraints.tightFor(
                      width: 36,
                      height: 36,
                    ),
                    padding: EdgeInsets.zero,
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    }
    const width = 156.0;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeOutCubic,
      width: width,
      color: const Color(0xfff7fbfa),
      child: Material(
        color: Colors.transparent,
        child: Column(
          children: [
            const SizedBox(height: 12),
            Padding(
              padding: EdgeInsets.symmetric(horizontal: expanded ? 14 : 10),
              child: Row(
                mainAxisAlignment: expanded
                    ? MainAxisAlignment.start
                    : MainAxisAlignment.center,
                children: [
                  const Icon(
                    Icons.precision_manufacturing_rounded,
                    color: Color(0xff16a66a),
                  ),
                  if (expanded) ...[
                    const SizedBox(width: 10),
                    const Flexible(
                      child: Text(
                        'XLine 划线小车',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                          color: Color(0xff14532d),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 18),
            Expanded(
              child: ListView.separated(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                itemCount: tabs.length,
                separatorBuilder: (_, __) => const SizedBox(height: 6),
                itemBuilder: (context, index) {
                  final tab = tabs[index];
                  final selected = selectedIndex == index;
                  final item = InkWell(
                    borderRadius: BorderRadius.circular(8),
                    onTap: () => onSelected(index),
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 160),
                      height: 44,
                      padding: EdgeInsets.symmetric(
                        horizontal: expanded ? 14 : 0,
                      ),
                      decoration: BoxDecoration(
                        color: selected
                            ? const Color(0xffdff7eb)
                            : Colors.transparent,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Row(
                        mainAxisAlignment: expanded
                            ? MainAxisAlignment.start
                            : MainAxisAlignment.center,
                        children: [
                          Icon(
                            tab.icon,
                            size: 22,
                            color: selected
                                ? const Color(0xff16865a)
                                : const Color(0xff64748b),
                          ),
                          if (expanded) ...[
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                tab.label,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  fontSize: 14,
                                  fontWeight: selected
                                      ? FontWeight.w700
                                      : FontWeight.w500,
                                  color: selected
                                      ? const Color(0xff166534)
                                      : const Color(0xff334155),
                                ),
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                  );
                  return expanded
                      ? item
                      : Tooltip(message: tab.label, child: item);
                },
              ),
            ),
            if (expanded)
              Padding(
                padding: const EdgeInsets.fromLTRB(10, 4, 10, 8),
                child: _SideDeviceStatus(
                  device: device,
                  bridgeState: bridgeState,
                  lineRunning: lineRunning,
                  emergencyStopped: emergencyStopped,
                  onEmergencyPressed: onEmergencyPressed,
                ),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(8, 8, 8, 12),
              child: Tooltip(
                message: expanded ? '收起导航栏' : '展开导航栏',
                child: IconButton(
                  onPressed: onToggle,
                  icon: Icon(
                    expanded
                        ? Icons.chevron_left_rounded
                        : Icons.chevron_right_rounded,
                  ),
                  style: IconButton.styleFrom(
                    minimumSize: const Size(44, 44),
                    foregroundColor: const Color(0xff475569),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SideDeviceStatus extends StatelessWidget {
  const _SideDeviceStatus({
    required this.device,
    required this.bridgeState,
    required this.lineRunning,
    required this.emergencyStopped,
    required this.onEmergencyPressed,
  });

  final RoverDevice device;
  final BridgeState bridgeState;
  final bool lineRunning;
  final bool emergencyStopped;
  final VoidCallback onEmergencyPressed;

  @override
  Widget build(BuildContext context) {
    final connected = bridgeState == BridgeState.connected;
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 10, 8, 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xffdce3ea)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            device.name,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 12),
          ),
          const SizedBox(height: 3),
          Text(
            device.bridgeUrl,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: Color(0xff64748b), fontSize: 10),
          ),
          const SizedBox(height: 7),
          Row(
            children: [
              Expanded(
                child: _StatusChip(
                  text: lineRunning ? '划线中' : bridgeState.label,
                  color: lineRunning
                      ? const Color(0xfff59e0b)
                      : bridgeState.color,
                ),
              ),
              if (connected) ...[
                const SizedBox(width: 4),
                IconButton(
                  tooltip: emergencyStopped ? '解除急停' : '紧急停车',
                  onPressed: onEmergencyPressed,
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints.tightFor(
                    width: 32,
                    height: 32,
                  ),
                  style: IconButton.styleFrom(
                    backgroundColor: emergencyStopped
                        ? const Color(0xffdc2626)
                        : const Color(0xfffff1f2),
                    foregroundColor: emergencyStopped
                        ? Colors.white
                        : const Color(0xffdc2626),
                  ),
                  icon: Icon(
                    emergencyStopped
                        ? Icons.lock_open_rounded
                        : Icons.stop_rounded,
                    size: 16,
                  ),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }
}

/// App 的主容器，承载“首页 / 任务 / 监控 / 设置”四个一级入口。
class RoverHomePage extends StatefulWidget {
  const RoverHomePage({super.key});

  @override
  State<RoverHomePage> createState() => _RoverHomePageState();
}

/// 主页面运行状态和业务调度中心。
///
/// 这里管理页面切换、设备列表、WebSocket、任务、速度和日志。
/// 项目扩展后，建议将通信与状态逐步拆分到 `api/` 和 `stores/`。
class _RoverHomePageState extends State<RoverHomePage>
    with WidgetsBindingObserver {
  int tabIndex = 0;
  bool sideNavExpanded = true;
  bool homeControlOverlayVisible = false;
  int homeModule = 0;
  int selectedDeviceIndex = 0;
  bool lineRunning = false;
  bool printerEnabled = true;
  double linearSpeed = AppConstants.defaultLinearVelocity;
  double angularSpeed = 0.40;
  bool rosAvailable = false;
  bool backendOnline = false;
  bool emergencyStopped = false;
  bool controlGranted = false;
  bool releaseEmergencyAfterControlClaim = false;
  bool emergencyReleaseInProgress = false;
  String? controlOwner;
  bool controlReady = false;
  bool agentMotionActive = false;
  int agentMotionRemainingMs = 0;
  final ValueNotifier<int> agentMotionNotifier = ValueNotifier<int>(-1);
  bool driveDeviceConnected = false;
  bool motorDriverReady = false;
  String driveTransport = 'socketcan';
  String driveDevicePath = 'can0';
  bool missionNodesReady = false;
  bool localizationValid = false;
  String localizationSource = 'unavailable';
  bool ln150Ready = false;
  bool preferTotalStation = false;
  bool showRelativeMap = false;
  double? liveMapOriginX;
  double? liveMapOriginY;
  List<List<double>> liveMapTrace = const [];
  bool printerReady = false;
  VehicleStatus? vehicleStatus;
  double? linearVelocity;
  double? localizationAccuracyMm;
  int? telemetryAgeMs;
  Map<String, dynamic> robotPose = const {};
  Map<String, dynamic> odometry = const {};
  Map<String, dynamic> reflectorPosition = const {};
  Map<String, dynamic> gridMap = const {};
  List<Map<String, dynamic>> plannedPaths = const [];
  List<Map<String, dynamic>> pathAnnotations = const [];
  int? mapAgeMs;
  int? pathsAgeMs;
  List<Map<String, dynamic>> missionPreviewPaths = const [];
  String? missionPreviewFile;
  List<List<double>> poseTrace = const [];
  Map<String, dynamic> printerStatus = const {};
  final Map<String, bool> printerSprayPending = {};
  final Map<String, Timer> printerSprayTimeouts = {};
  Map<String, dynamic> obstacleDistances = const {};
  int? obstacleAgeMs;
  Map<String, dynamic> wheelSpeeds = const {};
  Map<String, dynamic> motorStatus = const {};
  Map<String, dynamic> telemetryContract = const {};
  bool telemetryApiOnline = false;
  bool telemetryPollInFlight = false;
  String telemetryApiError = '';
  int? telemetryRequestLatencyMs;
  int? battery;
  String localizationCalibration = 'idle';
  bool localizationCalibrationAvailable = false;
  String missionStage = 'idle';
  bool missionPaused = false;
  String missionFile = 'test_pattern.json';
  final List<String> missionFiles = [
    'test_pattern.json',
    'huanong_skeleton.json',
    'square_image.json',
  ];
  bool missionFilesLoading = false;
  int? missionCurrentId;
  int missionCompleted = 0;
  int missionTotal = 0;
  String missionError = '';
  String connectionMessage = '已加载默认设备，等待连接测试';
  BridgeState bridgeState = BridgeState.disconnected;
  WebSocket? socket;
  StreamSubscription? socketSub;
  Timer? statusWatchdog;
  Timer? telemetryPoll;
  Timer? controlHeartbeat;
  DateTime? lastControlWarningAt;
  final String controlClientId =
      'xline-app-${DateTime.now().microsecondsSinceEpoch}';
  final List<String> bridgeLogs = ['App 已就绪，可连接小车端 ROS2 Bridge'];

  final List<RoverDevice> devices = [];

  /// 返回当前选中的小车；若无已连接设备，则返回第一台。
  RoverDevice get activeDevice {
    if (devices.isEmpty) return RoverDevice.unconfigured;
    return devices[selectedDeviceIndex.clamp(0, devices.length - 1)];
  }

  void _setActiveDeviceConnected(bool connected) {
    if (devices.isEmpty) return;
    final index = selectedDeviceIndex.clamp(0, devices.length - 1);
    final device = devices[index];
    devices[index] = RoverDevice(
      name: device.name,
      ip: device.ip,
      port: device.port,
      domainId: device.domainId,
      type: device.type,
      connected: connected,
    );
  }

  bool get localizationReady =>
      localizationValid &&
      robotPose.isNotEmpty &&
      telemetryAgeMs != null &&
      telemetryAgeMs! <= 750;

  bool get missionReady =>
      bridgeState == BridgeState.connected &&
      rosAvailable &&
      backendOnline &&
      missionNodesReady &&
      controlGranted &&
      localizationReady;

  Map<String, dynamic> get liveMapPose {
    final sourcePose = realtimePose;
    final x = (sourcePose['x'] as num?)?.toDouble();
    final y = (sourcePose['y'] as num?)?.toDouble();
    if (x == null ||
        y == null ||
        liveMapOriginX == null ||
        liveMapOriginY == null) {
      return sourcePose;
    }
    return {
      ...sourcePose,
      'x': x - liveMapOriginX!,
      'y': y - liveMapOriginY!,
      'frame_id': 'app_live_map',
    };
  }

  Map<String, dynamic> get realtimePose {
    if (robotPose['x'] is num && robotPose['y'] is num) return robotPose;
    if (odometry['x'] is num && odometry['y'] is num) return odometry;
    return const {'x': 0.0, 'y': 0.0, 'theta': 0.0, 'frame_id': 'map'};
  }

  Map<String, dynamic> get liveMapGrid {
    if (gridMap.isEmpty || liveMapOriginX == null || liveMapOriginY == null) {
      return gridMap;
    }
    return {
      ...gridMap,
      'origin_x':
          ((gridMap['origin_x'] as num?)?.toDouble() ?? 0) - liveMapOriginX!,
      'origin_y':
          ((gridMap['origin_y'] as num?)?.toDouble() ?? 0) - liveMapOriginY!,
      'frame_id': 'app_live_map',
    };
  }

  List<Map<String, dynamic>> get liveMapPlannedPaths {
    final sourcePaths = _displayedPlannedPaths;
    if (liveMapOriginX == null || liveMapOriginY == null) return sourcePaths;
    return sourcePaths
        .map((segment) {
          final transformedPoints = <List<double>>[];
          for (final raw in segment['points'] as List? ?? const []) {
            if (raw is List &&
                raw.length >= 2 &&
                raw[0] is num &&
                raw[1] is num) {
              transformedPoints.add([
                (raw[0] as num).toDouble() - liveMapOriginX!,
                (raw[1] as num).toDouble() - liveMapOriginY!,
              ]);
            }
          }
          return {
            ...segment,
            'points': transformedPoints,
            'frame_id': 'app_live_map',
          };
        })
        .toList(growable: false);
  }

  void _appendLiveMapPoint() {
    final x = (realtimePose['x'] as num?)?.toDouble();
    final y = (realtimePose['y'] as num?)?.toDouble();
    if (x == null || y == null) return;
    liveMapOriginX ??= x;
    liveMapOriginY ??= y;
    final point = [x - liveMapOriginX!, y - liveMapOriginY!];
    if (liveMapTrace.isNotEmpty) {
      final last = liveMapTrace.last;
      final dx = point[0] - last[0];
      final dy = point[1] - last[1];
      if (math.sqrt(dx * dx + dy * dy) < .005) return;
    }
    liveMapTrace = [...liveMapTrace, point];
    if (liveMapTrace.length > 5000) {
      liveMapTrace = liveMapTrace.sublist(liveMapTrace.length - 5000);
    }
  }

  void _refreshLiveMap() {
    final x = (robotPose['x'] as num?)?.toDouble();
    final y = (robotPose['y'] as num?)?.toDouble();
    if (x == null || y == null) {
      setState(() {
        liveMapOriginX = null;
        liveMapOriginY = null;
        liveMapTrace = const [
          <double>[0, 0],
        ];
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('相对地图已刷新，下一帧里程计将作为原点')));
      return;
    }
    setState(() {
      liveMapOriginX = x;
      liveMapOriginY = y;
      liveMapTrace = const [
        <double>[0, 0],
      ];
    });
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('已将当前位置设为地图原点，并从这里继续构建轨迹')));
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    if (AppConstants.layoutPreviewMode) {
      _enableLayoutPreview();
    } else {
      _startTelemetryPolling();
      unawaited(_restoreDevices());
    }
  }

  /// Populate realistic read-only data for Android layout work.
  /// Outbound commands are blocked by [_sendBridge] below.
  void _enableLayoutPreview() {
    const previewDevice = RoverDevice(
      name: 'XLine Rover · 布局预览',
      ip: '192.168.0.100',
      port: 8000,
      domainId: 0,
      type: 'FastAPI Backend',
      connected: true,
    );
    devices
      ..clear()
      ..add(previewDevice);
    bridgeState = BridgeState.connected;
    connectionMessage = '已连接（布局预览）';
    rosAvailable = true;
    backendOnline = true;
    emergencyStopped = false;
    controlGranted = true;
    controlOwner = controlClientId;
    controlReady = true;
    driveDeviceConnected = true;
    motorDriverReady = true;
    missionNodesReady = true;
    localizationValid = true;
    localizationSource = 'odom_imu_relative';
    localizationCalibration = 'accepted';
    localizationCalibrationAvailable = true;
    ln150Ready = false;
    printerReady = true;
    printerEnabled = true;
    linearVelocity = 0.0;
    telemetryAgeMs = 32;
    battery = 86;
    robotPose = const {'x': 0.0, 'y': 0.0, 'theta': 0.0, 'frame_id': 'map'};
    odometry = const {'x': 0.0, 'y': 0.0, 'theta': 0.0, 'frame_id': 'odom'};
    gridMap = const {
      'frame_id': 'map',
      'resolution': 0.05,
      'width': 160,
      'height': 120,
      'origin_x': -4.0,
      'origin_y': -3.0,
      'runs': <List<Object>>[],
    };
    plannedPaths = _previewPaths;
    missionPreviewPaths = _previewPaths;
    missionPreviewFile = missionFile;
    printerStatus = const {
      'printer_center': {
        'connected': true,
        'is_online': true,
        'enabled': false,
        'spraying': false,
        'status': 'ready',
      },
    };
    obstacleDistances = const {
      'front': 2.4,
      'back': 2.8,
      'left': 1.6,
      'right': 1.7,
    };
    obstacleAgeMs = 120;
    wheelSpeeds = const {'left_mps': 0.0, 'right_mps': 0.0};
    motorStatus = const {'ready': true, 'error': ''};
    pathAnnotations = const [];
    poseTrace = const [
      [0.0, 0.0],
      [0.12, 0.0],
      [0.24, 0.02],
      [0.36, 0.04],
    ];
    mapAgeMs = 32;
    pathsAgeMs = 32;
    vehicleStatus = const VehicleStatus(
      deviceId: 'preview-rover',
      model: 'XLine Rover',
      softwareVersion: 'layout-preview',
      online: true,
      rosAvailable: true,
      controlReady: true,
      localizationValid: true,
      localizationSource: 'odom_imu_relative',
      emergencyStopped: false,
      capabilities: VehicleCapabilities(
        manualDrive: true,
        pathPlanning: true,
        pathExecution: true,
        localization: true,
        printing: true,
        emergencyStop: true,
      ),
    );
  }

  List<Map<String, dynamic>> get _previewPaths => const [
    {
      'id': 0,
      'frame_id': 'map',
      'route_type': 'transition',
      'points': [
        [-0.8, -0.8],
        [0.0, 0.0],
      ],
    },
    {
      'id': 1,
      'frame_id': 'map',
      'route_type': 'drawing',
      'points': [
        [0.0, 0.0],
        [1.2, 0.0],
        [1.2, 0.8],
        [0.0, 0.8],
        [0.0, 0.0],
      ],
    },
  ];

  Future<void> _restoreDevices() async {
    try {
      final preferences = await DevicePreferences.load();
      if (preferences == null) return;
      final decoded = jsonDecode(preferences.devicesJson);
      if (decoded is! List) return;
      final restored = decoded
          .whereType<Map>()
          .map((item) => RoverDevice.fromJson(Map<String, dynamic>.from(item)))
          .where((device) => device.isConfigured)
          .toList();
      if (restored.isEmpty || !mounted) return;
      final selectedIndex = preferences.selectedIndex.clamp(
        0,
        restored.length - 1,
      );
      setState(() {
        selectedDeviceIndex = selectedIndex;
        devices
          ..clear()
          ..addAll([
            for (var index = 0; index < restored.length; index++)
              RoverDevice(
                name: restored[index].name,
                ip: restored[index].ip,
                port: restored[index].port,
                domainId: restored[index].domainId,
                type: restored[index].type,
                connected: false,
              ),
          ]);
        connectionMessage = '已恢复 ${restored.length} 台设备，正在重新连接';
      });
      await _connectActiveDevice();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        connectionMessage = '设备配置恢复失败，请重新添加';
        _addLog('restore devices failed: $error');
      });
    }
  }

  Future<void> _persistDevices() async {
    try {
      await DevicePreferences.save(
        devicesJson: jsonEncode(
          devices.map((device) => device.toJson()).toList(),
        ),
        selectedIndex: devices.isEmpty
            ? 0
            : selectedDeviceIndex.clamp(0, devices.length - 1),
      );
    } catch (error) {
      if (mounted) setState(() => _addLog('persist devices failed: $error'));
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) {
      _sendBridge(RosMessages.cmdVel(0, 0));
    }
  }

  Map<String, dynamic> get centerPrinter =>
      _asStringMap(printerStatus['printer_center']);

  String get centerPrinterLabel {
    if (!printerReady) return '节点未就绪';
    if (centerPrinter.isEmpty) return '未知';
    return centerPrinter['status']?.toString() ??
        (centerPrinter['connected'] == true ? '已连接' : '已断开');
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    statusWatchdog?.cancel();
    telemetryPoll?.cancel();
    controlHeartbeat?.cancel();
    for (final timer in printerSprayTimeouts.values) {
      timer.cancel();
    }
    if (socket != null) socket!.add(jsonEncode(RosMessages.cmdVel(0, 0)));
    socketSub?.cancel();
    socket?.close();
    agentMotionNotifier.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tabs = const [
      _TabItem('首页', Icons.home_rounded),
      _TabItem('任务', Icons.route_rounded),
      _TabItem('监控', Icons.monitor_heart_rounded),
      _TabItem('设置', Icons.tune_rounded),
    ];
    final narrowLayout = MediaQuery.sizeOf(context).width < 720;

    return Scaffold(
      body: SafeArea(
        child: Row(
          children: [
            _SideNavigation(
              tabs: tabs,
              selectedIndex: tabIndex,
              expanded: sideNavExpanded && !narrowLayout,
              device: activeDevice,
              bridgeState: bridgeState,
              lineRunning: lineRunning,
              emergencyStopped: emergencyStopped,
              onEmergencyPressed: _toggleEmergencyStop,
              onToggle: () => setState(() {
                sideNavExpanded = !sideNavExpanded;
              }),
              onSelected: (value) => setState(() {
                tabIndex = value;
                if (value == 0) homeModule = 0;
              }),
            ),
            Expanded(
              child: Stack(
                children: [
                  Column(
                    children: [
                      Expanded(
                        child: AnimatedSwitcher(
                          duration: const Duration(milliseconds: 220),
                          child: _buildPage(),
                        ),
                      ),
                    ],
                  ),
                  Positioned.fill(
                    child: _DraggableAgentBall(onTap: _openAgentSheet),
                  ),
                  if (agentMotionActive)
                    Positioned(
                      left: 16,
                      right: 16,
                      top: 16,
                      child: FilledButton.icon(
                        style: FilledButton.styleFrom(
                          backgroundColor: const Color(0xffdc2626),
                          foregroundColor: Colors.white,
                          minimumSize: const Size.fromHeight(52),
                        ),
                        onPressed: _stopAgentMotion,
                        icon: const Icon(Icons.stop_circle_rounded),
                        label: Text(
                          '停止 AI 控制小车运动'
                          '${agentMotionRemainingMs > 0 ? ' · ${(agentMotionRemainingMs / 1000).ceil()} 秒' : ''}',
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
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
          missionPaused: missionPaused,
          emergencyStopped: emergencyStopped,
          missionStage: missionStage,
          missionFile: missionFile,
          missionCurrentId: missionCurrentId,
          completed: missionCompleted,
          total: missionTotal,
          error: missionError,
          missionFiles: missionFiles,
          missionFilesLoading: missionFilesLoading,
          gridMap: gridMap,
          plannedPaths: _displayedPlannedPaths,
          pathAnnotations: pathAnnotations,
          robotPose: robotPose,
          poseTrace: poseTrace,
          showLivePose: localizationReady,
          onFileChanged: _selectMissionFile,
          onCreateDrawing: _openDrawingEditor,
          onImportJson: _openJsonImporter,
          onImportCad: _importCadDrawing,
          onRefreshFiles: _loadMissionFiles,
          onDeleteFile: _deleteMissionFile,
          onStart: () => _controlMission('start'),
          onPause: () => _controlMission('pause'),
          onResume: () => _controlMission('resume'),
          onCancel: _confirmCancelMission,
          localizationSource: localizationSource,
          localizationValid: localizationValid,
        );
      case 2:
        return _MonitorPage(
          backendOnline: backendOnline,
          rosAvailable: rosAvailable,
          controlReady: controlReady,
          controlGranted: controlGranted,
          driveDeviceConnected: driveDeviceConnected,
          motorDriverReady: motorDriverReady,
          driveTransport: driveTransport,
          driveDevicePath: driveDevicePath,
          telemetryAgeMs: telemetryAgeMs,
          wheelSpeeds: wheelSpeeds,
          motorStatus: motorStatus,
          telemetryContract: telemetryContract,
          telemetryApiOnline: telemetryApiOnline,
          telemetryApiError: telemetryApiError,
          telemetryRequestLatencyMs: telemetryRequestLatencyMs,
          controlChannelConnected: bridgeState == BridgeState.connected,
          battery: battery,
          printerReady: printerReady,
          printerStatus: centerPrinter,
          localizationValid: localizationValid,
          linearVelocity: linearVelocity,
          onRefreshTelemetry: _pollTelemetryContract,
          onRunDiagnosis: _runMonitorDiagnosis,
        );
      case 3:
        return _SettingsPage(
          device: activeDevice,
          localizationSource: localizationSource,
          onAddDevice: _openAddDeviceSheet,
          onOpenDevices: () => setState(() {
            tabIndex = 0;
            homeModule = 3;
          }),
          bridgeState: bridgeState,
          printerStatus: centerPrinterLabel,
          printerStatusData: printerStatus,
          onPrinterChanged: _setNamedPrinterActive,
          onPrinterEnabledChanged: _setNamedPrinterEnabled,
          onPrinterCommand: _sendPrinterCommand,
          onPrinterRawCommand: _sendPrinterRawCommand,
        );
      default:
        return _buildHomePage();
    }
  }

  Future<void> _openDrawingEditor({String? fileName}) async {
    final savedFileName = await Navigator.of(context).push<String>(
      MaterialPageRoute(
        builder: (context) => _DrawingEditorPage(
          device: activeDevice,
          bridgeConnected: bridgeState == BridgeState.connected,
          previewMode: AppConstants.layoutPreviewMode,
          localizationSource: localizationSource,
          initialFileName: fileName,
          existingFileNames: missionFiles,
        ),
      ),
    );
    if (savedFileName == null || !mounted) return;
    setState(() {
      if (!missionFiles.contains(savedFileName))
        missionFiles.add(savedFileName);
    });
    await _selectMissionFile(savedFileName);
  }

  Future<void> _openJsonImporter() async {
    if (AppConstants.layoutPreviewMode) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('布局预览模式不会写入小车图纸')));
      return;
    }
    final fileName = await showDialog<String>(
      context: context,
      builder: (context) => _JsonDrawingDialog(device: activeDevice),
    );
    if (fileName == null || !mounted) return;
    setState(() {
      if (!missionFiles.contains(fileName)) missionFiles.add(fileName);
    });
    await _selectMissionFile(fileName);
  }

  Future<void> _importCadDrawing() async {
    if (AppConstants.layoutPreviewMode) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('布局预览模式不会写入小车图纸')));
      return;
    }
    if (bridgeState != BridgeState.connected) return;
    final unit = await showDialog<String>(
      context: context,
      builder: (context) => SimpleDialog(
        title: const Text('选择 CAD 图纸单位'),
        children: [
          for (final item in const {
            'mm': '毫米（推荐）',
            'cm': '厘米',
            'm': '米',
          }.entries)
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, item.key),
              child: Text(item.value),
            ),
        ],
      ),
    );
    if (unit == null || !mounted) return;
    final picked = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['dxf', 'dwg'],
      withData: true,
    );
    if (picked == null || picked.files.single.bytes == null) return;
    final selected = picked.files.single;
    final boundary = '----XLine${DateTime.now().microsecondsSinceEpoch}';
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 5);
    try {
      final request = await client.postUrl(
        Uri.parse(
          'http://${activeDevice.ip}:${activeDevice.port}/api/drawings/import-cad?unit=$unit',
        ),
      );
      request.headers.contentType = ContentType(
        'multipart',
        'form-data',
        parameters: {'boundary': boundary},
      );
      final name = selected.name.replaceAll(RegExp(r'[^A-Za-z0-9_.-]'), '_');
      request.write(
        '--$boundary\r\nContent-Disposition: form-data; name="file"; filename="$name"\r\nContent-Type: application/octet-stream\r\n\r\n',
      );
      request.add(selected.bytes!);
      request.write('\r\n--$boundary--\r\n');
      final response = await request.close().timeout(
        const Duration(seconds: 30),
      );
      final decoded = jsonDecode(await utf8.decoder.bind(response).join());
      if (!mounted) return;
      if (decoded is Map && decoded['ok'] == true) {
        final fileName = decoded['file_name'].toString();
        setState(() {
          if (!missionFiles.contains(fileName)) missionFiles.add(fileName);
        });
        await _selectMissionFile(fileName);
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('CAD 已转换并导入：$fileName')));
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              decoded is Map
                  ? decoded['message']?.toString() ?? 'CAD 导入失败'
                  : 'CAD 导入失败',
            ),
          ),
        );
      }
    } catch (_) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('CAD 导入失败，请检查后端连接')));
    } finally {
      client.close(force: true);
    }
  }

  List<Map<String, dynamic>> get _displayedPlannedPaths =>
      missionPreviewFile == missionFile ? missionPreviewPaths : plannedPaths;

  Future<void> _selectMissionFile(String fileName) async {
    if (!mounted) return;
    setState(() {
      missionFile = fileName;
      missionPreviewFile = null;
      missionPreviewPaths = const [];
    });
    if (AppConstants.layoutPreviewMode) {
      setState(() {
        missionPreviewFile = fileName;
        missionPreviewPaths = _previewPaths;
        plannedPaths = _previewPaths;
      });
      return;
    }
    if (bridgeState != BridgeState.connected) return;

    final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
    try {
      final uri = Uri.parse(
        'http://${activeDevice.ip}:${activeDevice.port}/api/drawings/${Uri.encodeComponent(fileName)}',
      );
      final response = await (await client.getUrl(
        uri,
      )).close().timeout(const Duration(seconds: 8));
      final decoded = jsonDecode(await utf8.decoder.bind(response).join());
      if (!mounted || missionFile != fileName) return;
      if (decoded is Map && decoded['ok'] == true) {
        setState(() {
          missionPreviewFile = fileName;
          missionPreviewPaths = _asMapList(decoded['planned_paths']);
          poseTrace = const [];
        });
      } else {
        setState(() => _addLog('drawing preview unavailable: $fileName'));
      }
    } catch (error) {
      if (mounted && missionFile == fileName) {
        setState(() => _addLog('drawing preview failed: $error'));
      }
    } finally {
      client.close(force: true);
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
            plannedPaths: _displayedPlannedPaths,
            pathAnnotations: pathAnnotations,
            robotPose: robotPose,
            poseTrace: poseTrace,
            localizationValid: localizationValid,
            localizationSource: localizationSource,
            telemetryAgeMs: telemetryAgeMs,
            mapAgeMs: mapAgeMs,
            pathsAgeMs: pathsAgeMs,
            missionStage: missionStage,
            missionCurrentId: missionCurrentId,
            missionCompleted: missionCompleted,
            missionTotal: missionTotal,
          ),
        );
      case 2:
        return LayoutBuilder(
          builder: (context, constraints) {
            final control = _ControlPage(
              linearSpeed: linearSpeed,
              angularSpeed: angularSpeed,
              onLinearSpeedChanged: (value) =>
                  setState(() => linearSpeed = value),
              onAngularSpeedChanged: (value) =>
                  setState(() => angularSpeed = value),
              onDriveCommand: _sendDriveCommand,
              printerStatus: printerStatus,
              onPrinterChanged: _setNamedPrinterActive,
              fixedLayout: true,
              showPrinterPanel: false,
            );
            if (MediaQuery.sizeOf(context).width >= 840) {
              final realtimeMap = _Panel(
                title: '实时地图',
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      tooltip: '刷新当前位置',
                      onPressed: _refreshLivePosition,
                      icon: const Icon(Icons.gps_fixed_rounded, size: 20),
                    ),
                    IconButton(
                      tooltip: '打开完整地图',
                      onPressed: () => setState(() => homeModule = 1),
                      icon: const Icon(Icons.open_in_full_rounded, size: 20),
                    ),
                  ],
                ),
                child: _RealtimeRobotView(
                  rosAvailable: rosAvailable,
                  pose: liveMapPose,
                  gridMap: liveMapGrid,
                  plannedPaths: liveMapPlannedPaths,
                  poseTrace: liveMapTrace,
                  lineRunning: lineRunning,
                  onTap: () => setState(() => homeModule = 1),
                  height: constraints.hasBoundedHeight
                      ? math.max(260, constraints.maxHeight - 72)
                      : null,
                ),
              );
              final printerPanel = _PrinterTogglePanel(
                status: printerStatus,
                onSprayChanged: _setNamedPrinterActive,
              );
              return _HomeModulePage(
                title: '手动控制 · 地图',
                onBack: () => setState(() => homeModule = 0),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Expanded(flex: 62, child: realtimeMap),
                    const SizedBox(width: 8),
                    Expanded(
                      flex: 38,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Expanded(flex: 28, child: printerPanel),
                          const SizedBox(height: 8),
                          Expanded(flex: 72, child: control),
                        ],
                      ),
                    ),
                  ],
                ),
              );
            }
            return _HomeModulePage(
              title: '手动控制',
              onBack: () => setState(() => homeModule = 0),
              child: Column(
                children: [
                  SizedBox(
                    height: 230,
                    child: _RealtimeRobotView(
                      rosAvailable: rosAvailable,
                      pose: liveMapPose,
                      gridMap: liveMapGrid,
                      plannedPaths: liveMapPlannedPaths,
                      poseTrace: liveMapTrace,
                      lineRunning: lineRunning,
                      onTap: () => setState(() => homeModule = 1),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Expanded(
                    child: _ControlPage(
                      linearSpeed: linearSpeed,
                      angularSpeed: angularSpeed,
                      onLinearSpeedChanged: (value) =>
                          setState(() => linearSpeed = value),
                      onAngularSpeedChanged: (value) =>
                          setState(() => angularSpeed = value),
                      onDriveCommand: _sendDriveCommand,
                      printerStatus: printerStatus,
                      onPrinterChanged: _setNamedPrinterActive,
                    ),
                  ),
                ],
              ),
            );
          },
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
            onDelete: _deleteDevice,
            onTestActive: _connectActiveDevice,
            onDisconnect: _disconnectBridge,
            onProvisionWifi: _openWifiProvisionSheet,
          ),
        );
      default:
        return _DashboardPage(
          device: activeDevice,
          lineRunning: lineRunning,
          bridgeState: bridgeState,
          rosAvailable: rosAvailable,
          backendOnline: backendOnline,
          controlGranted: controlGranted,
          controlOwner: controlOwner,
          controlReady: controlReady,
          driveDeviceConnected: driveDeviceConnected,
          motorDriverReady: motorDriverReady,
          driveTransport: driveTransport,
          driveDevicePath: driveDevicePath,
          linearVelocity: linearVelocity,
          localizationAccuracyMm: localizationAccuracyMm,
          telemetryAgeMs: telemetryAgeMs,
          robotPose: showRelativeMap ? liveMapPose : robotPose,
          gridMap: showRelativeMap ? liveMapGrid : gridMap,
          plannedPaths: showRelativeMap
              ? liveMapPlannedPaths
              : _displayedPlannedPaths,
          poseTrace: showRelativeMap ? liveMapTrace : poseTrace,
          obstacleDistances: obstacleDistances,
          obstacleAgeMs: obstacleAgeMs,
          wheelSpeeds: wheelSpeeds,
          motorStatus: motorStatus,
          battery: battery,
          localizationReady: localizationReady,
          localizationSource: localizationSource,
          localizationCalibration: localizationCalibration,
          localizationCalibrationAvailable: localizationCalibrationAvailable,
          ln150Ready: ln150Ready,
          preferTotalStation: preferTotalStation,
          showRelativeMap: showRelativeMap,
          onLnCommand: _sendLnCommand,
          onTotalStationChanged: _setTotalStationPreference,
          onMapModeChanged: _setMapMode,
          onRefreshMap: _refreshLiveMap,
          onCalibrateLocalization: () =>
              _sendBridge(RosMessages.calibrateLocalization()),
          printerStatus: centerPrinterLabel,
          printerStatusData: printerStatus,
          onPrinterChanged: _setNamedPrinterActive,
          onPrinterEnabledChanged: _setNamedPrinterEnabled,
          onPrinterCommand: _sendPrinterCommand,
          onPrinterRawCommand: _sendPrinterRawCommand,
          linearSpeed: linearSpeed,
          angularSpeed: angularSpeed,
          onLinearSpeedChanged: (value) => setState(() => linearSpeed = value),
          onAngularSpeedChanged: (value) =>
              setState(() => angularSpeed = value),
          onDriveCommand: _sendDriveCommand,
          missionReady: missionReady,
          onStartMission: () =>
              _controlMission(lineRunning ? 'cancel' : 'start'),
          onAddDevice: _openAddDeviceSheet,
          onConnect: _connectActiveDevice,
          onOpenMap: () => setState(() => homeModule = 1),
          onOpenControl: () => setState(
            () => homeControlOverlayVisible = !homeControlOverlayVisible,
          ),
          controlOverlayVisible: homeControlOverlayVisible,
          onToggleControlOverlay: () => setState(
            () => homeControlOverlayVisible = !homeControlOverlayVisible,
          ),
          onOpenDrawingEditor: _openDrawingEditor,
          onOpenDevices: () => setState(() => homeModule = 3),
        );
    }
  }

  Future<void> _openAgentSheet() async {
    var agentPreviewPaths = const <Map<String, dynamic>>[];
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: Colors.white,
      constraints: const BoxConstraints(maxWidth: double.infinity),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => StatefulBuilder(
        builder: (context, setSheetState) => SizedBox(
          width: double.infinity,
          height: MediaQuery.sizeOf(context).height * 0.92,
          child: Column(
            children: [
              Center(
                child: Container(
                  width: 36,
                  height: 4,
                  margin: const EdgeInsets.only(top: 8),
                  decoration: BoxDecoration(
                    color: const Color(0xff334155),
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 8, 8, 2),
                child: Row(
                  children: [
                    Container(
                      width: 34,
                      height: 34,
                      decoration: BoxDecoration(
                        color: const Color(0xff172554),
                        borderRadius: BorderRadius.circular(9),
                      ),
                      child: const Icon(
                        Icons.smart_toy_rounded,
                        size: 19,
                        color: Color(0xff60a5fa),
                      ),
                    ),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Text(
                        '智能助手',
                        style: TextStyle(
                          fontSize: 16,
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
                child: LayoutBuilder(
                  builder: (context, constraints) {
                    final wide = MediaQuery.sizeOf(context).width >= 840;
                    final agent = _AgentPage(
                      device: activeDevice,
                      bridgeConnected: bridgeState == BridgeState.connected,
                      previewMode: AppConstants.layoutPreviewMode,
                      agentMotionNotifier: agentMotionNotifier,
                      onStopAgentMotion: _stopAgentMotion,
                      clientId: controlClientId,
                      printerStatus: printerStatus,
                      onPrinterSprayChanged: (printerName, spraying) {
                        _setNamedPrinterActive(printerName, spraying);
                        setSheetState(() {});
                      },
                      onPreviewPathsChanged: (paths) {
                        setSheetState(
                          () => agentPreviewPaths = List.unmodifiable(paths),
                        );
                      },
                    );
                    if (!wide) return agent;
                    final usesTotalStation =
                        localizationSource == 'ln150_imu' && ln150Ready;
                    final relativePlanning = !usesTotalStation;
                    final planningGrid = usesTotalStation && gridMap.isNotEmpty
                        ? gridMap
                        : <String, dynamic>{
                            'width': 20,
                            'height': 20,
                            'resolution': 0.5,
                            'origin_x': -5.0,
                            'origin_y': -5.0,
                            'frame_id': usesTotalStation
                                ? 'map'
                                : 'relative_map',
                          };
                    final planningPose = usesTotalStation
                        ? robotPose
                        : const <String, dynamic>{
                            'x': 0.0,
                            'y': 0.0,
                            'theta': 0.0,
                            'frame_id': 'relative_map',
                          };
                    final planningMap = _Panel(
                      title: usesTotalStation
                          ? 'AI 规划路径 · 全站仪定位'
                          : 'AI 规划路径 · 相对定位',
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          _StatusChip(
                            text: relativePlanning ? '车头为坐标原点' : '全局坐标系',
                            color: relativePlanning
                                ? const Color(0xff2563eb)
                                : const Color(0xff16a66a),
                          ),
                          const SizedBox(width: 6),
                          _StatusChip(
                            text: agentPreviewPaths.isEmpty
                                ? '等待 JSON'
                                : '${agentPreviewPaths.length} 段路径',
                            color: agentPreviewPaths.isEmpty
                                ? const Color(0xff64748b)
                                : const Color(0xff16a66a),
                          ),
                          IconButton(
                            tooltip: '清除规划路径',
                            onPressed: agentPreviewPaths.isEmpty
                                ? null
                                : () => setSheetState(
                                    () => agentPreviewPaths = const [],
                                  ),
                            icon: const Icon(Icons.clear_all_rounded, size: 20),
                          ),
                        ],
                      ),
                      child: _RealtimeRobotView(
                        rosAvailable: usesTotalStation && rosAvailable,
                        pose: planningPose,
                        gridMap: planningGrid,
                        plannedPaths: agentPreviewPaths,
                        poseTrace: const [],
                        lineRunning: false,
                        onTap: () {},
                        showPoseOverlay: usesTotalStation || relativePlanning,
                        height: constraints.hasBoundedHeight
                            ? math.max(260, constraints.maxHeight - 48)
                            : null,
                      ),
                    );
                    return Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(flex: 44, child: agent),
                        const VerticalDivider(width: 1),
                        Expanded(flex: 56, child: planningMap),
                      ],
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _setTotalStationPreference(bool enabled) {
    if (enabled && !ln150Ready) {
      setState(() {
        preferTotalStation = false;
        showRelativeMap = false;
        connectionMessage = '未检测到全站仪，继续使用实时地图';
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('未检测到全站仪，已保持实时地图模式')));
      return;
    }
    setState(() {
      preferTotalStation = enabled;
      showRelativeMap = enabled;
      connectionMessage = enabled ? '已选择全站仪相对地图' : '已选择实时地图';
    });
  }

  void _setMapMode(bool relative) {
    if (relative && !(ln150Ready && localizationSource == 'ln150_imu')) {
      setState(() => showRelativeMap = false);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('相对地图需要全站仪定位数据，已保持实时地图')));
      return;
    }
    setState(() => showRelativeMap = relative);
  }

  void _refreshLivePosition() {
    final x = (realtimePose['x'] as num?)?.toDouble() ?? 0;
    final y = (realtimePose['y'] as num?)?.toDouble() ?? 0;
    setState(() {
      liveMapOriginX = x;
      liveMapOriginY = y;
      liveMapTrace = const [
        <double>[0, 0],
      ];
    });
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('已清除轨迹，并将当前位置设置为原点')));
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
      devices.add(
        RoverDevice(
          name: device.name,
          ip: device.ip,
          port: device.port,
          domainId: device.domainId,
          type: device.type,
          connected: false,
        ),
      );
      selectedDeviceIndex = devices.length - 1;
      connectionMessage = '已添加并连接 ${device.name}';
      tabIndex = 0;
      homeModule = 3;
    });
    unawaited(_persistDevices());
    unawaited(_connectActiveDevice());
  }

  Future<Map<String, dynamic>> _networkRequest(
    String path, {
    String method = 'GET',
    Map<String, dynamic>? body,
  }) async {
    if (!activeDevice.isConfigured) {
      throw StateError('请先添加并连接小车');
    }
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 5);
    try {
      final uri = Uri.parse(
        'http://${activeDevice.ip}:${activeDevice.port}$path',
      );
      final request = method == 'POST'
          ? await client.postUrl(uri)
          : await client.getUrl(uri);
      if (body != null) {
        request.headers.contentType = ContentType.json;
        request.write(jsonEncode(body));
      }
      final response = await request.close().timeout(
        const Duration(seconds: 25),
      );
      final decoded = jsonDecode(await response.transform(utf8.decoder).join());
      if (decoded is! Map) throw const FormatException('网络接口响应格式无效');
      return Map<String, dynamic>.from(decoded);
    } finally {
      client.close(force: true);
    }
  }

  Future<void> _openWifiProvisionSheet() async {
    if (!activeDevice.isConfigured) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('请先添加小车并连接到初始热点')));
      return;
    }
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xfff8fafc),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(14)),
      ),
      builder: (context) => _WifiProvisionSheet(
        device: activeDevice,
        onStatus: () => _networkRequest('/api/network/status'),
        onScan: () => _networkRequest('/api/network/wifi'),
        onConnect:
            ({
              required String ssid,
              required String password,
              required bool hidden,
            }) => _networkRequest(
              '/api/network/wifi',
              method: 'POST',
              body: {'ssid': ssid, 'password': password, 'hidden': hidden},
            ),
      ),
    );
  }

  /// 将指定设备设为当前设备，然后重新连接。
  void _connectDevice(int selectedIndex) {
    setState(() {
      selectedDeviceIndex = selectedIndex;
      for (var index = 0; index < devices.length; index++) {
        final device = devices[index];
        devices[index] = RoverDevice(
          name: device.name,
          ip: device.ip,
          port: device.port,
          domainId: device.domainId,
          type: device.type,
          connected: false,
        );
      }
      connectionMessage = '已切换到 ${devices[selectedIndex].name}';
    });
    unawaited(_persistDevices());
    unawaited(_connectActiveDevice());
  }

  Future<void> _deleteDevice(int index) async {
    if (index < 0 || index >= devices.length) return;
    final device = devices[index];
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除设备'),
        content: Text('确认删除“${device.name}”？此操作只删除 App 中的连接配置。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xffdc2626),
            ),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    final deletingSelected = index == selectedDeviceIndex;
    if (deletingSelected) await _disconnectBridge();
    if (!mounted || index >= devices.length) return;
    setState(() {
      devices.removeAt(index);
      if (devices.isEmpty) {
        selectedDeviceIndex = 0;
        bridgeState = BridgeState.disconnected;
        connectionMessage = '尚未配置小车，请先添加设备';
      } else if (index < selectedDeviceIndex) {
        selectedDeviceIndex--;
        connectionMessage = '已删除 ${device.name}';
      } else if (deletingSelected) {
        selectedDeviceIndex = index.clamp(0, devices.length - 1);
        connectionMessage = '已删除 ${device.name}，请选择是否连接当前设备';
      } else {
        connectionMessage = '已删除 ${device.name}';
      }
      _addLog('device deleted ${device.name}');
    });
    unawaited(_persistDevices());
  }

  /// 关闭旧连接，然后连接当前设备的 WebSocket Bridge。
  /// 成功后订阅核心 ROS2 话题；4 秒内未成功则进入失败状态。
  Future<void> _connectActiveDevice() async {
    if (AppConstants.layoutPreviewMode) {
      _enableLayoutPreview();
      if (mounted) setState(() {});
      return;
    }
    if (!activeDevice.isConfigured) {
      setState(() {
        bridgeState = BridgeState.disconnected;
        _setActiveDeviceConnected(false);
        connectionMessage = 'Please add and configure a real vehicle first';
        _addLog('connect blocked: no configured device');
      });
      return;
    }
    await socketSub?.cancel();
    await socket?.close();
    setState(() {
      bridgeState = BridgeState.connecting;
      liveMapOriginX = null;
      liveMapOriginY = null;
      liveMapTrace = const [
        <double>[0, 0],
      ];
      _setActiveDeviceConnected(false);
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
          controlHeartbeat?.cancel();
          setState(() {
            bridgeState = BridgeState.disconnected;
            _setActiveDeviceConnected(false);
            backendOnline = false;
            rosAvailable = false;
            controlReady = false;
            controlGranted = false;
            lineRunning = false;
            connectionMessage = 'Bridge 已断开';
            _addLog('bridge closed');
          });
        },
        onError: (error) {
          if (!mounted) return;
          controlHeartbeat?.cancel();
          setState(() {
            bridgeState = BridgeState.failed;
            _setActiveDeviceConnected(false);
            backendOnline = false;
            rosAvailable = false;
            controlReady = false;
            controlGranted = false;
            lineRunning = false;
            connectionMessage = 'Bridge 错误：$error';
            _addLog('error $error');
          });
        },
      );
      setState(() {
        bridgeState = BridgeState.connected;
        _setActiveDeviceConnected(true);
        connectionMessage = '已连接 ${activeDevice.name}';
        _addLog('connected');
      });
      _subscribeCoreTopics();
      _sendBridge(RosMessages.claimControl());
      controlHeartbeat?.cancel();
      controlHeartbeat = Timer.periodic(const Duration(seconds: 1), (_) {
        _sendBridge(RosMessages.controlHeartbeat());
      });
      _startTelemetryPolling();
      unawaited(_loadMissionFiles());
    } catch (error) {
      setState(() {
        bridgeState = BridgeState.failed;
        _setActiveDeviceConnected(false);
        connectionMessage = '连接失败：请确认小车端 Bridge 已启动';
        _addLog('connect failed $error');
      });
    }
  }

  void _startTelemetryPolling() {
    telemetryPoll ??= Timer.periodic(const Duration(seconds: 2), (_) {
      unawaited(_pollTelemetryContract());
    });
    unawaited(_pollTelemetryContract());
  }

  Future<void> _pollTelemetryContract() async {
    if (!mounted ||
        AppConstants.layoutPreviewMode ||
        !activeDevice.isConfigured ||
        telemetryPollInFlight) {
      return;
    }
    telemetryPollInFlight = true;
    final stopwatch = Stopwatch()..start();
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 2);
    try {
      final request = await client.getUrl(
        Uri.parse(
          'http://${activeDevice.ip}:${activeDevice.port}/api/telemetry',
        ),
      );
      final response = await request.close().timeout(
        const Duration(seconds: 3),
      );
      stopwatch.stop();
      if (response.statusCode != 200) {
        throw HttpException('监控接口返回 HTTP ${response.statusCode}');
      }
      final payload = jsonDecode(await response.transform(utf8.decoder).join());
      if (!mounted || payload is! Map) return;
      final telemetry = _asStringMap(payload['telemetry']);
      if (telemetry.isEmpty) return;
      final runtime = _asStringMap(telemetry['runtime']);
      final drive = _asStringMap(telemetry['drive']);
      final localization = _asStringMap(telemetry['localization']);
      final energy = _asStringMap(telemetry['energy']);
      final printerEnvelope = _asStringMap(payload['printer']);
      final printers = _asStringMap(printerEnvelope['printers']);
      final center = _asStringMap(printers['printer_center']);
      if (!mounted) return;
      setState(() {
        telemetryContract = telemetry;
        telemetryApiOnline = true;
        telemetryApiError = '';
        telemetryRequestLatencyMs = stopwatch.elapsedMilliseconds;
        backendOnline = runtime['online'] == true;
        rosAvailable = runtime['ros_available'] == true;
        controlReady = runtime['control_ready'] == true;
        telemetryAgeMs = (runtime['telemetry_age_ms'] as num?)?.toInt();
        driveDeviceConnected = drive['device_connected'] == true;
        motorDriverReady = drive['driver_ready'] == true;
        driveTransport = drive['transport']?.toString() ?? driveTransport;
        driveDevicePath = drive['device_path']?.toString() ?? driveDevicePath;
        wheelSpeeds = _asStringMap(drive['wheel_speeds']);
        motorStatus = _asStringMap(drive['motor_status']);
        linearVelocity = (drive['linear_velocity'] as num?)?.toDouble();
        localizationValid = localization['valid'] == true;
        localizationSource =
            localization['source']?.toString() ?? localizationSource;
        localizationAccuracyMm = (localization['accuracy_mm'] as num?)
            ?.toDouble();
        robotPose = _asStringMap(localization['pose']);
        odometry = _asStringMap(localization['odometry']);
        battery = (energy['battery_percent'] as num?)?.toInt();
        if (center.isNotEmpty) {
          printerReady =
              center['connected'] == true && center['online'] == true;
          printerStatus = {
            ...printerStatus,
            'printer_center': {
              ...center,
              'is_online': center['online'] == true,
              'spray_state': center['lifecycle']?.toString() ?? 'idle',
              'spray_error': center['error']?.toString() ?? '',
            },
          };
        }
      });
    } catch (error) {
      if (mounted) {
        stopwatch.stop();
        final message = '监控接口不可达：$error';
        if (telemetryApiOnline || telemetryApiError != message) {
          setState(() {
            telemetryApiOnline = false;
            telemetryApiError = message;
          });
        }
      }
    } finally {
      telemetryPollInFlight = false;
      client.close(force: true);
    }
  }

  Future<Map<String, dynamic>> _runMonitorDiagnosis() async {
    if (!activeDevice.isConfigured) {
      throw StateError('未配置小车地址，无法发起真实诊断');
    }
    final snapshot = <String, Object?>{
      'telemetry': telemetryContract,
      'app_link': {
        'telemetry_api_online': telemetryApiOnline,
        'telemetry_request_latency_ms': telemetryRequestLatencyMs,
        'control_websocket_connected': bridgeState == BridgeState.connected,
      },
      'observed_at': DateTime.now().toIso8601String(),
    };
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 5);
    try {
      final request = await client.postUrl(
        Uri.parse(
          'http://${activeDevice.ip}:${activeDevice.port}/api/monitor/diagnose',
        ),
      );
      request.headers.contentType = ContentType.json;
      request.write(jsonEncode({'snapshot': snapshot}));
      final response = await request.close().timeout(
        const Duration(seconds: 20),
      );
      final body = jsonDecode(await response.transform(utf8.decoder).join());
      if (response.statusCode != 200 || body is! Map || body['ok'] != true) {
        final message = body is Map ? body['message']?.toString() : null;
        throw HttpException(message ?? '诊断接口返回 HTTP ${response.statusCode}');
      }
      return Map<String, dynamic>.from(body);
    } finally {
      client.close(force: true);
    }
  }

  Future<void> _loadMissionFiles() async {
    if (AppConstants.layoutPreviewMode) return;
    if (bridgeState != BridgeState.connected || missionFilesLoading) return;
    setState(() => missionFilesLoading = true);
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
    try {
      final request = await client.getUrl(
        Uri.parse(
          'http://${activeDevice.ip}:${activeDevice.port}/api/drawings',
        ),
      );
      final response = await request.close().timeout(
        const Duration(seconds: 8),
      );
      final decoded = jsonDecode(await utf8.decoder.bind(response).join());
      if (decoded is! Map || decoded['ok'] != true) return;
      final remoteFiles = ((decoded['files'] as List?) ?? const [])
          .map((item) => item.toString())
          .where((file) => file.endsWith('.json'));
      if (!mounted) return;
      var selectedFile = missionFile;
      setState(() {
        const builtIn = [
          'test_pattern.json',
          'huanong_skeleton.json',
          'square_image.json',
        ];
        missionFiles
          ..clear()
          ..addAll({...builtIn, ...remoteFiles});
        if (!missionFiles.contains(missionFile)) {
          missionFile = missionFiles.first;
          selectedFile = missionFile;
        }
        connectionMessage = '已同步 ${missionFiles.length} 个任务图纸';
      });
      await _selectMissionFile(selectedFile);
    } catch (error) {
      if (mounted) {
        setState(() => _addLog('drawing sync failed $error'));
      }
    } finally {
      client.close(force: true);
      if (mounted) {
        setState(() => missionFilesLoading = false);
      }
    }
  }

  Future<void> _deleteMissionFile(String fileName) async {
    if (AppConstants.layoutPreviewMode) {
      if (mounted) {
        setState(() => _addLog('preview blocked drawing delete $fileName'));
      }
      return;
    }
    const builtIn = {
      'test_pattern.json',
      'huanong_skeleton.json',
      'square_image.json',
    };
    if (builtIn.contains(fileName)) {
      return;
    }
    if (lineRunning && missionFile == fileName) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('任务正在执行，不能删除当前图纸')));
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除图纸'),
        content: Text('确定删除 $fileName 吗？此操作无法撤销。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xffdc2626),
            ),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
    try {
      final uri = Uri.parse(
        'http://${activeDevice.ip}:${activeDevice.port}/api/drawings/${Uri.encodeComponent(fileName)}',
      );
      final request = await client.deleteUrl(uri);
      final response = await request.close().timeout(
        const Duration(seconds: 8),
      );
      final decoded = jsonDecode(await utf8.decoder.bind(response).join());
      if (!mounted) return;
      if (decoded is Map && decoded['ok'] == true) {
        var nextFile = missionFile;
        setState(() {
          missionFiles.remove(fileName);
          if (missionFile == fileName) {
            missionFile = 'test_pattern.json';
            nextFile = missionFile;
          }
        });
        if (fileName == missionPreviewFile || fileName == nextFile) {
          await _selectMissionFile(nextFile);
        }
        if (!mounted) return;
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('图纸已删除')));
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              decoded is Map
                  ? decoded['message']?.toString() ?? '删除失败'
                  : '删除失败',
            ),
          ),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('删除失败，请检查后端连接')));
      }
    } finally {
      client.close(force: true);
    }
  }

  /// 主动断开 WebSocket，清理订阅并将界面设为离线。
  Future<void> _disconnectBridge() async {
    if (AppConstants.layoutPreviewMode) {
      if (mounted) {
        setState(() => _addLog('preview blocked disconnect request'));
      }
      return;
    }
    _sendBridge(RosMessages.cmdVel(0, 0));
    _sendBridge(RosMessages.releaseControl());
    controlHeartbeat?.cancel();
    await socketSub?.cancel();
    await socket?.close();
    setState(() {
      socket = null;
      socketSub = null;
      bridgeState = BridgeState.disconnected;
      _setActiveDeviceConnected(false);
      backendOnline = false;
      rosAvailable = false;
      controlReady = false;
      lineRunning = false;
      agentMotionActive = false;
      agentMotionRemainingMs = 0;
      agentMotionNotifier.value = -1;
      controlGranted = false;
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
      final operation = envelope['op']?.toString();
      if (operation == 'control_response') {
        final granted =
            envelope['ok'] == true &&
            envelope['owner']?.toString() == controlClientId;
        setState(() {
          controlOwner = envelope['owner']?.toString();
          controlGranted = granted;
          if (!controlGranted) connectionMessage = '控制权正被其他客户端占用';
        });
        if (granted && releaseEmergencyAfterControlClaim) {
          releaseEmergencyAfterControlClaim = false;
          // Give the backend one event-loop turn to commit the lease before
          // authorizing the safety-state transition.
          Future<void>.delayed(const Duration(milliseconds: 80), () {
            if (!mounted || bridgeState != BridgeState.connected) return;
            _sendBridge(RosMessages.emergencyStop(false));
          });
        }
        if (!granted && releaseEmergencyAfterControlClaim) {
          releaseEmergencyAfterControlClaim = false;
          emergencyReleaseInProgress = false;
          _showControlWarning(
            '取得控制权失败：${envelope['message']?.toString() ?? '控制权被其他客户端占用'}',
          );
        }
        return;
      }
      if (operation == 'emergency_stop_response') {
        final accepted = envelope['ok'] == true;
        final active = envelope['active'] != false;
        setState(() {
          if (accepted) {
            emergencyStopped = active;
            emergencyReleaseInProgress = false;
          }
        });
        if (!accepted) {
          emergencyReleaseInProgress = false;
          _showControlWarning(
            '解除急停失败：${envelope['message']?.toString() ?? '后端拒绝了请求'}',
          );
        }
        return;
      }
      if (operation == 'service_response' || operation == 'mission_response') {
        final service = envelope['service']?.toString() ?? '';
        final message = envelope['message']?.toString().trim() ?? '';
        if (envelope['ok'] == true) {
          if (service.contains('printer')) {
            _showControlNotice(message.isEmpty ? '喷码机指令已发送' : message);
          }
        } else {
          final prefix = service.contains('printer') ? '喷码机操作失败：' : '';
          _showControlWarning('$prefix${message.isEmpty ? '后端操作失败' : message}');
        }
        return;
      }
      if (operation == 'printer_spray_response') {
        final message = envelope['message']?.toString().trim() ?? '';
        final printerName = envelope['printer_name']?.toString() ?? 'center';
        if (envelope['ok'] == true) {
          _showControlNotice(message.isEmpty ? '喷墨状态已更新' : message);
        } else {
          setState(() {
            printerSprayPending.remove(printerName);
            printerSprayTimeouts.remove(printerName)?.cancel();
            final key = 'printer_$printerName';
            final current = _asStringMap(printerStatus[key]);
            printerStatus = {
              ...printerStatus,
              key: {
                ...current,
                'spray_state': 'error',
                'spray_error': message.isEmpty ? '后端拒绝了请求' : message,
              },
            };
          });
          _showControlWarning(
            '喷墨操作失败：${message.isEmpty ? '后端拒绝了请求' : message}',
          );
        }
        return;
      }
      if (operation != null &&
          operation != 'status' &&
          operation != 'control_heartbeat_response') {
        return;
      }
      if (operation == 'control_heartbeat_response') {
        if (envelope['ok'] != true) {
          setState(() => controlGranted = false);
          _sendBridge(RosMessages.claimControl());
        }
        return;
      }
      final rawStatus = envelope['op'] == 'status' ? envelope['msg'] : envelope;
      if (rawStatus is! Map) return;
      final status = Map<String, dynamic>.from(rawStatus);
      final parsedVehicleStatus = VehicleStatus.fromEnvelope(status);
      statusWatchdog?.cancel();
      statusWatchdog = Timer(const Duration(seconds: 8), () {
        if (!mounted) return;
        setState(() {
          backendOnline = false;
          rosAvailable = false;
          controlReady = false;
          agentMotionActive = false;
          agentMotionRemainingMs = 0;
          agentMotionNotifier.value = -1;
          _setActiveDeviceConnected(false);
          connectionMessage = '状态数据超时，控制已锁定';
        });
      });
      setState(() {
        _setActiveDeviceConnected(true);
        vehicleStatus = parsedVehicleStatus;
        rosAvailable = parsedVehicleStatus.rosAvailable;
        backendOnline = parsedVehicleStatus.online;
        emergencyStopped = parsedVehicleStatus.emergencyStopped;
        controlOwner = status['control_owner']?.toString();
        controlGranted = controlOwner == controlClientId;
        controlReady = parsedVehicleStatus.controlReady;
        agentMotionActive = status['agent_motion_active'] == true;
        agentMotionRemainingMs =
            (status['agent_motion_remaining_ms'] as num?)?.toInt() ?? 0;
        agentMotionNotifier.value = agentMotionActive
            ? agentMotionRemainingMs
            : -1;
        driveDeviceConnected = status['drive_device_connected'] == true;
        motorDriverReady = status['motor_driver_ready'] == true;
        driveTransport = status['drive_transport']?.toString() ?? 'socketcan';
        driveDevicePath = status['drive_device_path']?.toString() ?? 'can0';
        missionNodesReady = status['mission_nodes_ready'] == true;
        localizationValid = parsedVehicleStatus.localizationValid;
        localizationSource = parsedVehicleStatus.localizationSource;
        ln150Ready = status['ln150_ready'] == true;
        if (!ln150Ready && preferTotalStation) {
          preferTotalStation = false;
          showRelativeMap = false;
        }
        printerReady = status['printer_ready'] == true;
        linearVelocity = (status['linear_velocity'] as num?)?.toDouble();
        localizationAccuracyMm = (status['localization_accuracy_mm'] as num?)
            ?.toDouble();
        telemetryAgeMs = (status['telemetry_age_ms'] as num?)?.toInt();
        robotPose = _asStringMap(status['robot_pose']);
        _appendLiveMapPoint();
        odometry = _asStringMap(status['odometry']);
        reflectorPosition = _asStringMap(status['reflector_position']);
        gridMap = _asStringMap(status['grid_map']);
        plannedPaths = _asMapList(status['planned_paths']);
        pathAnnotations = _asMapList(status['path_annotations']);
        mapAgeMs = (status['map_age_ms'] as num?)?.toInt();
        pathsAgeMs = (status['paths_age_ms'] as num?)?.toInt();
        poseTrace = _asPointList(status['pose_trace']);
        final incomingPrinterStatus = _asStringMap(status['printer_status']);
        final completedPrinterRequests = <String>[];
        for (final entry in printerSprayPending.entries) {
          final key = 'printer_${entry.key}';
          final current = _asStringMap(incomingPrinterStatus[key]);
          final state = current['spray_state']?.toString() ?? '';
          final reachedTarget = current['spraying'] == entry.value;
          if (reachedTarget || state == 'error' || state == 'disconnected') {
            completedPrinterRequests.add(entry.key);
          } else {
            incomingPrinterStatus[key] = {
              ...current,
              'spray_state': entry.value ? 'starting' : 'stopping',
            };
          }
        }
        for (final name in completedPrinterRequests) {
          printerSprayPending.remove(name);
          printerSprayTimeouts.remove(name)?.cancel();
        }
        printerStatus = incomingPrinterStatus;
        obstacleDistances = _asStringMap(status['obstacle_distances']);
        obstacleAgeMs = (status['obstacle_age_ms'] as num?)?.toInt();
        wheelSpeeds = _asStringMap(status['wheel_speeds']);
        motorStatus = _asStringMap(status['motor_status']);
        battery = (status['battery'] as num?)?.toInt();
        localizationCalibration =
            status['localization_calibration']?.toString() ?? 'idle';
        localizationCalibrationAvailable =
            status['localization_calibration_available'] == true;
        final center = _asStringMap(printerStatus['printer_center']);
        if (center['enabled'] is bool) {
          printerEnabled = center['enabled'] as bool;
        }
        missionStage = status['mission_stage']?.toString() ?? 'idle';
        missionPaused = status['mission_paused'] == true;
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

  List<List<double>> _asPointList(Object? value) {
    if (value is! List) return const [];
    return value
        .whereType<List>()
        .where(
          (point) => point.length >= 2 && point[0] is num && point[1] is num,
        )
        .map(
          (point) => [
            (point[0] as num).toDouble(),
            (point[1] as num).toDouble(),
          ],
        )
        .toList();
  }

  /// 连接成功后订阅 [AppConstants.coreTopics] 中的所有话题。
  void _subscribeCoreTopics() {
    for (final topic in AppConstants.coreTopics) {
      _sendBridge(RosMessages.subscribe(topic));
    }
  }

  /// 将线速度和角速度转成 `/cmd_vel` 指令。
  void _sendDriveCommand(double linear, double angular) {
    if (AppConstants.layoutPreviewMode) {
      setState(() => _addLog('preview blocked drive $linear $angular'));
      return;
    }
    if ((linear != 0 || angular != 0) && !controlGranted) {
      _showControlWarning('当前 App 尚未取得小车控制权');
      return;
    }
    if (emergencyStopped && (linear != 0 || angular != 0)) {
      _showControlWarning('急停已锁定，请确认安全后再解除');
      return;
    }
    if ((linear != 0 || angular != 0) && !controlReady) {
      _showControlWarning('CAN 接口或电机驱动尚未就绪');
      return;
    }
    // Keep the operator-facing signs all the way to ROS2:
    // linear.x > 0 is forward and angular.z > 0 is left.
    // The xline_ws3 driver already uses this standard convention, so do not
    // invert here. AI motion uses the same convention in the backend.
    _sendBridge(RosMessages.cmdVel(linear, angular));
  }

  void _stopAgentMotion() {
    if (AppConstants.layoutPreviewMode) {
      setState(() {
        agentMotionActive = false;
        agentMotionRemainingMs = 0;
        agentMotionNotifier.value = -1;
        _addLog('preview blocked stop agent motion');
      });
      return;
    }
    _sendBridge(RosMessages.stopAgentMotion());
    setState(() {
      agentMotionActive = false;
      agentMotionRemainingMs = 0;
      agentMotionNotifier.value = -1;
      _addLog('operator stopped AI motion');
    });
  }

  void _showControlWarning(String message) {
    final now = DateTime.now();
    if (lastControlWarningAt != null &&
        now.difference(lastControlWarningAt!) < const Duration(seconds: 2)) {
      return;
    }
    lastControlWarningAt = now;
    final messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    messenger.showSnackBar(
      SnackBar(content: Text(message), duration: const Duration(seconds: 2)),
    );
  }

  /// 调用喷码机指令，[action] 例如 `start_print` 或 `stop_print`。
  void _sendPrinterCommand(String printerName, String action) {
    if (bridgeState != BridgeState.connected) {
      _showControlWarning('小车未连接，无法发送喷码机指令');
      return;
    }
    _showControlNotice(action == 'test_print' ? '正在发送喷码测试指令…' : '正在发送喷码机指令…');
    _sendBridge(RosMessages.printerCommand(action, printerName: printerName));
  }

  void _showControlNotice(String message) {
    final messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    messenger.showSnackBar(
      SnackBar(content: Text(message), duration: const Duration(seconds: 2)),
    );
  }

  void _setNamedPrinterActive(String printerName, bool active) {
    if (bridgeState != BridgeState.connected) {
      _showControlWarning('小车未连接，无法切换喷墨');
      return;
    }
    setState(() {
      printerSprayPending[printerName] = active;
      if (printerName == 'center') {
        printerEnabled = active;
      }
      final key = 'printer_$printerName';
      final current = _asStringMap(printerStatus[key]);
      printerStatus = {
        ...printerStatus,
        key: {
          ...current,
          'spray_state': active ? 'starting' : 'stopping',
          'spray_error': '',
        },
      };
    });
    printerSprayTimeouts.remove(printerName)?.cancel();
    printerSprayTimeouts[printerName] = Timer(const Duration(seconds: 30), () {
      if (!mounted || printerSprayPending[printerName] != active) return;
      setState(() {
        printerSprayPending.remove(printerName);
        printerSprayTimeouts.remove(printerName);
        final key = 'printer_$printerName';
        final current = _asStringMap(printerStatus[key]);
        printerStatus = {
          ...printerStatus,
          key: {
            ...current,
            'spraying': false,
            'spray_state': 'error',
            'spray_error': active ? '喷墨开启超时，请重试' : '喷墨停止超时，请重试',
          },
        };
      });
      if (active && bridgeState == BridgeState.connected) {
        _sendBridge(RosMessages.printerSpray(false, printerName: printerName));
      }
      _showControlWarning(active ? '喷墨开启超时，已发送停止保护' : '喷墨停止超时');
    });
    _sendBridge(RosMessages.printerSpray(active, printerName: printerName));
  }

  void _setNamedPrinterEnabled(String printerName, bool enabled) {
    _sendBridge(RosMessages.printerEnabled(enabled, printerName: printerName));
  }

  void _sendPrinterRawCommand(String printerName, String jsonData) {
    _sendBridge(
      RosMessages.printerRawCommand(jsonData, printerName: printerName),
    );
  }

  /// 发送 LN150 命令类型，其数字含义须与小车端定义一致。
  void _sendLnCommand(int commandType) {
    _sendBridge(RosMessages.lnCommand(commandType));
  }

  /// 启动或停止划线任务，并联动喷码机与底盘停车。
  /// 离线时会直接拦截，不会修改任务状态。
  void _controlMission(String action) {
    if (AppConstants.layoutPreviewMode) {
      setState(() => _addLog('preview blocked mission $action'));
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('布局预览模式不会启动真实任务')));
      return;
    }
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
    if ((action == 'start' || action == 'resume') && !missionReady) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('定位或喷码设备尚未上报，任务暂不可执行')));
      return;
    }
    _sendBridge(RosMessages.missionAction(action, fileName: missionFile));
    if (action == 'pause' || action == 'cancel') {
      _sendDriveCommand(0, 0);
    }
  }

  Future<void> _confirmCancelMission() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('取消当前任务'),
        content: const Text('小车将立即停车，当前任务进度会保留在历史状态中。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('继续任务'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xffdc2626),
            ),
            child: const Text('取消并停车'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      _controlMission('cancel');
    }
  }

  Future<void> _toggleEmergencyStop() async {
    if (!emergencyStopped) {
      _sendBridge(RosMessages.cmdVel(0, 0));
      _sendBridge(RosMessages.emergencyStop(true));
      setState(() => emergencyStopped = true);
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('解除急停'),
        content: const Text('请确认小车周围安全，解除后仍需重新下达运动指令。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认解除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    if (!controlGranted) {
      releaseEmergencyAfterControlClaim = true;
      emergencyReleaseInProgress = true;
      _sendBridge(RosMessages.claimControl());
      _showControlWarning('正在取得小车控制权，成功后将自动解除急停');
      return;
    }
    emergencyReleaseInProgress = true;
    _sendBridge(RosMessages.emergencyStop(false));
  }

  /// 所有 ROS Bridge 指令的统一发送入口。
  /// 只有 WebSocket 已连接时才真正发送，否则只记录拦截日志。
  void _sendBridge(Map<String, Object?> payload) {
    final text = jsonEncode({...payload, 'client_id': controlClientId});
    if (AppConstants.layoutPreviewMode) {
      setState(() => _addLog('preview blocked $text'));
      return;
    }
    if (bridgeState == BridgeState.connected && socket != null) {
      socket!.add(text);
      // Joystick commands are sent at a high rate. Logging each one rebuilds
      // the whole page and adds visible input latency; failures still arrive
      // through the bridge response and are logged by the receiver.
      final isDriveCommand =
          payload['op'] == 'publish' && payload['topic'] == '/tablet_cmd_vel';
      if (!isDriveCommand) {
        setState(() => _addLog('send $text'));
      }
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
