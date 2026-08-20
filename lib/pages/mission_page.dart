part of '../main.dart';

/// 任务页：展示划线步骤，控制任务并发送 LN150 指令。
class _JsonDrawingDialog extends StatefulWidget {
  const _JsonDrawingDialog({required this.device});

  final RoverDevice device;

  @override
  State<_JsonDrawingDialog> createState() => _JsonDrawingDialogState();
}

class _JsonDrawingDialogState extends State<_JsonDrawingDialog> {
  final nameController = TextEditingController(text: 'imported_drawing');
  final jsonController = TextEditingController(
    text: const JsonEncoder.withIndent('  ').convert({
      'layers': [
        {'layer_id': 1, 'name': 'app_json'},
      ],
      'lines': [
        {
          'id': 1,
          'type': 'line',
          'layer_id': 1,
          'start': {'x': 0, 'y': 0, 'z': 0},
          'end': {'x': 3000, 'y': 0, 'z': 0},
        },
      ],
    }),
  );
  String status = '';
  bool busy = false;

  @override
  void dispose() {
    nameController.dispose();
    jsonController.dispose();
    super.dispose();
  }

  void _formatJson() {
    try {
      final decoded = jsonDecode(jsonController.text);
      if (decoded is! Map) throw const FormatException();
      jsonController.text = const JsonEncoder.withIndent('  ').convert(decoded);
      setState(() => status = 'JSON valid');
    } catch (_) {
      setState(() => status = 'Invalid JSON object');
    }
  }

  Future<void> _import() async {
    final name = nameController.text.trim();
    dynamic payload;
    try {
      payload = jsonDecode(jsonController.text);
    } catch (_) {
      setState(() => status = 'Invalid JSON syntax');
      return;
    }
    if (name.isEmpty || payload is! Map) {
      setState(() => status = 'Name and JSON object are required');
      return;
    }

    setState(() {
      busy = true;
      status = 'Sending JSON to rover tools...';
    });
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
    try {
      final request = await client.postUrl(
        Uri.parse(
          'http://${widget.device.ip}:${widget.device.port}/api/drawings/import-json',
        ),
      );
      request.headers.contentType = ContentType.json;
      request.write(jsonEncode({'name': name, 'payload': payload}));
      final response = await request.close().timeout(
        const Duration(seconds: 10),
      );
      final result = jsonDecode(await utf8.decoder.bind(response).join());
      if (!mounted) return;
      if (response.statusCode == 200 && result is Map && result['ok'] == true) {
        Navigator.pop(context, result['file_name']?.toString());
      } else {
        setState(
          () => status = result is Map
              ? result['message']?.toString() ?? 'Import rejected'
              : 'Import rejected',
        );
      }
    } catch (error) {
      if (mounted) setState(() => status = 'Bridge unavailable: $error');
    } finally {
      client.close(force: true);
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('JSON drawing tools'),
    content: SizedBox(
      width: 640,
      height: MediaQuery.sizeOf(context).height * .62,
      child: Column(
        children: [
          TextField(
            controller: nameController,
            decoration: const InputDecoration(
              labelText: 'File name',
              prefixIcon: Icon(Icons.description_outlined),
            ),
          ),
          const SizedBox(height: 12),
          Expanded(
            child: TextField(
              controller: jsonController,
              expands: true,
              maxLines: null,
              minLines: null,
              keyboardType: TextInputType.multiline,
              textAlignVertical: TextAlignVertical.top,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
              decoration: const InputDecoration(
                labelText: 'CAD JSON (coordinates in millimetres)',
                alignLabelWithHint: true,
                border: OutlineInputBorder(),
              ),
            ),
          ),
          const SizedBox(height: 8),
          SizedBox(
            height: 20,
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text(status, maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
          ),
        ],
      ),
    ),
    actions: [
      IconButton(
        tooltip: 'Format and validate JSON',
        onPressed: busy ? null : _formatJson,
        icon: const Icon(Icons.auto_fix_high_rounded),
      ),
      TextButton(
        onPressed: busy ? null : () => Navigator.pop(context),
        child: const Text('Cancel'),
      ),
      FilledButton.icon(
        onPressed: busy ? null : _import,
        icon: busy
            ? const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Icon(Icons.upload_file_rounded),
        label: const Text('Import'),
      ),
    ],
  );
}

class _MissionPage extends StatelessWidget {
  const _MissionPage({
    required this.lineRunning,
    required this.missionPaused,
    required this.emergencyStopped,
    required this.missionStage,
    required this.missionFile,
    required this.missionCurrentId,
    required this.completed,
    required this.total,
    required this.error,
    required this.missionFiles,
    required this.missionFilesLoading,
    required this.gridMap,
    required this.plannedPaths,
    required this.pathAnnotations,
    required this.robotPose,
    required this.poseTrace,
    required this.showLivePose,
    required this.onFileChanged,
    required this.onCreateDrawing,
    required this.onImportJson,
    required this.onRefreshFiles,
    required this.onDeleteFile,
    required this.onStart,
    required this.onPause,
    required this.onResume,
    required this.onCancel,
    required this.onLnCommand,
    required this.onCalibrateLocalization,
    required this.localizationCalibration,
    required this.ln150Ready,
    required this.localizationSource,
    required this.localizationCalibrationAvailable,
  });

  final bool lineRunning;
  final bool missionPaused;
  final bool emergencyStopped;
  final String missionStage;
  final String missionFile;
  final int? missionCurrentId;
  final int completed;
  final int total;
  final String error;
  final List<String> missionFiles;
  final bool missionFilesLoading;
  final Map<String, dynamic> gridMap;
  final List<Map<String, dynamic>> plannedPaths;
  final List<Map<String, dynamic>> pathAnnotations;
  final Map<String, dynamic> robotPose;
  final List<List<double>> poseTrace;
  final bool showLivePose;
  final ValueChanged<String> onFileChanged;
  final VoidCallback onCreateDrawing;
  final VoidCallback onImportJson;
  final VoidCallback onRefreshFiles;
  final ValueChanged<String> onDeleteFile;
  final VoidCallback onStart;
  final VoidCallback onPause;
  final VoidCallback onResume;
  final VoidCallback onCancel;
  final ValueChanged<int> onLnCommand;
  final VoidCallback onCalibrateLocalization;
  final String localizationCalibration;
  final bool ln150Ready;
  final String localizationSource;
  final bool localizationCalibrationAvailable;

  @override
  Widget build(BuildContext context) {
    final hasDrawing = missionFiles.contains(missionFile);
    final canDelete = !const {
      'test_pattern.json',
      'huanong_skeleton.json',
      'square_image.json',
    }.contains(missionFile);
    final drawingPanel = _Panel(
      title: '任务图纸',
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          IconButton(
            tooltip: '同步图纸',
            onPressed: missionFilesLoading ? null : onRefreshFiles,
            icon: missionFilesLoading
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.sync_rounded),
          ),
          IconButton(
            tooltip: '创建图纸',
            onPressed: lineRunning ? null : onCreateDrawing,
            icon: const Icon(Icons.draw_rounded),
          ),
          IconButton(
            tooltip: 'Import JSON drawing',
            onPressed: lineRunning ? null : onImportJson,
            icon: const Icon(Icons.data_object_rounded),
          ),
        ],
      ),
      child: !hasDrawing
          ? _MissionDrawingEmptyState(
              onCreateDrawing: onCreateDrawing,
              onRefresh: onRefreshFiles,
            )
          : Column(
              children: [
                DropdownButtonFormField<String>(
                  initialValue: missionFile,
                  isExpanded: true,
                  decoration: _inputDecoration(
                    '选择 CAD 图纸',
                    Icons.folder_open_rounded,
                  ),
                  items: missionFiles
                      .map(
                        (file) => DropdownMenuItem(
                          value: file,
                          child: Text(file, overflow: TextOverflow.ellipsis),
                        ),
                      )
                      .toList(),
                  onChanged: lineRunning
                      ? null
                      : (value) {
                          if (value != null) onFileChanged(value);
                        },
                ),
                const SizedBox(height: 12),
                Container(
                  height: 300,
                  decoration: BoxDecoration(
                    color: const Color(0xfff8fafc),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: const Color(0xffdce3ea)),
                  ),
                  clipBehavior: Clip.antiAlias,
                  child: plannedPaths.isEmpty
                      ? const _MapEmptyState(text: '正在等待图纸预览')
                      : _EngineeringMapView(
                          lineRunning: lineRunning,
                          gridMap: gridMap,
                          plannedPaths: plannedPaths,
                          pathAnnotations: pathAnnotations,
                          robotPose: robotPose,
                          poseTrace: poseTrace,
                          showLivePose: showLivePose,
                          relativeMode:
                              localizationSource == 'odom_imu_relative',
                        ),
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    const Icon(
                      Icons.description_outlined,
                      size: 18,
                      color: Color(0xff16a66a),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        missionFile,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                    ),
                    Text(
                      '${plannedPaths.length} 条路径',
                      style: const TextStyle(
                        color: Color(0xff64748b),
                        fontSize: 12,
                      ),
                    ),
                    if (canDelete) ...[
                      const SizedBox(width: 6),
                      IconButton(
                        tooltip: '删除当前图纸',
                        onPressed: lineRunning
                            ? null
                            : () => onDeleteFile(missionFile),
                        icon: const Icon(
                          Icons.delete_outline_rounded,
                          color: Color(0xffdc2626),
                        ),
                      ),
                    ],
                  ],
                ),
              ],
            ),
    );
    final executionPanel = _Panel(
      title: '任务执行',
      trailing: _StatusChip(
        text: _missionStageLabel(missionStage),
        color: missionStage == 'failed'
            ? const Color(0xffdc2626)
            : lineRunning
            ? const Color(0xfff59e0b)
            : const Color(0xff16a66a),
      ),
      child: Column(
        children: [
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
            Text(error, style: const TextStyle(color: Color(0xffdc2626))),
          ],
          const SizedBox(height: 12),
          if (!lineRunning)
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: emergencyStopped || !hasDrawing ? null : onStart,
                icon: const Icon(Icons.play_arrow_rounded),
                label: Text(emergencyStopped ? '急停锁定中' : '规划并执行'),
              ),
            )
          else
            Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: emergencyStopped
                        ? null
                        : (missionPaused ? onResume : onPause),
                    icon: Icon(
                      missionPaused
                          ? Icons.play_arrow_rounded
                          : Icons.pause_rounded,
                    ),
                    label: Text(missionPaused ? '继续任务' : '暂停任务'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: onCancel,
                    icon: const Icon(Icons.cancel_outlined),
                    label: const Text('取消任务'),
                  ),
                ),
              ],
            ),
        ],
      ),
    );
    final setupPanel = _Panel(
      title: '定位准备',
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          if (ln150Ready) ...[
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
                ? localizationSource == 'odom_imu_relative'
                      ? '正在重置原点'
                      : '定位校准中'
                : localizationSource == 'odom_imu_relative'
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

    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth < 840) {
          return ListView(
            key: const ValueKey('mission'),
            padding: const EdgeInsets.all(16),
            children: [
              drawingPanel,
              const SizedBox(height: 12),
              executionPanel,
              const SizedBox(height: 12),
              setupPanel,
            ],
          );
        }
        return SingleChildScrollView(
          key: const ValueKey('mission-wide'),
          padding: const EdgeInsets.all(24),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(flex: 62, child: drawingPanel),
              const SizedBox(width: 16),
              Expanded(
                flex: 38,
                child: Column(
                  children: [
                    executionPanel,
                    const SizedBox(height: 16),
                    setupPanel,
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  static String _missionStageLabel(String stage) {
    const labels = {
      'idle': '待启动',
      'planning': '规划中',
      'executing': '执行中',
      'paused': '已暂停',
      'completed': '已完成',
      'cancelled': '已取消',
      'failed': '失败',
    };
    return labels[stage] ?? stage;
  }
}

class _MissionDrawingEmptyState extends StatelessWidget {
  const _MissionDrawingEmptyState({
    required this.onCreateDrawing,
    required this.onRefresh,
  });

  final VoidCallback onCreateDrawing;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) => SizedBox(
    height: 300,
    child: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(
            Icons.folder_open_rounded,
            size: 54,
            color: Color(0xff94a3b8),
          ),
          const SizedBox(height: 12),
          const Text(
            '暂无 CAD 图纸',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
          ),
          const SizedBox(height: 6),
          const Text(
            '同步小车图纸，或在 App 中创建一张新图纸',
            style: TextStyle(color: Color(0xff64748b)),
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            children: [
              OutlinedButton.icon(
                onPressed: onRefresh,
                icon: const Icon(Icons.sync_rounded),
                label: const Text('同步图纸'),
              ),
              FilledButton.icon(
                onPressed: onCreateDrawing,
                icon: const Icon(Icons.draw_rounded),
                label: const Text('创建图纸'),
              ),
            ],
          ),
        ],
      ),
    ),
  );
}
