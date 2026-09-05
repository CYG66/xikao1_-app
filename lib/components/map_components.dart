part of '../main.dart';

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
    this.pathAnnotations = const [],
    required this.robotPose,
    required this.poseTrace,
    this.showLivePose = true,
    this.showDrawing = true,
    this.showPlan = true,
    this.showTrace = true,
    this.showRobot = true,
    this.cameraZoom = 1,
    this.cameraPan = Offset.zero,
    this.followRobot = false,
  });

  final bool lineRunning;
  final Map<String, dynamic> gridMap;
  final List<Map<String, dynamic>> plannedPaths;
  final List<Map<String, dynamic>> pathAnnotations;
  final Map<String, dynamic> robotPose;
  final List<List<double>> poseTrace;
  final bool showLivePose;
  final bool showDrawing;
  final bool showPlan;
  final bool showTrace;
  final bool showRobot;
  final double cameraZoom;
  final Offset cameraPan;
  final bool followRobot;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xfff8fafc),
    );
    final width = (gridMap['width'] as num?)?.toInt() ?? 0;
    final height = (gridMap['height'] as num?)?.toInt() ?? 0;
    final resolution = (gridMap['resolution'] as num?)?.toDouble() ?? 0;
    final originX = (gridMap['origin_x'] as num?)?.toDouble() ?? 0;
    final originY = (gridMap['origin_y'] as num?)?.toDouble() ?? 0;
    final mapFrame = gridMap['frame_id']?.toString();
    String? referenceFrame = mapFrame;
    for (final segment in plannedPaths) {
      referenceFrame ??= segment['frame_id']?.toString();
    }

    final xs = <double>[];
    final ys = <double>[];
    if (width > 0 && height > 0 && resolution > 0) {
      xs.addAll([originX, originX + width * resolution]);
      ys.addAll([originY, originY + height * resolution]);
    }
    for (final segment in plannedPaths) {
      final segmentFrame = segment['frame_id']?.toString();
      if (referenceFrame != null &&
          segmentFrame != null &&
          segmentFrame != referenceFrame) {
        continue;
      }
      for (final raw in segment['points'] as List? ?? const []) {
        if (raw is List && raw.length >= 2 && raw[0] is num && raw[1] is num) {
          xs.add((raw[0] as num).toDouble());
          ys.add((raw[1] as num).toDouble());
        }
      }
    }
    for (final annotation in pathAnnotations) {
      final annotationFrame = annotation['frame_id']?.toString();
      if (referenceFrame != null &&
          annotationFrame != null &&
          annotationFrame != referenceFrame) {
        continue;
      }
      if (annotation['x'] is num && annotation['y'] is num) {
        xs.add((annotation['x'] as num).toDouble());
        ys.add((annotation['y'] as num).toDouble());
      }
    }
    for (final point in poseTrace) {
      if (point.length >= 2) {
        xs.add(point[0]);
        ys.add(point[1]);
      }
    }
    if (showLivePose && robotPose['x'] is num && robotPose['y'] is num) {
      xs.add((robotPose['x'] as num).toDouble());
      ys.add((robotPose['y'] as num).toDouble());
    }
    if (xs.isEmpty) return;

    var minX = xs.reduce(math.min);
    var maxX = xs.reduce(math.max);
    var minY = ys.reduce(math.min);
    var maxY = ys.reduce(math.max);
    if (maxX - minX < 2) {
      minX -= 1;
      maxX += 1;
    }
    if (maxY - minY < 2) {
      minY -= 1;
      maxY += 1;
    }
    final paddingX = (maxX - minX) * .1;
    final paddingY = (maxY - minY) * .1;
    minX -= paddingX;
    maxX += paddingX;
    minY -= paddingY;
    maxY += paddingY;

    const margin = 42.0;
    var worldWidth = maxX - minX;
    var worldHeight = maxY - minY;
    final viewportWidth = math.max(1.0, size.width - margin * 2);
    final viewportHeight = math.max(1.0, size.height - margin * 2);
    final viewportAspect = viewportWidth / viewportHeight;
    final worldAspect = worldWidth / worldHeight;
    if (worldAspect < viewportAspect) {
      final extra = (worldHeight * viewportAspect - worldWidth) / 2;
      minX -= extra;
      maxX += extra;
      worldWidth = maxX - minX;
    } else if (worldAspect > viewportAspect) {
      final extra = (worldWidth / viewportAspect - worldHeight) / 2;
      minY -= extra;
      maxY += extra;
      worldHeight = maxY - minY;
    }
    final baseScale = math.min(
      (size.width - margin * 2) / worldWidth,
      (size.height - margin * 2) / worldHeight,
    );
    final pixelsPerMeter = baseScale * cameraZoom;
    final centerX = followRobot && robotPose['x'] is num
        ? (robotPose['x'] as num).toDouble()
        : (minX + maxX) / 2 - cameraPan.dx / pixelsPerMeter;
    final centerY = followRobot && robotPose['y'] is num
        ? (robotPose['y'] as num).toDouble()
        : (minY + maxY) / 2 + cameraPan.dy / pixelsPerMeter;
    worldWidth = viewportWidth / pixelsPerMeter;
    worldHeight = viewportHeight / pixelsPerMeter;
    minX = centerX - worldWidth / 2;
    maxX = centerX + worldWidth / 2;
    minY = centerY - worldHeight / 2;
    maxY = centerY + worldHeight / 2;
    final mapWidth = viewportWidth;
    final mapHeight = viewportHeight;
    const left = margin;
    const top = margin;

    Offset world(double x, double y) => Offset(
      left + (x - minX) * pixelsPerMeter,
      top + mapHeight - (y - minY) * pixelsPerMeter,
    );

    final gridStep = pixelsPerMeter >= 70
        ? .5
        : pixelsPerMeter >= 32
        ? 1.0
        : 2.0;
    final gridPaint = Paint()
      ..color = const Color(0xffe2e8f0)
      ..strokeWidth = 1;
    final axisPaint = Paint()
      ..color = const Color(0xff94a3b8)
      ..strokeWidth = 1.5;
    final labels = TextPainter(textDirection: TextDirection.ltr);
    for (
      var x = (minX / gridStep).floor() * gridStep;
      x <= maxX;
      x += gridStep
    ) {
      final p = world(x, 0);
      canvas.drawLine(
        Offset(p.dx, top),
        Offset(p.dx, top + mapHeight),
        x.abs() < .0001 ? axisPaint : gridPaint,
      );
      labels.text = TextSpan(
        text: '${x.toStringAsFixed(gridStep < 1 ? 1 : 0)}m',
        style: const TextStyle(color: Color(0xff64748b), fontSize: 10),
      );
      labels.layout();
      labels.paint(canvas, Offset(p.dx + 3, top + mapHeight - 16));
    }
    for (
      var y = (minY / gridStep).floor() * gridStep;
      y <= maxY;
      y += gridStep
    ) {
      final p = world(0, y);
      canvas.drawLine(
        Offset(left, p.dy),
        Offset(left + mapWidth, p.dy),
        y.abs() < .0001 ? axisPaint : gridPaint,
      );
      labels.text = TextSpan(
        text: '${y.toStringAsFixed(gridStep < 1 ? 1 : 0)}m',
        style: const TextStyle(color: Color(0xff64748b), fontSize: 10),
      );
      labels.layout();
      labels.paint(canvas, Offset(left + 3, p.dy - 14));
    }

    final scaleBarMeters = pixelsPerMeter >= 70 ? 1.0 : 2.0;
    final scaleBarStart = Offset(left + 12, top + mapHeight - 30);
    final scaleBarEnd =
        scaleBarStart + Offset(scaleBarMeters * pixelsPerMeter, 0);
    final scalePaint = Paint()
      ..color = const Color(0xff0f172a)
      ..strokeWidth = 3;
    canvas.drawLine(scaleBarStart, scaleBarEnd, scalePaint);
    canvas.drawLine(
      scaleBarStart - const Offset(0, 5),
      scaleBarStart + const Offset(0, 5),
      axisPaint,
    );
    canvas.drawLine(
      scaleBarEnd - const Offset(0, 5),
      scaleBarEnd + const Offset(0, 5),
      axisPaint,
    );
    labels.text = TextSpan(
      text: '${scaleBarMeters.toStringAsFixed(0)} m',
      style: const TextStyle(
        color: Color(0xff0f172a),
        fontSize: 11,
        fontWeight: FontWeight.w700,
      ),
    );
    labels.layout();
    labels.paint(canvas, scaleBarStart - const Offset(0, 20));

    const north = Offset(26, 76);
    canvas.drawLine(north + const Offset(0, 20), north, axisPaint);
    final northPath = Path()
      ..moveTo(north.dx, north.dy)
      ..lineTo(north.dx - 5, north.dy + 9)
      ..lineTo(north.dx + 5, north.dy + 9)
      ..close();
    canvas.drawPath(northPath, Paint()..color = const Color(0xff334155));
    labels.text = const TextSpan(
      text: 'N',
      style: TextStyle(
        color: Color(0xff334155),
        fontSize: 11,
        fontWeight: FontWeight.w800,
      ),
    );
    labels.layout();
    labels.paint(canvas, north - const Offset(4, 16));

    if (width > 0 && height > 0 && resolution > 0) {
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
          final cell = world(
            originX + column * resolution,
            originY + (row + 1) * resolution,
          );
          canvas.drawRect(
            Rect.fromLTWH(
              cell.dx,
              cell.dy,
              count * resolution * pixelsPerMeter + .5,
              resolution * pixelsPerMeter + .5,
            ),
            Paint()..color = const Color(0xffcbd5e1),
          );
          index += count;
          remaining -= count;
        }
      }
    }

    for (final segment in plannedPaths) {
      final segmentFrame = segment['frame_id']?.toString();
      if (referenceFrame != null &&
          segmentFrame != null &&
          segmentFrame != referenceFrame) {
        continue;
      }
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
          segment['route_type'] == 'drawing' ||
          (segment['namespace'] == 'path_lines' &&
              (((segment['color'] as Map?)?['b'] as num?)?.toDouble() ?? 0) >
                  .8);
      if ((drawing && !showDrawing) || (!drawing && !showPlan)) continue;
      canvas.drawPath(
        path,
        Paint()
          ..color = drawing ? const Color(0xff2563eb) : const Color(0xffd97706)
          ..style = PaintingStyle.stroke
          ..strokeCap = StrokeCap.round
          ..strokeJoin = StrokeJoin.round
          ..strokeWidth = drawing ? 3.0 : 2.5,
      );
    }

    if (showDrawing) {
      for (final annotation in pathAnnotations) {
        final annotationFrame = annotation['frame_id']?.toString();
        if (referenceFrame != null &&
            annotationFrame != null &&
            annotationFrame != referenceFrame) {
          continue;
        }
        if (annotation['x'] is! num || annotation['y'] is! num) continue;
        final text = annotation['text']?.toString() ?? '';
        if (text.isEmpty) continue;
        final position = world(
          (annotation['x'] as num).toDouble(),
          (annotation['y'] as num).toDouble(),
        );
        labels.text = TextSpan(
          text: text,
          style: const TextStyle(
            color: Color(0xff0f172a),
            fontSize: 11,
            fontWeight: FontWeight.w700,
          ),
        );
        labels.layout(maxWidth: 180);
        labels.paint(canvas, position + const Offset(5, -18));
      }
    }

    if (showTrace && poseTrace.length >= 2) {
      final tracePath = Path();
      for (var index = 0; index < poseTrace.length; index++) {
        final offset = world(poseTrace[index][0], poseTrace[index][1]);
        index == 0
            ? tracePath.moveTo(offset.dx, offset.dy)
            : tracePath.lineTo(offset.dx, offset.dy);
      }
      canvas.drawPath(
        tracePath,
        Paint()
          ..color = const Color(0xfff97316)
          ..style = PaintingStyle.stroke
          ..strokeWidth = 3
          ..strokeCap = StrokeCap.round
          ..strokeJoin = StrokeJoin.round,
      );
    }

    final poseFrame = robotPose['frame_id']?.toString();
    if (showRobot &&
        showLivePose &&
        robotPose.isNotEmpty &&
        (poseFrame == null || poseFrame == referenceFrame)) {
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
          ..color = const Color(0xff14532d)
          ..strokeWidth = 3
          ..strokeCap = StrokeCap.round,
      );

      // Values come from xline_path_planner/config/planner.yaml.
      final lateral = Offset(-math.sin(theta), -math.cos(theta));
      for (final nozzleOffset in const [-0.25, 0.005, 0.25]) {
        final nozzle = rover + lateral * (nozzleOffset * pixelsPerMeter);
        canvas.drawCircle(
          nozzle,
          3.5,
          Paint()..color = const Color(0xff0f766e),
        );
      }
    }
  }

  @override
  bool shouldRepaint(covariant _MapPainter oldDelegate) =>
      oldDelegate.lineRunning != lineRunning ||
      oldDelegate.gridMap != gridMap ||
      oldDelegate.plannedPaths != plannedPaths ||
      oldDelegate.pathAnnotations != pathAnnotations ||
      oldDelegate.poseTrace != poseTrace ||
      oldDelegate.robotPose != robotPose ||
      oldDelegate.showLivePose != showLivePose ||
      oldDelegate.showDrawing != showDrawing ||
      oldDelegate.showPlan != showPlan ||
      oldDelegate.showTrace != showTrace ||
      oldDelegate.showRobot != showRobot ||
      oldDelegate.cameraZoom != cameraZoom ||
      oldDelegate.cameraPan != cameraPan;
}

class _ConnectionLayerRow extends StatelessWidget {
  const _ConnectionLayerRow({
    required this.label,
    required this.detail,
    required this.ready,
    this.last = false,
  });

  final String label;
  final String detail;
  final bool ready;
  final bool last;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(vertical: 6),
    decoration: BoxDecoration(
      border: last
          ? null
          : const Border(bottom: BorderSide(color: Color(0xffe2e8f0))),
    ),
    child: Row(
      children: [
        Icon(
          ready ? Icons.check_circle_rounded : Icons.error_outline_rounded,
          color: ready ? const Color(0xff22c55e) : const Color(0xfff59e0b),
          size: 19,
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            label,
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        ),
        Text(
          detail,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(color: Color(0xff64748b), fontSize: 12),
        ),
      ],
    ),
  );
}
