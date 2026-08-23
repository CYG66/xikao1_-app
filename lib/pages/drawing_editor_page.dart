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
    required this.previewMode,
    required this.localizationSource,
    this.embedded = false,
  });

  final RoverDevice device;
  final bool bridgeConnected;
  final bool previewMode;
  final String localizationSource;
  final bool embedded;

  @override
  State<_DrawingEditorPage> createState() => _DrawingEditorPageState();
}

class _DrawingEditorPageState extends State<_DrawingEditorPage> {
  double pixelsPerMeter = 42;
  final TextEditingController promptController = TextEditingController();
  final OfflineSpeechService drawingSpeech = OfflineSpeechService();
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
  bool transformingView = false;
  Matrix4 gestureBaseTransform = Matrix4.identity();
  bool drawingSpeechStarting = false;
  bool drawingListening = false;
  String drawingSpeechPrefix = '';
  Timer? drawingSpeechTimer;

  @override
  void dispose() {
    drawingSpeechTimer?.cancel();
    unawaited(drawingSpeech.dispose());
    promptController.dispose();
    viewController.dispose();
    super.dispose();
  }

  Future<void> _toggleDrawingSpeech() async {
    if (drawingListening) {
      drawingSpeechTimer?.cancel();
      setState(() {
        drawingListening = false;
        drawingSpeechStarting = true;
        status = '录音结束，正在本地转换为文字...';
      });
      try {
        final spoken = await drawingSpeech.stopAndRecognize();
        if (!mounted) return;
        final text = drawingSpeechPrefix.isEmpty
            ? spoken
            : spoken.isEmpty
            ? drawingSpeechPrefix
            : '$drawingSpeechPrefix $spoken';
        setState(() {
          promptController.value = TextEditingValue(
            text: text,
            selection: TextSelection.collapsed(offset: text.length),
          );
          drawingSpeechStarting = false;
          status = spoken.isEmpty
              ? '没有识别到语音，请靠近平板麦克风后重试'
              : '语音已转成图纸描述，请检查后再生成草图';
        });
      } catch (error) {
        if (!mounted) return;
        setState(() {
          drawingSpeechStarting = false;
          status = error is OfflineSpeechException
              ? error.message
              : '离线语音识别失败：$error';
        });
      }
      return;
    }

    setState(() {
      drawingSpeechStarting = true;
      status = '正在加载高精度离线中文模型...';
    });
    try {
      drawingSpeechPrefix = promptController.text.trimRight();
      await drawingSpeech.start();
      if (!mounted) {
        await drawingSpeech.cancel();
        return;
      }
      setState(() {
        drawingListening = true;
        drawingSpeechStarting = false;
        status = '正在录音，再次点击麦克风结束并转成图纸描述';
      });
      drawingSpeechTimer?.cancel();
      drawingSpeechTimer = Timer(const Duration(seconds: 60), () {
        if (mounted && drawingListening) {
          unawaited(_toggleDrawingSpeech());
        }
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        drawingListening = false;
        drawingSpeechStarting = false;
        status = error is OfflineSpeechException
            ? error.message
            : '离线语音识别失败：$error';
      });
    }
  }

  Offset _toWorld(Offset local) => Offset(
    (viewController.toScene(local).dx - canvasSize.width / 2) / pixelsPerMeter,
    (canvasSize.height / 2 - viewController.toScene(local).dy) / pixelsPerMeter,
  );

  void _gestureStart(ScaleStartDetails details) {
    transformingView = details.pointerCount > 1;
    gestureBaseTransform = viewController.value.clone();
    if (transformingView) {
      draft = null;
      selectionDragRecorded = false;
      setState(() {});
      return;
    }
    if (tool == _DrawingTool.pan) {
      cursorWorld = _toWorld(details.localFocalPoint);
      setState(() {});
      return;
    }
    _start(
      DragStartDetails(
        localPosition: details.localFocalPoint,
        globalPosition: details.focalPoint,
      ),
    );
  }

  void _gestureUpdate(ScaleUpdateDetails details) {
    if (details.pointerCount > 1 || transformingView) {
      if (!transformingView) {
        transformingView = true;
        draft = null;
        selectionDragRecorded = false;
        gestureBaseTransform = viewController.value.clone();
      }
      final focal = details.localFocalPoint;
      final next = gestureBaseTransform.clone()
        ..translate(details.focalPointDelta.dx, details.focalPointDelta.dy)
        ..translate(focal.dx, focal.dy)
        ..rotateZ(details.rotation)
        ..scale(details.scale)
        ..translate(-focal.dx, -focal.dy);
      viewController.value = next;
      setState(() {});
      return;
    }
    _update(
      DragUpdateDetails(
        localPosition: details.localFocalPoint,
        globalPosition: details.focalPoint,
      ),
    );
  }

  void _gestureEnd(ScaleEndDetails details) {
    if (transformingView) {
      transformingView = false;
      draft = null;
      setState(() {});
      return;
    }
    _end(
      DragEndDetails(
        primaryVelocity: details.velocity.pixelsPerSecond.distance,
      ),
    );
  }

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
    if (widget.previewMode) {
      throw StateError('布局预览模式不会发送后端请求');
    }
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

  List<_SketchPath> _templatePaths(String template) {
    _SketchPath rectangle(
      double width,
      double height, [
      Offset origin = Offset.zero,
    ]) {
      final left = origin.dx - width / 2;
      final right = origin.dx + width / 2;
      final bottom = origin.dy - height / 2;
      final top = origin.dy + height / 2;
      return _SketchPath([
        Offset(left, bottom),
        Offset(right, bottom),
        Offset(right, top),
        Offset(left, top),
        Offset(left, bottom),
      ]);
    }

    _SketchPath circle(double radius, [Offset center = Offset.zero]) =>
        _SketchPath([
          for (var index = 0; index <= 48; index++)
            center +
                Offset(
                  radius * math.cos(index * math.pi * 2 / 48),
                  radius * math.sin(index * math.pi * 2 / 48),
                ),
        ]);

    return switch (template) {
      'room' => [rectangle(6, 4)],
      'two_rooms' => [
        rectangle(8, 6),
        _SketchPath([const Offset(0, -3), const Offset(0, 3)]),
      ],
      'parking' => [rectangle(2.5, 5)],
      'basketball' => [
        rectangle(28, 15),
        _SketchPath([const Offset(0, -7.5), const Offset(0, 7.5)]),
        circle(1.8),
      ],
      'grid' => [
        for (var value = -2; value <= 2; value++)
          _SketchPath([
            Offset(value.toDouble(), -2),
            Offset(value.toDouble(), 2),
          ]),
        for (var value = -2; value <= 2; value++)
          _SketchPath([
            Offset(-2, value.toDouble()),
            Offset(2, value.toDouble()),
          ]),
      ],
      'foundation' => [circle(3)],
      'corridor' => [rectangle(12, 2)],
      'warehouse' => [
        rectangle(20, 12),
        for (var x = -8; x <= 8; x += 4)
          _SketchPath([Offset(x.toDouble(), -6), Offset(x.toDouble(), 6)]),
      ],
      'badminton' => [
        rectangle(13.4, 6.1),
        _SketchPath([const Offset(0, -3.05), const Offset(0, 3.05)]),
        _SketchPath([const Offset(-2.1, -3.05), const Offset(-2.1, 3.05)]),
        _SketchPath([const Offset(2.1, -3.05), const Offset(2.1, 3.05)]),
      ],
      'parking_lot' => [
        rectangle(12, 6),
        for (var x = -5; x <= 5; x += 2)
          _SketchPath([Offset(x.toDouble(), -3), Offset(x.toDouble(), 3)]),
      ],
      _ => const [],
    };
  }

  void _applyTemplate(String template, String label) {
    final generated = _templatePaths(template);
    if (generated.isEmpty) return;
    _recordChange();
    setState(() {
      paths
        ..clear()
        ..addAll(generated);
      selectedIndex = null;
      tool = _DrawingTool.select;
      status = '已载入$label，可继续选择、编辑或精确调整';
      viewController.value = Matrix4.identity();
    });
  }

  @override
  Widget build(BuildContext context) {
    final liveCheck = _preflight();
    final liveErrors = (liveCheck['errors'] as List).length;
    final liveWarnings = (liveCheck['warnings'] as List).length;
    final appBar = AppBar(
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
    );
    final toolBar = Container(
      height: 50,
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.96),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xffdce3ea)),
        boxShadow: const [
          BoxShadow(
            color: Color(0x180f172a),
            blurRadius: 12,
            offset: Offset(0, 4),
          ),
        ],
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
    );
    final editorContent = Column(
      children: [
        Container(
          width: double.infinity,
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
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
              final drawingLayer = Stack(
                fit: StackFit.expand,
                children: [
                  CustomPaint(
                    painter: _DrawingCanvasPainter(
                      paths: paths,
                      travelPaths: _travelPreview,
                      draft: draft,
                      selectedIndex: selectedIndex,
                      pixelsPerMeter: pixelsPerMeter,
                      relativeMode:
                          widget.localizationSource == 'odom_imu_relative',
                      errorSegments: liveCheck['error_segments'] as Set<String>,
                      warningSegments:
                          liveCheck['warning_segments'] as Set<String>,
                      drawGrid: false,
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
                ],
              );
              final canvas = Stack(
                fit: StackFit.expand,
                children: [
                  Positioned.fill(
                    child: CustomPaint(
                      painter: _InfiniteGridPainter(
                        transform: viewController.value,
                        pixelsPerMeter: pixelsPerMeter,
                        relativeMode:
                            widget.localizationSource == 'odom_imu_relative',
                      ),
                    ),
                  ),
                  Positioned.fill(
                    child: GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      onScaleStart: _gestureStart,
                      onScaleUpdate: _gestureUpdate,
                      onScaleEnd: _gestureEnd,
                      child: Transform(
                        alignment: Alignment.topLeft,
                        transform: viewController.value,
                        child: SizedBox(
                          width: canvasSize.width,
                          height: canvasSize.height,
                          child: drawingLayer,
                        ),
                      ),
                    ),
                  ),
                  Positioned(
                    left: 12,
                    right: 12,
                    bottom: 12,
                    child: Center(
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 560),
                        child: toolBar,
                      ),
                    ),
                  ),
                  Positioned(
                    left: 12,
                    bottom: 72,
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
                    bottom: 70,
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
              return canvas;
            },
          ),
        ),
        Container(
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
          decoration: const BoxDecoration(
            color: Colors.white,
            border: Border(top: BorderSide(color: Color(0xffdce3ea))),
          ),
          child: SafeArea(
            top: false,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  status,
                  style: const TextStyle(
                    color: Color(0xff64748b),
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
                        : const Color(0xff15803d),
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
                        enabled:
                            !drawingSpeechStarting &&
                            !drawingListening &&
                            !busy,
                        minLines: 1,
                        maxLines: 2,
                        decoration: _inputDecoration(
                          drawingListening ? '正在录音，再次点击麦克风结束' : '让助手帮你画图',
                          drawingListening
                              ? Icons.graphic_eq_rounded
                              : Icons.smart_toy_rounded,
                        ),
                        onSubmitted: (_) => _generate(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    IconButton(
                      tooltip: drawingListening
                          ? '结束录音并在本机转换'
                          : drawingSpeechStarting
                          ? '正在加载离线语音模型'
                          : '离线语音输入图纸描述',
                      onPressed: busy || drawingSpeechStarting
                          ? null
                          : _toggleDrawingSpeech,
                      style: IconButton.styleFrom(
                        foregroundColor: drawingListening
                            ? const Color(0xffdc2626)
                            : const Color(0xff475569),
                        backgroundColor: drawingListening
                            ? const Color(0xffffe4e6)
                            : const Color(0xfff1f5f9),
                      ),
                      icon: Icon(
                        drawingListening
                            ? Icons.mic_rounded
                            : Icons.mic_none_rounded,
                      ),
                    ),
                    const SizedBox(width: 6),
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
                              child: CircularProgressIndicator(strokeWidth: 2),
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
    );
    final content = LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth < 900) return editorContent;
        return Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(
              width: 310,
              child: _DrawingTemplateLibrary(onSelected: _applyTemplate),
            ),
            const VerticalDivider(width: 1, color: Color(0xffdce3ea)),
            Expanded(child: editorContent),
          ],
        );
      },
    );
    if (widget.embedded) {
      return Material(
        color: const Color(0xfff8fafc),
        child: Column(
          children: [
            appBar,
            Expanded(child: content),
          ],
        ),
      );
    }
    return Scaffold(appBar: appBar, body: content);
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
      backgroundColor: Colors.white,
      foregroundColor: const Color(0xff475569),
      side: const BorderSide(color: Color(0xffcbd5e1)),
      minimumSize: const Size(36, 36),
      maximumSize: const Size(36, 36),
      padding: EdgeInsets.zero,
    ),
    icon: Icon(icon, size: 18),
  );
}

class _DrawingTemplateLibrary extends StatefulWidget {
  const _DrawingTemplateLibrary({required this.onSelected});

  final void Function(String template, String label) onSelected;

  @override
  State<_DrawingTemplateLibrary> createState() =>
      _DrawingTemplateLibraryState();
}

class _DrawingTemplateLibraryState extends State<_DrawingTemplateLibrary> {
  String category = '全部';

  static const templates = [
    ('room', '矩形房间', '6 x 4 m', Icons.crop_square_rounded, '建筑'),
    ('two_rooms', '两室布局', '8 x 6 m · 含隔墙', Icons.view_week_outlined, '建筑'),
    ('corridor', '长走廊', '12 x 2 m', Icons.horizontal_rule_rounded, '建筑'),
    ('parking', '标准车位', '2.5 x 5 m', Icons.local_parking_rounded, '场地'),
    ('parking_lot', '停车场', '12 x 6 m · 车位线', Icons.local_parking, '场地'),
    ('basketball', '篮球场', '28 x 15 m', Icons.sports_basketball_rounded, '场地'),
    ('badminton', '羽毛球场', '13.4 x 6.1 m', Icons.sports_tennis_rounded, '场地'),
    ('warehouse', '仓库网格', '20 x 12 m', Icons.warehouse_outlined, '施工'),
    ('grid', '施工轴网', '5 x 5 网格', Icons.grid_on_rounded, '施工'),
    ('foundation', '圆形基础', '半径 3 m', Icons.circle_outlined, '施工'),
  ];

  @override
  Widget build(BuildContext context) => ColoredBox(
    color: const Color(0xfff8fafc),
    child: Padding(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Row(
            children: [
              Icon(Icons.dashboard_customize_outlined, size: 20),
              SizedBox(width: 8),
              Text(
                '图纸模板',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
              ),
            ],
          ),
          const SizedBox(height: 4),
          const Text(
            '选择常用结构后可继续精确编辑',
            style: TextStyle(color: Color(0xff64748b), fontSize: 12),
          ),
          const SizedBox(height: 14),
          Container(
            height: 38,
            padding: const EdgeInsets.all(3),
            decoration: BoxDecoration(
              color: const Color(0xffe8edf5),
              borderRadius: BorderRadius.circular(7),
            ),
            child: Row(
              children: [
                for (final label in const ['全部', '建筑', '场地', '施工'])
                  Expanded(
                    child: GestureDetector(
                      onTap: () => setState(() => category = label),
                      child: _DrawingCategoryLabel(
                        label,
                        selected: category == label,
                      ),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          Expanded(
            child: GridView.builder(
              itemCount: templates
                  .where((item) => category == '全部' || item.$5 == category)
                  .length,
              gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 2,
                mainAxisSpacing: 10,
                crossAxisSpacing: 10,
                childAspectRatio: 0.82,
              ),
              itemBuilder: (context, index) {
                final visible = templates
                    .where((item) => category == '全部' || item.$5 == category)
                    .toList();
                final item = visible[index];
                return InkWell(
                  onTap: () => widget.onSelected(item.$1, item.$2),
                  borderRadius: BorderRadius.circular(8),
                  child: Ink(
                    padding: const EdgeInsets.all(9),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: const Color(0xffdce3ea)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Container(
                            width: double.infinity,
                            decoration: BoxDecoration(
                              color: const Color(0xffeef3f9),
                              borderRadius: BorderRadius.circular(6),
                            ),
                            child: Icon(
                              item.$4,
                              color: const Color(0xff64809f),
                              size: 34,
                            ),
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          item.$2,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        Text(
                          item.$3,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Color(0xff64748b),
                            fontSize: 10,
                          ),
                        ),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    ),
  );
}

class _DrawingCategoryLabel extends StatelessWidget {
  const _DrawingCategoryLabel(this.label, {this.selected = false});

  final String label;
  final bool selected;

  @override
  Widget build(BuildContext context) => Container(
    alignment: Alignment.center,
    decoration: selected
        ? BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(5),
            boxShadow: const [
              BoxShadow(color: Color(0x160f172a), blurRadius: 4),
            ],
          )
        : null,
    child: Text(
      label,
      style: TextStyle(
        color: selected ? const Color(0xff1e293b) : const Color(0xff64748b),
        fontSize: 11,
        fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
      ),
    ),
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

class _InfiniteGridPainter extends CustomPainter {
  _InfiniteGridPainter({
    required this.transform,
    required this.pixelsPerMeter,
    required this.relativeMode,
  });

  final Matrix4 transform;
  final double pixelsPerMeter;
  final bool relativeMode;

  Offset _transformPoint(Offset point) {
    final values = transform.storage;
    return Offset(
      values[0] * point.dx + values[4] * point.dy + values[12],
      values[1] * point.dx + values[5] * point.dy + values[13],
    );
  }

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRect(
      Offset.zero & size,
      Paint()..color = const Color(0xfff8fbff),
    );

    final sceneCorners = [
      Offset.zero,
      Offset(size.width, 0),
      Offset(0, size.height),
      Offset(size.width, size.height),
    ].map((point) => _scenePoint(point)).toList();
    final minSceneX = sceneCorners.map((point) => point.dx).reduce(math.min);
    final maxSceneX = sceneCorners.map((point) => point.dx).reduce(math.max);
    final minSceneY = sceneCorners.map((point) => point.dy).reduce(math.min);
    final maxSceneY = sceneCorners.map((point) => point.dy).reduce(math.max);
    final center = Offset(size.width / 2, size.height / 2);
    final minWorldX = ((minSceneX - center.dx) / pixelsPerMeter).floor() - 1;
    final maxWorldX = ((maxSceneX - center.dx) / pixelsPerMeter).ceil() + 1;
    final minWorldY = ((center.dy - maxSceneY) / pixelsPerMeter).floor() - 1;
    final maxWorldY = ((center.dy - minSceneY) / pixelsPerMeter).ceil() + 1;
    final grid = Paint()..strokeWidth = 1;

    Offset scene(double x, double y) =>
        Offset(center.dx + x * pixelsPerMeter, center.dy - y * pixelsPerMeter);

    for (var value = minWorldX; value <= maxWorldX; value++) {
      final major = value % 5 == 0;
      grid.color = major ? const Color(0xffc7d5e5) : const Color(0xffe6edf5);
      canvas.drawLine(
        _transformPoint(scene(value.toDouble(), minWorldY.toDouble())),
        _transformPoint(scene(value.toDouble(), maxWorldY.toDouble())),
        grid,
      );
    }
    for (var value = minWorldY; value <= maxWorldY; value++) {
      final major = value % 5 == 0;
      grid.color = major ? const Color(0xffc7d5e5) : const Color(0xffe6edf5);
      canvas.drawLine(
        _transformPoint(scene(minWorldX.toDouble(), value.toDouble())),
        _transformPoint(scene(maxWorldX.toDouble(), value.toDouble())),
        grid,
      );
    }

    final axis = Paint()..color = const Color(0xff7ea6d2);
    canvas.drawLine(
      _transformPoint(scene(0, minWorldY.toDouble())),
      _transformPoint(scene(0, maxWorldY.toDouble())),
      axis,
    );
    canvas.drawLine(
      _transformPoint(scene(minWorldX.toDouble(), 0)),
      _transformPoint(scene(maxWorldX.toDouble(), 0)),
      axis,
    );

    void label(String text, Offset point) {
      final painter = TextPainter(
        text: TextSpan(
          text: text,
          style: const TextStyle(color: Color(0xff64748b), fontSize: 10),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      final position = _transformPoint(point);
      if (position.dx > -40 &&
          position.dx < size.width + 10 &&
          position.dy > -20 &&
          position.dy < size.height + 10) {
        painter.paint(canvas, position + const Offset(3, 3));
      }
    }

    for (var value = minWorldX; value <= maxWorldX; value++) {
      label('${value}m', scene(value.toDouble(), 0));
    }
    for (var value = minWorldY; value <= maxWorldY; value++) {
      label('${value}m', scene(0, value.toDouble()));
    }
  }

  Offset _scenePoint(Offset viewportPoint) {
    final values = transform.storage;
    final a = values[0];
    final b = values[1];
    final c = values[4];
    final d = values[5];
    final tx = viewportPoint.dx - values[12];
    final ty = viewportPoint.dy - values[13];
    final determinant = a * d - b * c;
    if (determinant.abs() < 0.000001) return viewportPoint;
    return Offset(
      (d * tx - c * ty) / determinant,
      (-b * tx + a * ty) / determinant,
    );
  }

  @override
  bool shouldRepaint(covariant _InfiniteGridPainter oldDelegate) =>
      oldDelegate.transform != transform ||
      oldDelegate.pixelsPerMeter != pixelsPerMeter ||
      oldDelegate.relativeMode != relativeMode;
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
    this.drawGrid = true,
  });

  final List<_SketchPath> paths;
  final List<_SketchPath> travelPaths;
  final _SketchPath? draft;
  final int? selectedIndex;
  final double pixelsPerMeter;
  final bool relativeMode;
  final Set<String> errorSegments;
  final Set<String> warningSegments;
  final bool drawGrid;

  @override
  void paint(Canvas canvas, Size size) {
    if (!drawGrid) {
      _drawContent(canvas, size);
      return;
    }
    _drawContent(canvas, size);
  }

  void _drawContent(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    if (drawGrid) {
      canvas.drawRect(
        Offset.zero & size,
        Paint()..color = const Color(0xfff8fbff),
      );
      final grid = Paint()..strokeWidth = 1;
      for (
        var x = center.dx % pixelsPerMeter;
        x < size.width;
        x += pixelsPerMeter
      ) {
        final major = ((x - center.dx) / pixelsPerMeter).round() % 5 == 0;
        grid.color = major ? const Color(0xffc7d5e5) : const Color(0xffe6edf5);
        canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
      }
      for (
        var x = center.dx % pixelsPerMeter - pixelsPerMeter;
        x >= 0;
        x -= pixelsPerMeter
      ) {
        final major = ((x - center.dx) / pixelsPerMeter).round() % 5 == 0;
        grid.color = major ? const Color(0xffc7d5e5) : const Color(0xffe6edf5);
        canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
      }
      for (
        var y = center.dy % pixelsPerMeter;
        y < size.height;
        y += pixelsPerMeter
      ) {
        final major = ((y - center.dy) / pixelsPerMeter).round() % 5 == 0;
        grid.color = major ? const Color(0xffc7d5e5) : const Color(0xffe6edf5);
        canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
      }
      for (
        var y = center.dy % pixelsPerMeter - pixelsPerMeter;
        y >= 0;
        y -= pixelsPerMeter
      ) {
        final major = ((y - center.dy) / pixelsPerMeter).round() % 5 == 0;
        grid.color = major ? const Color(0xffc7d5e5) : const Color(0xffe6edf5);
        canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
      }
      canvas.drawLine(
        Offset(0, center.dy),
        Offset(size.width, center.dy),
        Paint()..color = const Color(0xff7ea6d2),
      );
      canvas.drawLine(
        Offset(center.dx, 0),
        Offset(center.dx, size.height),
        Paint()..color = const Color(0xff7ea6d2),
      );

      // Keep coordinate labels attached to the visible viewport so the whole
      // workspace remains readable when the tablet canvas gets wider.
      void drawAxisLabel(String text, Offset position) {
        final painter = TextPainter(
          text: TextSpan(
            text: text,
            style: const TextStyle(color: Color(0xff64748b), fontSize: 10),
          ),
          textDirection: TextDirection.ltr,
        )..layout();
        painter.paint(canvas, position);
      }

      final minX = (-center.dx / pixelsPerMeter).floor();
      final maxX = ((size.width - center.dx) / pixelsPerMeter).ceil();
      for (var value = minX; value <= maxX; value++) {
        final x = center.dx + value * pixelsPerMeter;
        drawAxisLabel('${value}m', Offset(x + 3, center.dy + 7));
      }
      final minY = ((center.dy - size.height) / pixelsPerMeter).floor();
      final maxY = (center.dy / pixelsPerMeter).ceil();
      for (var value = minY; value <= maxY; value++) {
        final y = center.dy - value * pixelsPerMeter;
        drawAxisLabel('${value}m', Offset(5, y - 14));
      }
    }

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
