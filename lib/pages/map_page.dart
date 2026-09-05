part of '../main.dart';

/// 地图与划线路径页，严格显示规划器发布的栅格、MarkerArray 和定位位姿。
class _MapPage extends StatelessWidget {
  const _MapPage({
    required this.connected,
    required this.lineRunning,
    required this.gridMap,
    required this.plannedPaths,
    required this.pathAnnotations,
    required this.robotPose,
    required this.poseTrace,
    required this.localizationValid,
    required this.localizationSource,
    required this.telemetryAgeMs,
    required this.mapAgeMs,
    required this.pathsAgeMs,
    required this.missionStage,
    required this.missionCurrentId,
    required this.missionCompleted,
    required this.missionTotal,
  });

  final bool connected;
  final bool lineRunning;
  final Map<String, dynamic> gridMap;
  final List<Map<String, dynamic>> plannedPaths;
  final List<Map<String, dynamic>> pathAnnotations;
  final Map<String, dynamic> robotPose;
  final List<List<double>> poseTrace;
  final bool localizationValid;
  final String localizationSource;
  final int? telemetryAgeMs;
  final int? mapAgeMs;
  final int? pathsAgeMs;
  final String missionStage;
  final int? missionCurrentId;
  final int missionCompleted;
  final int missionTotal;

  bool get isTotalStationMode => localizationSource == 'ln150_imu';
  bool get isRelativeMode => localizationSource == 'odom_imu_relative';

  String get mapModeTitle => isTotalStationMode
      ? '全局工程地图'
      : isRelativeMode
      ? '相对作业地图'
      : '定位模式未就绪';

  String get mapModeDetail => isTotalStationMode
      ? 'LN150 + IMU · 工程坐标'
      : isRelativeMode
      ? '里程计 + IMU · 本次相对原点'
      : '等待后端确认定位来源';

  Color get mapModeColor => isTotalStationMode
      ? const Color(0xff047857)
      : isRelativeMode
      ? const Color(0xffb45309)
      : const Color(0xff64748b);

  String? get referenceFrame {
    final mapFrame = gridMap['frame_id']?.toString();
    if (mapFrame != null && mapFrame.isNotEmpty) return mapFrame;
    for (final path in plannedPaths) {
      final frame = path['frame_id']?.toString();
      if (frame != null && frame.isNotEmpty) return frame;
    }
    return null;
  }

  bool get hasFramedPath => plannedPaths.any((path) {
    final frame = path['frame_id']?.toString();
    return frame != null && frame.isNotEmpty;
  });

  bool get isLocalPreview =>
      gridMap.isEmpty && plannedPaths.isNotEmpty && !hasFramedPath;

  bool get hasFrameConflict {
    final frame = referenceFrame;
    if (frame == null) return false;
    final poseFrame = robotPose['frame_id']?.toString();
    if (poseFrame != null && poseFrame.isNotEmpty && poseFrame != frame) {
      return true;
    }
    return plannedPaths.any((path) {
      final pathFrame = path['frame_id']?.toString();
      return pathFrame != null && pathFrame.isNotEmpty && pathFrame != frame;
    });
  }

  bool get framesAligned {
    final frame = referenceFrame;
    return frame != null && !hasFrameConflict;
  }

  String get mapStatusText {
    if (hasFrameConflict) {
      return '实时地图、规划路径与车体坐标系冲突，已隐藏车体和偏差';
    }
    if (isLocalPreview) {
      return '当前为本地图纸预览；完成真实路径规划后可叠加实时车体与转场路径';
    }
    if (referenceFrame == null) {
      return '尚未收到 ROS2 地图或规划路径，实时定位数据暂不叠加';
    }
    if (localizationFresh) {
      if (isTotalStationMode) {
        return '全局定位有效 · LN150 + IMU · ${telemetryAgeMs}ms';
      }
      if (isRelativeMode) {
        return '相对定位有效 · 里程计 + IMU · ${telemetryAgeMs}ms · 长距离存在累计漂移';
      }
      return '定位有效 · $localizationSource · ${telemetryAgeMs}ms';
    }
    return '定位无效或数据已过期，地图仅显示已发布的规划结果';
  }

  String get mapFrameLabel {
    if (gridMap['resolution'] is num) {
      return '${gridMap['frame_id'] ?? 'map'} · ${((gridMap['resolution'] as num).toDouble() * 1000).toStringAsFixed(0)}mm/格';
    }
    if (referenceFrame != null) return '$referenceFrame · 无栅格底图';
    if (isLocalPreview) return '本地图纸预览';
    return '等待 ROS2 路径';
  }

  bool get localizationFresh =>
      localizationValid && telemetryAgeMs != null && telemetryAgeMs! <= 750;

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

  double get traveledLength {
    var total = 0.0;
    for (var index = 1; index < poseTrace.length; index++) {
      total += Offset(
        poseTrace[index][0] - poseTrace[index - 1][0],
        poseTrace[index][1] - poseTrace[index - 1][1],
      ).distance;
    }
    return total;
  }

  double? get currentDeviation {
    if (!localizationFresh ||
        !framesAligned ||
        robotPose['x'] is! num ||
        robotPose['y'] is! num) {
      return null;
    }
    final rover = Offset(
      (robotPose['x'] as num).toDouble(),
      (robotPose['y'] as num).toDouble(),
    );
    double? nearest;
    for (final path in plannedPaths) {
      final points = path['points'] as List? ?? const [];
      for (var index = 1; index < points.length; index++) {
        final previous = points[index - 1];
        final current = points[index];
        if (previous is! List || current is! List) continue;
        final start = Offset(
          (previous[0] as num).toDouble(),
          (previous[1] as num).toDouble(),
        );
        final end = Offset(
          (current[0] as num).toDouble(),
          (current[1] as num).toDouble(),
        );
        final segment = end - start;
        final lengthSquared = segment.dx * segment.dx + segment.dy * segment.dy;
        final ratio = lengthSquared == 0
            ? 0.0
            : (((rover - start).dx * segment.dx +
                          (rover - start).dy * segment.dy) /
                      lengthSquared)
                  .clamp(0.0, 1.0);
        final distance = (rover - (start + segment * ratio)).distance;
        if (nearest == null || distance < nearest) nearest = distance;
      }
    }
    return nearest;
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      key: const ValueKey('map'),
      padding: const EdgeInsets.all(14),
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
          decoration: BoxDecoration(
            color: isTotalStationMode
                ? const Color(0xffecfdf5)
                : isRelativeMode
                ? const Color(0xfffff7ed)
                : const Color(0xfff1f5f9),
            border: Border.all(color: mapModeColor),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            children: [
              Icon(
                isTotalStationMode
                    ? Icons.public_rounded
                    : isRelativeMode
                    ? Icons.explore_rounded
                    : Icons.location_searching_rounded,
                color: mapModeColor,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      mapModeTitle,
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 14,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      mapModeDetail,
                      style: const TextStyle(
                        color: Color(0xff64748b),
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
                decoration: BoxDecoration(
                  color: mapModeColor,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  isTotalStationMode
                      ? '全站仪'
                      : isRelativeMode
                      ? '相对定位'
                      : '未就绪',
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w700,
                    fontSize: 11,
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: hasFrameConflict
                ? const Color(0xfffef2f2)
                : isLocalPreview || referenceFrame == null
                ? const Color(0xfffff7ed)
                : localizationFresh
                ? const Color(0xffecfdf5)
                : const Color(0xfffffbeb),
            border: Border.all(
              color: hasFrameConflict
                  ? const Color(0xfff87171)
                  : isLocalPreview || referenceFrame == null
                  ? const Color(0xfffb923c)
                  : localizationFresh
                  ? const Color(0xff86efac)
                  : const Color(0xfffcd34d),
            ),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Row(
            children: [
              Icon(
                hasFrameConflict
                    ? Icons.layers_clear_rounded
                    : isLocalPreview || referenceFrame == null
                    ? Icons.layers_outlined
                    : localizationFresh
                    ? Icons.my_location_rounded
                    : Icons.location_disabled_rounded,
                size: 20,
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Text(
                  mapStatusText,
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 12,
                  ),
                ),
              ),
              Text(
                missionTotal > 0
                    ? '$missionCompleted/$missionTotal${missionCurrentId == null ? '' : ' · #$missionCurrentId'}'
                    : missionStage,
                style: const TextStyle(color: Color(0xff475569), fontSize: 12),
              ),
            ],
          ),
        ),
        const SizedBox(height: 10),
        _Panel(
          title: isTotalStationMode ? '全局地图与划线路径' : '相对地图与划线路径',
          trailing: Text(
            mapFrameLabel,
            style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
          ),
          child: SizedBox(
            height: 480,
            child: !connected
                ? const _MapEmptyState(text: '连接小车后显示规划地图')
                : gridMap.isEmpty &&
                      plannedPaths.isEmpty &&
                      poseTrace.isEmpty &&
                      robotPose.isEmpty
                ? const _MapEmptyState(text: '等待路径规划器发布地图')
                : _EngineeringMapView(
                    lineRunning: lineRunning,
                    gridMap: gridMap,
                    plannedPaths: plannedPaths,
                    pathAnnotations: pathAnnotations,
                    robotPose: robotPose,
                    poseTrace: poseTrace,
                    showLivePose: localizationFresh && framesAligned,
                    relativeMode: isRelativeMode,
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
                note: isLocalPreview ? '图纸预览点' : '规划器轨迹点',
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
                note: isLocalPreview ? '图纸预览长度' : '真实规划路径',
                icon: Icons.straighten_rounded,
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: _MetricCard(
                title: '实际里程',
                value: traveledLength == 0
                    ? '--'
                    : '${traveledLength.toStringAsFixed(2)}m',
                note: isRelativeMode ? '相对原点起累计' : '全局定位轨迹累计',
                icon: Icons.route_rounded,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _MetricCard(
                title: '路径偏差',
                value: currentDeviation == null
                    ? '--'
                    : '${(currentDeviation! * 1000).toStringAsFixed(0)}mm',
                note: isRelativeMode ? '相对坐标路径偏差' : '全局坐标路径偏差',
                icon: Icons.compare_arrows_rounded,
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _EngineeringMapView extends StatefulWidget {
  const _EngineeringMapView({
    required this.lineRunning,
    required this.gridMap,
    required this.plannedPaths,
    required this.pathAnnotations,
    required this.robotPose,
    required this.poseTrace,
    required this.showLivePose,
    required this.relativeMode,
  });

  final bool lineRunning;
  final Map<String, dynamic> gridMap;
  final List<Map<String, dynamic>> plannedPaths;
  final List<Map<String, dynamic>> pathAnnotations;
  final Map<String, dynamic> robotPose;
  final List<List<double>> poseTrace;
  final bool showLivePose;
  final bool relativeMode;

  @override
  State<_EngineeringMapView> createState() => _EngineeringMapViewState();
}

class _EngineeringMapViewState extends State<_EngineeringMapView> {
  final TransformationController controller = TransformationController();
  bool showDrawing = true;
  bool showPlan = true;
  bool showTrace = true;
  bool showRobot = true;

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(8),
    child: Stack(
      children: [
        Positioned.fill(
          child: InteractiveViewer(
            transformationController: controller,
            minScale: 0.7,
            maxScale: 10,
            boundaryMargin: const EdgeInsets.all(160),
            child: CustomPaint(
              size: const Size(760, 760),
              painter: _MapPainter(
                lineRunning: widget.lineRunning,
                gridMap: widget.gridMap,
                plannedPaths: widget.plannedPaths,
                pathAnnotations: widget.pathAnnotations,
                robotPose: widget.robotPose,
                poseTrace: widget.poseTrace,
                showLivePose: widget.showLivePose,
                showDrawing: showDrawing,
                showPlan: showPlan,
                showTrace: showTrace,
                showRobot: showRobot,
              ),
            ),
          ),
        ),
        Positioned(
          left: 10,
          bottom: 48,
          child: Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              _MapLayerChip(
                '划线路径',
                const Color(0xff2563eb),
                showDrawing,
                () => setState(() => showDrawing = !showDrawing),
              ),
              _MapLayerChip(
                '转场路径',
                const Color(0xffd97706),
                showPlan,
                () => setState(() => showPlan = !showPlan),
              ),
              _MapLayerChip(
                '轨迹',
                const Color(0xffea580c),
                showTrace,
                () => setState(() => showTrace = !showTrace),
              ),
              _MapLayerChip(
                '车体',
                const Color(0xff16a34a),
                showRobot,
                () => setState(() => showRobot = !showRobot),
              ),
            ],
          ),
        ),
        Positioned(
          left: 10,
          bottom: 10,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
            decoration: BoxDecoration(
              color: const Color(0xe6ffffff),
              border: Border.all(color: const Color(0xffcbd5e1)),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  widget.relativeMode
                      ? Icons.trip_origin_rounded
                      : Icons.language_rounded,
                  size: 15,
                  color: widget.relativeMode
                      ? const Color(0xffb45309)
                      : const Color(0xff047857),
                ),
                const SizedBox(width: 5),
                Text(
                  widget.relativeMode ? '相对原点 0,0' : '工程坐标系',
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
        ),
        Positioned(
          right: 10,
          bottom: 10,
          child: IconButton.filledTonal(
            tooltip: '自动缩放',
            onPressed: () => controller.value = Matrix4.identity(),
            icon: const Icon(Icons.fit_screen_rounded),
          ),
        ),
      ],
    ),
  );
}

class _MapLayerChip extends StatelessWidget {
  const _MapLayerChip(this.label, this.color, this.selected, this.onTap);

  final String label;
  final Color color;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => FilterChip(
    selected: selected,
    onSelected: (_) => onTap(),
    showCheckmark: false,
    avatar: Container(
      width: 9,
      height: 9,
      decoration: BoxDecoration(color: color, shape: BoxShape.circle),
    ),
    label: Text(label),
    visualDensity: VisualDensity.compact,
    backgroundColor: const Color(0xe6ffffff),
    selectedColor: const Color(0xffffffff),
    side: const BorderSide(color: Color(0xffcbd5e1)),
    labelStyle: TextStyle(
      color: selected ? const Color(0xff0f172a) : const Color(0xff94a3b8),
      fontWeight: FontWeight.w700,
      fontSize: 12,
    ),
  );
}

class _RobotTelemetryPanel extends StatelessWidget {
  const _RobotTelemetryPanel({
    required this.obstacles,
    required this.obstacleAgeMs,
    required this.wheelSpeeds,
    required this.motorStatus,
    required this.battery,
  });

  final Map<String, dynamic> obstacles;
  final int? obstacleAgeMs;
  final Map<String, dynamic> wheelSpeeds;
  final Map<String, dynamic> motorStatus;
  final int? battery;

  String distance(String key) {
    final value = obstacles[key];
    return value is num ? '${value.toStringAsFixed(2)} m' : '--';
  }

  String speed(String key) {
    final value = wheelSpeeds[key];
    return value is num ? '${value.toStringAsFixed(2)} m/s' : '--';
  }

  @override
  Widget build(BuildContext context) => _CollapsiblePanel(
    title: '车辆遥测',
    statusText: obstacleAgeMs == null || obstacleAgeMs! > 1500
        ? '避障未接入'
        : (motorStatus['ready'] == true ? '遥测正常' : '电机待检'),
    statusColor:
        obstacleAgeMs != null &&
            obstacleAgeMs! <= 1500 &&
            motorStatus['ready'] == true
        ? const Color(0xff22c55e)
        : const Color(0xfff59e0b),
    child: Column(
      children: [
        Row(
          children: [
            Expanded(child: _TelemetryValue('前障碍', distance('front'))),
            Expanded(child: _TelemetryValue('后障碍', distance('back'))),
            Expanded(child: _TelemetryValue('左障碍', distance('left'))),
            Expanded(child: _TelemetryValue('右障碍', distance('right'))),
          ],
        ),
        const Divider(height: 18),
        Row(
          children: [
            Expanded(child: _TelemetryValue('左轮', speed('left_mps'))),
            Expanded(child: _TelemetryValue('右轮', speed('right_mps'))),
            Expanded(
              child: _TelemetryValue(
                'LN150 电池',
                battery == null ? '--' : '$battery%',
              ),
            ),
          ],
        ),
        if ((motorStatus['error']?.toString() ?? '').isNotEmpty) ...[
          const SizedBox(height: 10),
          Text(
            motorStatus['error'].toString(),
            style: const TextStyle(color: Color(0xfff87171), fontSize: 12),
          ),
        ],
      ],
    ),
  );
}

class _TelemetryValue extends StatelessWidget {
  const _TelemetryValue(this.label, this.value);
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Text(
        label,
        style: const TextStyle(color: Color(0xffa8b4c7), fontSize: 11),
      ),
      const SizedBox(height: 3),
      Text(
        value,
        style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
      ),
    ],
  );
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
