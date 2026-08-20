part of '../main.dart';

enum _DrawingTool { pan, select, line, rectangle, circle, freehand }

class _SketchPath {
  _SketchPath(this.points);

  List<Offset> points;

  _SketchPath copy() => _SketchPath(List<Offset>.from(points));
}

class _DrawingEditorPage extends StatefulWidget {
  const _DrawingEditorPage({
    required this.device,
    required this.bridgeConnected,
    required this.localizationSource,
  });

  final RoverDevice device;
  final bool bridgeConnected;
  final String localizationSource;

  @override
  State<_DrawingEditorPage> createState() => _DrawingEditorPageState();
}

class _DrawingEditorPageState extends State<_DrawingEditorPage> {
  double pixelsPerMeter = 42;
  final TextEditingController promptController = TextEditingController();
  final List<_SketchPath> paths = [];
  final List<List<_SketchPath>> undoStack = [];
  final List<List<_SketchPath>> redoStack = [];
  final TransformationController viewController = TransformationController();
  _DrawingTool tool = _DrawingTool.select;
  _SketchPath? draft;
  Offset dragStart = Offset.zero;
  Offset lastWorld = Offset.zero;
  Offset cursorWorld = Offset.zero;
  Size canvasSize = Size.zero;
  int? selectedIndex;
  bool busy = false;
  bool snapEnabled = true;
  double snapStep = 0.1;
  bool selectionDragRecorded = false;
  String status = '单位：米 · 保存前请核对尺寸';

  @override
  void dispose() {
    promptController.dispose();
    viewController.dispose();
    super.dispose();
  }

  Offset _toWorld(Offset local) => Offset(
    (local.dx - canvasSize.width / 2) / pixelsPerMeter,
    (canvasSize.height / 2 - local.dy) / pixelsPerMeter,
  );

  List<_SketchPath> _snapshot() => paths.map((path) => path.copy()).toList();

  void _recordChange() {
    undoStack.add(_snapshot());
    if (undoStack.length > 50) undoStack.removeAt(0);
    redoStack.clear();
  }

  void _restore(List<_SketchPath> snapshot) {
    paths
      ..clear()
      ..addAll(snapshot.map((path) => path.copy()));
    selectedIndex = null;
  }

  void _undo() {
    if (undoStack.isEmpty) return;
    redoStack.add(_snapshot());
    setState(() => _restore(undoStack.removeLast()));
  }

  void _redo() {
    if (redoStack.isEmpty) return;
    undoStack.add(_snapshot());
    setState(() => _restore(redoStack.removeLast()));
  }

  Offset _snap(Offset point) {
    if (!snapEnabled) return point;
    var snapped = Offset(
      (point.dx / snapStep).round() * snapStep,
      (point.dy / snapStep).round() * snapStep,
    );
    final threshold = math.max(0.08, 8 / pixelsPerMeter);
    for (final path in paths) {
      for (final candidate in path.points) {
        if ((candidate - point).distance <= threshold) return candidate;
      }
    }
    return snapped;
  }

  void _start(DragStartDetails details) {
    final world = _snap(_toWorld(details.localPosition));
    cursorWorld = world;
    dragStart = world;
    lastWorld = world;
    if (tool == _DrawingTool.select) {
      selectedIndex = _nearestPath(world);
      selectionDragRecorded = false;
      setState(() {});
      return;
    }
    draft = _SketchPath([world, world]);
    setState(() {});
  }

  void _update(DragUpdateDetails details) {
    final world = _snap(_toWorld(details.localPosition));
    cursorWorld = world;
    if (tool == _DrawingTool.select && selectedIndex != null) {
      if (!selectionDragRecorded) {
        _recordChange();
        selectionDragRecorded = true;
      }
      final delta = world - lastWorld;
      final selected = paths[selectedIndex!];
      selected.points = selected.points.map((point) => point + delta).toList();
      lastWorld = world;
      setState(() {});
      return;
    }
    if (draft == null) return;
    switch (tool) {
      case _DrawingTool.pan:
        break;
      case _DrawingTool.line:
        draft!.points = [dragStart, world];
      case _DrawingTool.rectangle:
        draft!.points = [
          dragStart,
          Offset(world.dx, dragStart.dy),
          world,
          Offset(dragStart.dx, world.dy),
          dragStart,
        ];
      case _DrawingTool.circle:
        final radius = (world - dragStart).distance;
        draft!.points = [
          for (var index = 0; index <= 48; index++)
            dragStart +
                Offset(
                  radius * math.cos(index * math.pi * 2 / 48),
                  radius * math.sin(index * math.pi * 2 / 48),
                ),
        ];
      case _DrawingTool.freehand:
        if ((world - draft!.points.last).distance > 0.08) {
          draft!.points.add(world);
        }
      case _DrawingTool.select:
        break;
    }
    setState(() {});
  }

  void _end(DragEndDetails details) {
    if (draft != null && draft!.points.length > 1) {
      final length = draft!.points
          .asMap()
          .entries
          .skip(1)
          .fold<double>(
            0,
            (sum, entry) =>
                sum + (entry.value - draft!.points[entry.key - 1]).distance,
          );
      if (length > 0.02) {
        _recordChange();
        paths.add(draft!);
      }
    }
    draft = null;
    selectionDragRecorded = false;
    setState(() {});
  }

  int? _nearestPath(Offset world) {
    var bestDistance = 0.35;
    int? best;
    for (var index = 0; index < paths.length; index++) {
      for (final point in paths[index].points) {
        final distance = (point - world).distance;
        if (distance < bestDistance) {
          bestDistance = distance;
          best = index;
        }
      }
    }
    return best;
  }

  double? _number(TextEditingController controller) =>
      double.tryParse(controller.text.trim());

  Future<void> _showPreciseCreateDialog() async {
    var preciseTool = switch (tool) {
      _DrawingTool.rectangle => _DrawingTool.rectangle,
      _DrawingTool.circle => _DrawingTool.circle,
      _ => _DrawingTool.line,
    };
    final first = TextEditingController(text: '0');
    final second = TextEditingController(text: '0');
    final third = TextEditingController(
      text: preciseTool == _DrawingTool.line ? '1' : '2',
    );
    final fourth = TextEditingController(
      text: preciseTool == _DrawingTool.rectangle ? '1' : '0',
    );
    final created = await showDialog<_SketchPath>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) {
          final labels = switch (preciseTool) {
            _DrawingTool.rectangle => const ['X', 'Y', '宽度', '高度'],
            _DrawingTool.circle => const ['圆心 X', '圆心 Y', '半径', ''],
            _ => const ['起点 X', '起点 Y', '终点 X', '终点 Y'],
          };
          return AlertDialog(
            title: const Text('精确绘制'),
            content: SizedBox(
              width: 360,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  SegmentedButton<_DrawingTool>(
                    segments: const [
                      ButtonSegment(
                        value: _DrawingTool.line,
                        icon: Icon(Icons.horizontal_rule_rounded),
                        label: Text('直线'),
                      ),
                      ButtonSegment(
                        value: _DrawingTool.rectangle,
                        icon: Icon(Icons.rectangle_outlined),
                        label: Text('矩形'),
                      ),
                      ButtonSegment(
                        value: _DrawingTool.circle,
                        icon: Icon(Icons.circle_outlined),
                        label: Text('圆'),
                      ),
                    ],
                    selected: {preciseTool},
                    onSelectionChanged: (value) =>
                        setDialogState(() => preciseTool = value.first),
                  ),
                  const SizedBox(height: 14),
                  for (
                    var index = 0;
                    index < (preciseTool == _DrawingTool.circle ? 3 : 4);
                    index++
                  ) ...[
                    TextField(
                      controller: [first, second, third, fourth][index],
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                        signed: true,
                      ),
                      decoration: InputDecoration(
                        labelText: '${labels[index]}（m）',
                      ),
                    ),
                    if (index < 3) const SizedBox(height: 8),
                  ],
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('取消'),
              ),
              FilledButton(
                onPressed: () {
                  final values = [
                    first,
                    second,
                    third,
                    fourth,
                  ].map(_number).toList();
                  if (values
                      .take(preciseTool == _DrawingTool.circle ? 3 : 4)
                      .any((value) => value == null)) {
                    return;
                  }
                  final x = values[0]!;
                  final y = values[1]!;
                  _SketchPath? path;
                  if (preciseTool == _DrawingTool.line) {
                    path = _SketchPath([
                      Offset(x, y),
                      Offset(values[2]!, values[3]!),
                    ]);
                  } else if (preciseTool == _DrawingTool.rectangle &&
                      values[2]! > 0 &&
                      values[3]! > 0) {
                    final width = values[2]!;
                    final height = values[3]!;
                    path = _SketchPath([
                      Offset(x, y),
                      Offset(x + width, y),
                      Offset(x + width, y + height),
                      Offset(x, y + height),
                      Offset(x, y),
                    ]);
                  } else if (preciseTool == _DrawingTool.circle &&
                      values[2]! > 0) {
                    final radius = values[2]!;
                    path = _SketchPath([
                      for (var index = 0; index <= 64; index++)
                        Offset(x, y) +
                            Offset(
                              radius * math.cos(index * math.pi * 2 / 64),
                              radius * math.sin(index * math.pi * 2 / 64),
                            ),
                    ]);
                  }
                  if (path != null) Navigator.pop(context, path);
                },
                child: const Text('添加'),
              ),
            ],
          );
        },
      ),
    );
    first.dispose();
    second.dispose();
    third.dispose();
    fourth.dispose();
    if (!mounted || created == null) return;
    _recordChange();
    setState(() {
      paths.add(created);
      selectedIndex = paths.length - 1;
      tool = _DrawingTool.select;
      status = '已按精确尺寸添加图形';
    });
  }

  Future<void> _editSelected() async {
    final index = selectedIndex;
    if (index == null) return;
    final path = paths[index];
    final minX = path.points.map((point) => point.dx).reduce(math.min);
    final maxX = path.points.map((point) => point.dx).reduce(math.max);
    final minY = path.points.map((point) => point.dy).reduce(math.min);
    final maxY = path.points.map((point) => point.dy).reduce(math.max);
    final controllers = [minX, minY, maxX - minX, maxY - minY]
        .map((value) => TextEditingController(text: value.toStringAsFixed(3)))
        .toList();
    final values = await showDialog<List<double>>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('对象属性'),
        content: SizedBox(
          width: 340,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (var i = 0; i < 4; i++) ...[
                TextField(
                  controller: controllers[i],
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                    signed: true,
                  ),
                  decoration: InputDecoration(
                    labelText: '${const ['X', 'Y', '宽度', '高度'][i]}（m）',
                  ),
                ),
                if (i < 3) const SizedBox(height: 8),
              ],
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () {
              final parsed = controllers.map(_number).toList();
              if (parsed.any((value) => value == null) ||
                  parsed[2]! < 0 ||
                  parsed[3]! < 0 ||
                  (parsed[2] == 0 && parsed[3] == 0)) {
                return;
              }
              Navigator.pop(context, parsed.cast<double>());
            },
            child: const Text('应用'),
          ),
        ],
      ),
    );
    for (final controller in controllers) {
      controller.dispose();
    }
    if (!mounted || values == null) return;
    _recordChange();
    final oldWidth = maxX - minX;
    final oldHeight = maxY - minY;
    setState(() {
      path.points = path.points
          .map(
            (point) => Offset(
              oldWidth == 0
                  ? values[0]
                  : values[0] + (point.dx - minX) / oldWidth * values[2],
              oldHeight == 0
                  ? values[1]
                  : values[1] + (point.dy - minY) / oldHeight * values[3],
            ),
          )
          .toList();
      status = '对象尺寸已更新';
    });
  }

  Future<Map<String, dynamic>> _post(String endpoint, Object body) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 5);
    try {
      final request = await client.postUrl(
        Uri.parse('http://${widget.device.ip}:${widget.device.port}$endpoint'),
      );
      request.headers.contentType = ContentType.json;
      request.write(jsonEncode(body));
      final response = await request.close().timeout(
        const Duration(seconds: 20),
      );
      final decoded = jsonDecode(await utf8.decoder.bind(response).join());
      if (decoded is! Map) throw const FormatException('响应格式无效');
      return Map<String, dynamic>.from(decoded);
    } finally {
      client.close(force: true);
    }
  }

  Future<void> _generate({bool replaceSelected = false}) async {
    final prompt = promptController.text.trim();
    if (prompt.isEmpty) return;
    if (!widget.bridgeConnected) {
      setState(() => status = '请先连接小车或虚拟 Bridge');
      return;
    }
    setState(() {
      busy = true;
      status = '助手正在生成草图...';
    });
    try {
      final result = await _post('/api/drawings/generate', {'prompt': prompt});
      if (result['ok'] != true) {
        setState(() => status = result['message']?.toString() ?? '无法生成图纸');
        return;
      }
      final generated = <_SketchPath>[];
      for (final raw in result['shapes'] as List? ?? const []) {
        if (raw is! Map) continue;
        final shape = Map<String, dynamic>.from(raw);
        if (shape['type'] == 'rectangle') {
          final x = (shape['x'] as num).toDouble();
          final y = (shape['y'] as num).toDouble();
          final width = (shape['width'] as num).toDouble();
          final height = (shape['height'] as num).toDouble();
          generated.add(
            _SketchPath([
              Offset(x, y),
              Offset(x + width, y),
              Offset(x + width, y + height),
              Offset(x, y + height),
              Offset(x, y),
            ]),
          );
        } else {
          final points = <Offset>[];
          for (final point in shape['points'] as List? ?? const []) {
            if (point is List && point.length >= 2) {
              points.add(
                Offset(
                  (point[0] as num).toDouble(),
                  (point[1] as num).toDouble(),
                ),
              );
            }
          }
          if (points.length > 1) generated.add(_SketchPath(points));
        }
      }
      setState(() {
        if (generated.isNotEmpty) _recordChange();
        if (replaceSelected && selectedIndex != null && generated.isNotEmpty) {
          final index = selectedIndex!;
          paths
            ..removeAt(index)
            ..insertAll(index, generated);
          selectedIndex = index;
          status = 'AI 已局部重绘选中对象';
        } else {
          paths.addAll(generated);
          selectedIndex = null;
          status = result['message']?.toString() ?? '草图已生成';
        }
      });
    } catch (_) {
      setState(() => status = '生成失败，请检查 Bridge 与后端版本');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  List<Map<String, double>> _segments() {
    final segments = <Map<String, double>>[];
    for (final path in paths) {
      for (var index = 1; index < path.points.length; index++) {
        final start = path.points[index - 1];
        final end = path.points[index];
        segments.add({
          'start_x': start.dx,
          'start_y': start.dy,
          'end_x': end.dx,
          'end_y': end.dy,
        });
      }
    }
    return segments;
  }

  List<_SketchPath> get _travelPreview {
    final result = <_SketchPath>[];
    for (var index = 1; index < paths.length; index++) {
      final previous = paths[index - 1];
      final current = paths[index];
      if (previous.points.isEmpty || current.points.isEmpty) continue;
      if ((previous.points.last - current.points.first).distance > 0.001) {
        result.add(_SketchPath([previous.points.last, current.points.first]));
      }
    }
    return result;
  }

  Map<String, dynamic> _preflight() {
    final errors = <String>[];
    final warnings = <String>[];
    final errorSegments = <String>{};
    final warningSegments = <String>{};
    final seen = <String>{};
    var printingLength = 0.0;
    for (var pathIndex = 0; pathIndex < paths.length; pathIndex++) {
      final path = paths[pathIndex];
      if (path.points.length < 2) {
        errors.add('图形 ${pathIndex + 1} 没有有效线段');
        continue;
      }
      for (var index = 1; index < path.points.length; index++) {
        final start = path.points[index - 1];
        final end = path.points[index];
        final length = (end - start).distance;
        printingLength += length;
        if (length < 0.001) errors.add('图形 ${pathIndex + 1} 包含零长度线段');
        if (length < 0.001) errorSegments.add('$pathIndex:$index');
        if (length < 0.02) {
          warnings.add('图形 ${pathIndex + 1} 包含短于 20 mm 的线段');
          warningSegments.add('$pathIndex:$index');
        }
        if ([
          start.dx,
          start.dy,
          end.dx,
          end.dy,
        ].any((value) => !value.isFinite || value.abs() > 100)) {
          errors.add('图形 ${pathIndex + 1} 超出 ±100 m 坐标范围');
        }
        String pointKey(Offset point) =>
            '${point.dx.toStringAsFixed(4)},${point.dy.toStringAsFixed(4)}';
        final ends = [pointKey(start), pointKey(end)]..sort();
        if (!seen.add(ends.join('|'))) {
          warnings.add('检测到重复喷墨线段');
          warningSegments.add('$pathIndex:$index');
        }
      }
      for (var index = 1; index < path.points.length - 1; index++) {
        final incoming = path.points[index - 1] - path.points[index];
        final outgoing = path.points[index + 1] - path.points[index];
        if (incoming.distance == 0 || outgoing.distance == 0) continue;
        final cosine =
            (incoming.dx * outgoing.dx + incoming.dy * outgoing.dy) /
            (incoming.distance * outgoing.distance);
        final angle = math.acos(cosine.clamp(-1.0, 1.0)) * 180 / math.pi;
        if (angle < 55) {
          warnings.add('图形 ${pathIndex + 1} 存在急转角');
          warningSegments.add('$pathIndex:$index');
          warningSegments.add('$pathIndex:${index + 1}');
        }
      }
      if (path.points.length > 8 &&
          (path.points.first - path.points.last).distance < 0.001) {
        final minX = path.points.map((point) => point.dx).reduce(math.min);
        final maxX = path.points.map((point) => point.dx).reduce(math.max);
        final minY = path.points.map((point) => point.dy).reduce(math.min);
        final maxY = path.points.map((point) => point.dy).reduce(math.max);
        if (math.min(maxX - minX, maxY - minY) / 2 < 0.25) {
          warnings.add('图形 ${pathIndex + 1} 半径较小，需检查实车转向结果');
          for (var index = 1; index < path.points.length; index++) {
            warningSegments.add('$pathIndex:$index');
          }
        }
      }
    }
    bool intersects(Offset a, Offset b, Offset c, Offset d) {
      double cross(Offset p, Offset q, Offset r) =>
          (q.dx - p.dx) * (r.dy - p.dy) - (q.dy - p.dy) * (r.dx - p.dx);
      final abC = cross(a, b, c);
      final abD = cross(a, b, d);
      final cdA = cross(c, d, a);
      final cdB = cross(c, d, b);
      return abC * abD < 0 && cdA * cdB < 0;
    }

    final segments = <(int, int, Offset, Offset)>[];
    for (var pathIndex = 0; pathIndex < paths.length; pathIndex++) {
      for (var index = 1; index < paths[pathIndex].points.length; index++) {
        segments.add((
          pathIndex,
          index,
          paths[pathIndex].points[index - 1],
          paths[pathIndex].points[index],
        ));
      }
    }
    for (var left = 0; left < segments.length; left++) {
      for (var right = left + 1; right < segments.length; right++) {
        final a = segments[left];
        final b = segments[right];
        if (a.$1 == b.$1 && (a.$2 - b.$2).abs() <= 1) continue;
        if (intersects(a.$3, a.$4, b.$3, b.$4)) {
          warnings.add('检测到路径自交');
          warningSegments.add('${a.$1}:${a.$2}');
          warningSegments.add('${b.$1}:${b.$2}');
        }
      }
    }
    final travelLength = _travelPreview.fold<double>(
      0,
      (total, path) => total + (path.points.last - path.points.first).distance,
    );
    return {
      'ok': errors.isEmpty,
      'errors': errors.toSet().toList(),
      'warnings': warnings.toSet().toList(),
      'printing_length_m': printingLength,
      'travel_length_m': travelLength,
      'printing_paths': paths.length,
      'travel_paths': _travelPreview.length,
      'error_segments': errorSegments,
      'warning_segments': warningSegments,
    };
  }

  Future<void> _save() async {
    if (paths.isEmpty) {
      setState(() => status = '请先绘制或生成图形');
      return;
    }
    final check = _preflight();
    final errors = (check['errors'] as List).cast<String>();
    final warnings = (check['warnings'] as List).cast<String>();
    final proceed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(errors.isEmpty ? '保存前检查' : '图纸不能保存'),
        content: SizedBox(
          width: 380,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '喷墨 ${(check['printing_length_m'] as double).toStringAsFixed(2)} m · '
                '预计转场 ${(check['travel_length_m'] as double).toStringAsFixed(2)} m',
              ),
              const SizedBox(height: 10),
              if (errors.isNotEmpty)
                for (final error in errors)
                  Text(
                    '错误：$error',
                    style: const TextStyle(color: Color(0xffdc2626)),
                  ),
              if (warnings.isNotEmpty)
                for (final warning in warnings)
                  Text(
                    '提醒：$warning',
                    style: const TextStyle(color: Color(0xffb45309)),
                  ),
              if (errors.isEmpty && warnings.isEmpty)
                const Text('几何、坐标和重复路径检查通过。'),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('返回编辑'),
          ),
          if (errors.isEmpty)
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('继续保存'),
            ),
        ],
      ),
    );
    if (!mounted || proceed != true) return;
    final nameController = TextEditingController(
      text: 'app_drawing_${DateTime.now().millisecondsSinceEpoch}',
    );
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('保存任务图纸'),
        content: TextField(
          controller: nameController,
          autofocus: true,
          decoration: const InputDecoration(labelText: '文件名称'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, nameController.text.trim()),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    // 等待弹窗退出动画完成，避免与画图页退出同时修改 Navigator Overlay。
    await Future<void>.delayed(const Duration(milliseconds: 300));
    nameController.dispose();
    if (!mounted || name == null || name.isEmpty) return;
    setState(() {
      busy = true;
      status = '正在转换任务文件...';
    });
    try {
      final result = await _post('/api/drawings/save', {
        'name': name,
        'segments': _segments(),
      });
      if (!mounted) return;
      if (result['ok'] == true) {
        await Future<void>.delayed(const Duration(milliseconds: 80));
        if (!mounted) return;
        Navigator.pop(context, result['file_name'].toString());
      } else {
        setState(() => status = result['message']?.toString() ?? '保存失败');
      }
    } catch (_) {
      setState(() => status = '保存失败，请检查小车后端');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final liveCheck = _preflight();
    final liveErrors = (liveCheck['errors'] as List).length;
    final liveWarnings = (liveCheck['warnings'] as List).length;
    return Scaffold(
      appBar: AppBar(
        title: const Text('图纸编辑器'),
        actions: [
          IconButton(
            tooltip: '撤销',
            onPressed: undoStack.isEmpty ? null : _undo,
            icon: const Icon(Icons.undo_rounded),
          ),
          IconButton(
            tooltip: '重做',
            onPressed: redoStack.isEmpty ? null : _redo,
            icon: const Icon(Icons.redo_rounded),
          ),
          IconButton(
            tooltip: '精确绘制',
            onPressed: busy ? null : _showPreciseCreateDialog,
            icon: const Icon(Icons.square_foot_rounded),
          ),
          IconButton(
            tooltip: '编辑选中对象',
            onPressed: selectedIndex == null ? null : _editSelected,
            icon: const Icon(Icons.tune_rounded),
          ),
          IconButton(
            tooltip: '删除选中图形',
            onPressed: selectedIndex == null
                ? null
                : () {
                    _recordChange();
                    setState(() {
                      paths.removeAt(selectedIndex!);
                      selectedIndex = null;
                    });
                  },
            icon: const Icon(Icons.delete_outline_rounded),
          ),
          IconButton(
            tooltip: '保存任务',
            onPressed: busy ? null : _save,
            icon: const Icon(Icons.save_rounded),
          ),
        ],
      ),
      body: Column(
        children: [
          Container(
            height: 52,
            margin: const EdgeInsets.fromLTRB(10, 6, 10, 0),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: const Color(0xffdce3ea)),
            ),
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
              children: [
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: FilterChip(
                    selected: snapEnabled,
                    onSelected: (value) => setState(() => snapEnabled = value),
                    avatar: const Icon(Icons.grid_4x4_rounded, size: 17),
                    label: Text('吸附 ${(snapStep * 1000).round()}mm'),
                    showCheckmark: false,
                  ),
                ),
                _DrawingToolButton(
                  tool: _DrawingTool.pan,
                  selected: tool,
                  icon: Icons.pan_tool_alt_rounded,
                  label: '视图',
                  onTap: _setTool,
                ),
                _DrawingToolButton(
                  tool: _DrawingTool.select,
                  selected: tool,
                  icon: Icons.near_me_rounded,
                  label: '选择',
                  onTap: _setTool,
                ),
                _DrawingToolButton(
                  tool: _DrawingTool.line,
                  selected: tool,
                  icon: Icons.horizontal_rule_rounded,
                  label: '直线',
                  onTap: _setTool,
                ),
                _DrawingToolButton(
                  tool: _DrawingTool.rectangle,
                  selected: tool,
                  icon: Icons.rectangle_outlined,
                  label: '矩形',
                  onTap: _setTool,
                ),
                _DrawingToolButton(
                  tool: _DrawingTool.circle,
                  selected: tool,
                  icon: Icons.circle_outlined,
                  label: '圆',
                  onTap: _setTool,
                ),
                _DrawingToolButton(
                  tool: _DrawingTool.freehand,
                  selected: tool,
                  icon: Icons.gesture_rounded,
                  label: '折线',
                  onTap: _setTool,
                ),
              ],
            ),
          ),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(16, 2, 16, 8),
            alignment: Alignment.center,
            child: Text(
              _toolHint,
              style: const TextStyle(color: Color(0xff94a3b8), fontSize: 12),
            ),
          ),
          Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                canvasSize = Size(constraints.maxWidth, constraints.maxHeight);
                final canvas = Stack(
                  fit: StackFit.expand,
                  children: [
                    CustomPaint(
                      size: canvasSize,
                      painter: _DrawingCanvasPainter(
                        paths: paths,
                        travelPaths: _travelPreview,
                        draft: draft,
                        selectedIndex: selectedIndex,
                        pixelsPerMeter: pixelsPerMeter,
                        relativeMode:
                            widget.localizationSource == 'odom_imu_relative',
                        errorSegments:
                            liveCheck['error_segments'] as Set<String>,
                        warningSegments:
                            liveCheck['warning_segments'] as Set<String>,
                      ),
                    ),
                    if (paths.isEmpty && draft == null)
                      const IgnorePointer(
                        child: Center(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                Icons.draw_outlined,
                                color: Color(0xff64748b),
                                size: 34,
                              ),
                              SizedBox(height: 8),
                              Text(
                                '画布为空',
                                style: TextStyle(
                                  color: Color(0xff94a3b8),
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              SizedBox(height: 3),
                              Text(
                                '选择上方工具开始绘制',
                                style: TextStyle(
                                  color: Color(0xff64748b),
                                  fontSize: 12,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    Positioned(
                      left: 12,
                      bottom: 12,
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 9,
                          vertical: 5,
                        ),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(6),
                          border: Border.all(color: const Color(0xffdce3ea)),
                        ),
                        child: Text(
                          '${cursorWorld.dx.toStringAsFixed(2)}, '
                          '${cursorWorld.dy.toStringAsFixed(2)} m',
                          style: const TextStyle(
                            color: Color(0xffcbd5e1),
                            fontSize: 11,
                          ),
                        ),
                      ),
                    ),
                    Positioned(
                      right: 10,
                      bottom: 10,
                      child: Row(
                        children: [
                          _CanvasViewButton(
                            tooltip: '缩小',
                            icon: Icons.remove_rounded,
                            onPressed: () => setState(
                              () => pixelsPerMeter = math.max(
                                20,
                                pixelsPerMeter - 6,
                              ),
                            ),
                          ),
                          const SizedBox(width: 6),
                          _CanvasViewButton(
                            tooltip: '放大',
                            icon: Icons.add_rounded,
                            onPressed: () => setState(
                              () => pixelsPerMeter = math.min(
                                96,
                                pixelsPerMeter + 6,
                              ),
                            ),
                          ),
                          const SizedBox(width: 6),
                          _CanvasViewButton(
                            tooltip: '重置视图',
                            icon: Icons.center_focus_strong_rounded,
                            onPressed: () => setState(() {
                              pixelsPerMeter = 42;
                              viewController.value = Matrix4.identity();
                              selectedIndex = null;
                              cursorWorld = Offset.zero;
                            }),
                          ),
                        ],
                      ),
                    ),
                  ],
                );
                if (tool == _DrawingTool.pan) {
                  return InteractiveViewer(
                    transformationController: viewController,
                    minScale: 0.5,
                    maxScale: 8,
                    boundaryMargin: const EdgeInsets.all(300),
                    child: SizedBox(
                      width: canvasSize.width,
                      height: canvasSize.height,
                      child: canvas,
                    ),
                  );
                }
                return GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onPanStart: _start,
                  onPanUpdate: _update,
                  onPanEnd: _end,
                  child: canvas,
                );
              },
            ),
          ),
          Container(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
            decoration: const BoxDecoration(
              color: Color(0xff0f172a),
              border: Border(top: BorderSide(color: Color(0xff22304a))),
            ),
            child: SafeArea(
              top: false,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    status,
                    style: const TextStyle(
                      color: Color(0xff94a3b8),
                      fontSize: 12,
                    ),
                  ),
                  const SizedBox(height: 5),
                  Text(
                    '草稿 · 喷墨 ${(liveCheck['printing_length_m'] as double).toStringAsFixed(2)}m · '
                    '预计转场 ${(liveCheck['travel_length_m'] as double).toStringAsFixed(2)}m · '
                    '错误 $liveErrors · 警告 $liveWarnings',
                    style: TextStyle(
                      color: liveErrors > 0
                          ? const Color(0xfff87171)
                          : liveWarnings > 0
                          ? const Color(0xfffbbf24)
                          : const Color(0xff86efac),
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: promptController,
                          minLines: 1,
                          maxLines: 2,
                          decoration: _inputDecoration(
                            '让助手帮你画图',
                            Icons.smart_toy_rounded,
                          ),
                          onSubmitted: (_) => _generate(),
                        ),
                      ),
                      const SizedBox(width: 8),
                      if (selectedIndex != null) ...[
                        IconButton.filledTonal(
                          tooltip: 'AI 局部重绘选中对象',
                          onPressed: busy
                              ? null
                              : () => _generate(replaceSelected: true),
                          icon: const Icon(Icons.auto_fix_high_rounded),
                        ),
                        const SizedBox(width: 6),
                      ],
                      IconButton.filled(
                        tooltip: '生成草图',
                        onPressed: busy ? null : _generate,
                        icon: busy
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.arrow_upward_rounded),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _setTool(_DrawingTool value) => setState(() {
    tool = value;
    selectedIndex = null;
  });

  String get _toolHint => switch (tool) {
    _DrawingTool.pan => '双指缩放或拖动画布；重置按钮回到原点',
    _DrawingTool.select => '单指选取并拖动图形',
    _DrawingTool.line => '按住拖动绘制直线',
    _DrawingTool.rectangle => '从一个角拖动到对角绘制矩形',
    _DrawingTool.circle => '从圆心向外拖动绘制圆形',
    _DrawingTool.freehand => '按住拖动绘制连续路径',
  };
}

class _CanvasViewButton extends StatelessWidget {
  const _CanvasViewButton({
    required this.tooltip,
    required this.icon,
    required this.onPressed,
  });

  final String tooltip;
  final IconData icon;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) => IconButton(
    tooltip: tooltip,
    onPressed: onPressed,
    style: IconButton.styleFrom(
      backgroundColor: const Color(0xee111827),
      foregroundColor: const Color(0xffcbd5e1),
      side: const BorderSide(color: Color(0xff22304a)),
      minimumSize: const Size(36, 36),
      maximumSize: const Size(36, 36),
      padding: EdgeInsets.zero,
    ),
    icon: Icon(icon, size: 18),
  );
}

class _DrawingToolButton extends StatelessWidget {
  const _DrawingToolButton({
    required this.tool,
    required this.selected,
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final _DrawingTool tool;
  final _DrawingTool selected;
  final IconData icon;
  final String label;
  final ValueChanged<_DrawingTool> onTap;

  @override
  Widget build(BuildContext context) {
    final active = tool == selected;
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: Tooltip(
        message: label,
        child: IconButton(
          onPressed: () => onTap(tool),
          style: IconButton.styleFrom(
            backgroundColor: active
                ? const Color(0xff16a66a)
                : const Color(0xfff1f5f9),
            foregroundColor: active ? Colors.white : const Color(0xff64748b),
          ),
          icon: Icon(icon),
        ),
      ),
    );
  }
}

class _DrawingCanvasPainter extends CustomPainter {
  _DrawingCanvasPainter({
    required this.paths,
    required this.travelPaths,
    required this.draft,
    required this.selectedIndex,
    required this.pixelsPerMeter,
    required this.relativeMode,
    required this.errorSegments,
    required this.warningSegments,
  });

  final List<_SketchPath> paths;
  final List<_SketchPath> travelPaths;
  final _SketchPath? draft;
  final int? selectedIndex;
  final double pixelsPerMeter;
  final bool relativeMode;
  final Set<String> errorSegments;
  final Set<String> warningSegments;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xff07111f),
    );
    final center = Offset(size.width / 2, size.height / 2);
    final grid = Paint()..strokeWidth = 1;
    for (
      var x = center.dx % pixelsPerMeter;
      x < size.width;
      x += pixelsPerMeter
    ) {
      final major = ((x - center.dx) / pixelsPerMeter).round() % 5 == 0;
      grid.color = major ? const Color(0xff24344d) : const Color(0xff152238);
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    }
    for (
      var y = center.dy % pixelsPerMeter;
      y < size.height;
      y += pixelsPerMeter
    ) {
      final major = ((y - center.dy) / pixelsPerMeter).round() % 5 == 0;
      grid.color = major ? const Color(0xff24344d) : const Color(0xff152238);
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }
    canvas.drawLine(
      Offset(0, center.dy),
      Offset(size.width, center.dy),
      Paint()..color = const Color(0xff3b82f6),
    );
    canvas.drawLine(
      Offset(center.dx, 0),
      Offset(center.dx, size.height),
      Paint()..color = const Color(0xff3b82f6),
    );

    final roverWidth = 0.55 * pixelsPerMeter;
    final roverLength = 0.75 * pixelsPerMeter;
    final roverRect = Rect.fromCenter(
      center: center,
      width: roverWidth,
      height: roverLength,
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(roverRect, const Radius.circular(5)),
      Paint()
        ..color = const Color(0x3322c55e)
        ..style = PaintingStyle.fill,
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(roverRect, const Radius.circular(5)),
      Paint()
        ..color = const Color(0xff22c55e)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5,
    );
    canvas.drawLine(
      center,
      center.translate(0, -roverLength * 0.7),
      Paint()
        ..color = const Color(0xff22c55e)
        ..strokeWidth = 2.5,
    );
    final label = TextPainter(
      text: TextSpan(
        text: relativeMode ? '相对原点 · 初始车头' : '工程原点 · 初始车头',
        style: const TextStyle(color: Color(0xff86efac), fontSize: 10),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    label.paint(canvas, center.translate(10, 10));

    Offset screen(Offset world) => Offset(
      center.dx + world.dx * pixelsPerMeter,
      center.dy - world.dy * pixelsPerMeter,
    );

    void drawPath(_SketchPath path, Color color, double width) {
      if (path.points.length < 2) return;
      final drawing = Path()
        ..moveTo(screen(path.points.first).dx, screen(path.points.first).dy);
      for (final point in path.points.skip(1)) {
        final offset = screen(point);
        drawing.lineTo(offset.dx, offset.dy);
      }
      canvas.drawPath(
        drawing,
        Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = width
          ..strokeCap = StrokeCap.round
          ..strokeJoin = StrokeJoin.round,
      );
    }

    for (final path in travelPaths) {
      drawPath(path, const Color(0xfff59e0b), 2);
    }
    for (var index = 0; index < paths.length; index++) {
      drawPath(
        paths[index],
        index == selectedIndex
            ? const Color(0xfff59e0b)
            : const Color(0xff60a5fa),
        index == selectedIndex ? 4 : 3,
      );
    }
    for (var pathIndex = 0; pathIndex < paths.length; pathIndex++) {
      final path = paths[pathIndex];
      for (var index = 1; index < path.points.length; index++) {
        final key = '$pathIndex:$index';
        final color = errorSegments.contains(key)
            ? const Color(0xffef4444)
            : warningSegments.contains(key)
            ? const Color(0xfff59e0b)
            : null;
        if (color == null) continue;
        canvas.drawLine(
          screen(path.points[index - 1]),
          screen(path.points[index]),
          Paint()
            ..color = color
            ..strokeWidth = 5
            ..strokeCap = StrokeCap.round,
        );
      }
    }
    if (draft != null) drawPath(draft!, const Color(0xff22c55e), 3);
  }

  @override
  bool shouldRepaint(covariant _DrawingCanvasPainter oldDelegate) => true;
}
