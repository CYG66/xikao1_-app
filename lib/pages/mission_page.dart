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
    required this.onImportCad,
    required this.onRefreshFiles,
    required this.onDeleteFile,
    required this.onStart,
    required this.onPause,
    required this.onResume,
    required this.onCancel,
    required this.localizationSource,
    required this.localizationValid,
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
  final VoidCallback onImportCad;
  final VoidCallback onRefreshFiles;
  final ValueChanged<String> onDeleteFile;
  final VoidCallback onStart;
  final VoidCallback onPause;
  final VoidCallback onResume;
  final VoidCallback onCancel;
  final String localizationSource;
  final bool localizationValid;

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 840;
    final hasDrawing = missionFiles.contains(missionFile);
    final canDelete = !const {
      'test_pattern.json',
      'huanong_skeleton.json',
      'square_image.json',
    }.contains(missionFile);
    final drawingPanel = _Panel(
      title: '任务图纸',
      expandChild: wide,
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
            tooltip: '创建或修改图纸',
            onPressed: lineRunning ? null : onCreateDrawing,
            icon: const Icon(Icons.edit_note_rounded),
          ),
          IconButton(
            tooltip: '导入 CAD/DXF',
            onPressed: lineRunning ? null : onImportCad,
            icon: const Icon(Icons.upload_file_rounded),
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
              onImportCad: onImportCad,
            )
          : LayoutBuilder(
              builder: (context, panelConstraints) {
                final mapHeight = panelConstraints.maxHeight.isFinite
                    ? math.max(300.0, panelConstraints.maxHeight - 235)
                    : 300.0;
                return Column(
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
                              child: Text(
                                file,
                                overflow: TextOverflow.ellipsis,
                              ),
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
                      height: mapHeight,
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
                    const SizedBox(height: 8),
                    _MissionDrawingSummary(
                      file: missionFile,
                      pathCount: plannedPaths.length,
                      total: total,
                      localizationValid: localizationValid,
                    ),
                  ],
                );
              },
            ),
    );
    final executionContent = Column(
      children: [
        _MissionStageBanner(
          stage: missionStage,
          lineRunning: lineRunning,
          paused: missionPaused,
          completed: completed,
          total: total,
        ),
        const SizedBox(height: 8),
        _MissionReadinessPanel(
          hasDrawing: hasDrawing,
          localizationValid: localizationValid,
          emergencyStopped: emergencyStopped,
          total: total,
        ),
        const SizedBox(height: 12),
        _MissionLocalizationModeCard(
          totalStationMode: localizationSource == 'ln150_imu',
          relativeMode: localizationSource == 'odom_imu_relative',
          localizationValid: localizationValid,
        ),
        const SizedBox(height: 12),
        _MissionExecutionTimeline(
          stage: missionStage,
          completed: completed,
          total: total,
          localizationValid: localizationValid,
        ),
        const SizedBox(height: 10),
        _MissionProgressSummary(
          stage: missionStage,
          completed: completed,
          total: total,
          currentId: missionCurrentId,
        ),
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
              onPressed:
                  emergencyStopped ||
                      !hasDrawing ||
                      localizationSource == 'unavailable' ||
                      !localizationValid
                  ? null
                  : onStart,
              icon: const Icon(Icons.play_arrow_rounded),
              label: Text(
                emergencyStopped
                    ? '急停锁定中'
                    : localizationSource == 'unavailable'
                    ? '等待定位模式'
                    : !localizationValid
                    ? '等待有效定位'
                    : '规划并执行',
              ),
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
    );
    final executionPanel = _Panel(
      title: localizationSource == 'ln150_imu'
          ? '全站仪任务执行'
          : localizationSource == 'odom_imu_relative'
          ? '相对定位任务执行'
          : '任务执行（定位未就绪）',
      trailing: _StatusChip(
        text: _missionStageLabel(missionStage),
        color: missionStage == 'failed'
            ? const Color(0xffdc2626)
            : lineRunning
            ? const Color(0xfff59e0b)
            : const Color(0xff16a66a),
      ),
      expandChild: wide,
      child: wide
          ? SingleChildScrollView(child: executionContent)
          : executionContent,
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
            ],
          );
        }
        return SizedBox(
          key: const ValueKey('mission-wide'),
          height: constraints.maxHeight,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(
                  flex: 62,
                  child: SizedBox(
                    height: constraints.maxHeight - 32,
                    child: drawingPanel,
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  flex: 38,
                  child: SizedBox(
                    height: constraints.maxHeight - 32,
                    child: executionPanel,
                  ),
                ),
              ],
            ),
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

class _MissionDrawingSummary extends StatelessWidget {
  const _MissionDrawingSummary({
    required this.file,
    required this.pathCount,
    required this.total,
    required this.localizationValid,
  });
  final String file;
  final int pathCount, total;
  final bool localizationValid;

  @override
  Widget build(BuildContext context) => _MissionInlineSection(
    title: '图纸摘要',
    child: Wrap(
      spacing: 24,
      runSpacing: 10,
      children: [
        _SummaryItem(Icons.description_outlined, '当前图纸', file),
        _SummaryItem(Icons.route_rounded, '路径数量', '$pathCount 条'),
        _SummaryItem(
          Icons.segment_rounded,
          '任务分段',
          total == 0 ? '未生成' : '$total 段',
        ),
        _SummaryItem(
          Icons.gps_fixed_rounded,
          '定位状态',
          localizationValid ? '有效' : '未就绪',
        ),
      ],
    ),
  );
}

class _MissionReadinessPanel extends StatelessWidget {
  const _MissionReadinessPanel({
    required this.hasDrawing,
    required this.localizationValid,
    required this.emergencyStopped,
    required this.total,
  });
  final bool hasDrawing, localizationValid, emergencyStopped;
  final int total;

  @override
  Widget build(BuildContext context) {
    final checks = [
      ('图纸已选择', hasDrawing),
      ('定位有效', localizationValid),
      ('急停已解除', !emergencyStopped),
      ('路径已生成', total > 0),
    ];
    final passed = checks.where((check) => check.$2).length;
    return _CollapsiblePanel(
      title: '执行前检查',
      statusText: '$passed/${checks.length} 通过',
      statusColor: passed == checks.length
          ? const Color(0xff16a66a)
          : const Color(0xffb45309),
      child: Column(
        children: [
          for (final check in checks)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 5),
              child: Row(
                children: [
                  Icon(
                    check.$2
                        ? Icons.check_circle_rounded
                        : Icons.warning_amber_rounded,
                    size: 18,
                    color: check.$2
                        ? const Color(0xff16a66a)
                        : const Color(0xfff59e0b),
                  ),
                  const SizedBox(width: 8),
                  Expanded(child: Text(check.$1)),
                  Text(
                    check.$2 ? '通过' : '待处理',
                    style: TextStyle(
                      fontSize: 12,
                      color: check.$2
                          ? const Color(0xff15803d)
                          : const Color(0xffb45309),
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _SummaryItem extends StatelessWidget {
  const _SummaryItem(this.icon, this.label, this.value);
  final IconData icon;
  final String label, value;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Icon(icon, size: 18, color: const Color(0xff64748b)),
      const SizedBox(width: 6),
      Text('$label：', style: const TextStyle(color: Color(0xff64748b))),
      Text(value, style: const TextStyle(fontWeight: FontWeight.w700)),
    ],
  );
}

class _MissionInlineSection extends StatelessWidget {
  const _MissionInlineSection({required this.title, required this.child});
  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.fromLTRB(2, 8, 2, 12),
    decoration: const BoxDecoration(
      border: Border(bottom: BorderSide(color: Color(0xffe2e8f0))),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
        ),
        const SizedBox(height: 8),
        child,
      ],
    ),
  );
}

class _MissionStageBanner extends StatelessWidget {
  const _MissionStageBanner({
    required this.stage,
    required this.lineRunning,
    required this.paused,
    required this.completed,
    required this.total,
  });

  final String stage;
  final bool lineRunning, paused;
  final int completed, total;

  @override
  Widget build(BuildContext context) {
    final progress = total > 0 ? (completed / total).clamp(0.0, 1.0) : 0.0;
    final isError = stage == 'failed';
    final isDone = stage == 'completed';
    final color = isError
        ? const Color(0xffdc2626)
        : isDone
        ? const Color(0xff16a66a)
        : paused
        ? const Color(0xffb45309)
        : const Color(0xff2563eb);
    final title = isError
        ? '任务执行异常'
        : isDone
        ? '任务已完成'
        : paused
        ? '任务已暂停'
        : lineRunning
        ? '任务执行中'
        : stage == 'planning'
        ? '正在规划路径'
        : '任务待启动';
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 9),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .08),
        border: Border.all(color: color.withValues(alpha: .28)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(
            isError
                ? Icons.error_rounded
                : isDone
                ? Icons.check_circle_rounded
                : paused
                ? Icons.pause_circle_filled_rounded
                : Icons.play_circle_fill_rounded,
            color: color,
            size: 22,
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: TextStyle(color: color, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 5),
                ClipRRect(
                  borderRadius: BorderRadius.circular(3),
                  child: LinearProgressIndicator(
                    value: total > 0 ? progress : null,
                    minHeight: 5,
                    color: color,
                    backgroundColor: color.withValues(alpha: .16),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          Text(
            total > 0 ? '$completed/$total' : '--',
            style: TextStyle(color: color, fontWeight: FontWeight.w800),
          ),
        ],
      ),
    );
  }
}

class _MissionExecutionTimeline extends StatelessWidget {
  const _MissionExecutionTimeline({
    required this.stage,
    required this.completed,
    required this.total,
    required this.localizationValid,
  });

  final String stage;
  final int completed;
  final int total;
  final bool localizationValid;

  @override
  Widget build(BuildContext context) {
    final active = switch (stage) {
      'planning' || 'planning_preview' => 1,
      'ready' || 'pending_execution' => 2,
      'executing' || 'paused' || 'completed' || 'cancelled' => 3,
      'failed' => -1,
      _ => 0,
    };
    const labels = ['准备', '路径规划', '执行确认', '分段执行', '验收'];
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
      decoration: BoxDecoration(
        color: const Color(0xfff8fafc),
        border: Border.all(color: const Color(0xffdbe4ec)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('任务执行阶段', style: TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 10),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (var i = 0; i < labels.length; i++) ...[
                Expanded(
                  child: _StageDot(
                    label: labels[i],
                    state: active < 0
                        ? 'error'
                        : i < active
                        ? 'done'
                        : i == active
                        ? 'active'
                        : 'pending',
                  ),
                ),
                if (i != labels.length - 1)
                  Expanded(
                    child: Container(
                      height: 2,
                      margin: const EdgeInsets.only(top: 10),
                      color: i < active
                          ? const Color(0xff16a66a)
                          : const Color(0xffdbe4ec),
                    ),
                  ),
              ],
            ],
          ),
          const SizedBox(height: 8),
          if (stage == 'completed')
            const Text(
              '任务已完成，已进入验收阶段',
              style: TextStyle(color: Color(0xff15803d), fontSize: 12),
            ),
          if (stage == 'failed')
            const Text(
              '任务失败，请检查原因后重新规划或恢复',
              style: TextStyle(color: Color(0xffdc2626), fontSize: 12),
            ),
          if (stage == 'completed' || stage == 'failed')
            const SizedBox(height: 4),
          Text(
            total > 0 ? '已完成 $completed / $total 个分段' : '等待路径分段结果',
            style: const TextStyle(color: Color(0xff64748b), fontSize: 12),
          ),
          if (!localizationValid)
            const Padding(
              padding: EdgeInsets.only(top: 5),
              child: Text(
                '定位未有效，执行阶段将保持锁定',
                style: TextStyle(color: Color(0xffb45309), fontSize: 12),
              ),
            ),
        ],
      ),
    );
  }
}

class _MissionProgressSummary extends StatelessWidget {
  const _MissionProgressSummary({
    required this.stage,
    required this.completed,
    required this.total,
    required this.currentId,
  });
  final String stage;
  final int completed, total;
  final int? currentId;

  @override
  Widget build(BuildContext context) {
    final progress = total > 0 ? (completed / total).clamp(0.0, 1.0) : 0.0;
    final label = switch (stage) {
      'planning' || 'planning_preview' => '正在生成可执行路径',
      'ready' || 'pending_execution' => '路径已就绪，等待开始',
      'executing' => '小车正在执行当前路径',
      'paused' => '任务已暂停，可继续执行',
      'completed' => '全部路径已执行完成',
      'cancelled' => '任务已取消',
      'failed' => '任务执行失败',
      _ => '等待任务操作',
    };
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: const Color(0xfff8fafc),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  label,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              Text(
                total > 0 ? '${(progress * 100).round()}%' : '--',
                style: const TextStyle(
                  color: Color(0xff2563eb),
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          LinearProgressIndicator(
            value: total > 0 ? progress : null,
            minHeight: 6,
          ),
          const SizedBox(height: 6),
          Text(
            total > 0
                ? '分段 $completed / $total · 当前 ${currentId ?? '--'}'
                : '尚未收到任务分段数据',
            style: const TextStyle(fontSize: 12, color: Color(0xff64748b)),
          ),
        ],
      ),
    );
  }
}

class _StageDot extends StatelessWidget {
  const _StageDot({required this.label, required this.state});
  final String label;
  final String state;

  @override
  Widget build(BuildContext context) {
    final color = switch (state) {
      'done' => const Color(0xff16a66a),
      'active' => const Color(0xff2563eb),
      'error' => const Color(0xffdc2626),
      _ => const Color(0xff94a3b8),
    };
    return Column(
      children: [
        Icon(
          state == 'done'
              ? Icons.check_circle_rounded
              : state == 'error'
              ? Icons.error_rounded
              : state == 'active'
              ? Icons.radio_button_checked_rounded
              : Icons.radio_button_unchecked_rounded,
          color: color,
          size: 22,
        ),
        const SizedBox(height: 4),
        Text(
          label,
          textAlign: TextAlign.center,
          style: TextStyle(
            color: color,
            fontSize: 11,
            fontWeight: FontWeight.w700,
          ),
        ),
      ],
    );
  }
}

class _MissionLocalizationModeCard extends StatelessWidget {
  const _MissionLocalizationModeCard({
    required this.totalStationMode,
    required this.relativeMode,
    required this.localizationValid,
  });

  final bool totalStationMode;
  final bool relativeMode;
  final bool localizationValid;

  @override
  Widget build(BuildContext context) {
    final Color color;
    final IconData icon;
    final String title;
    final String detail;
    final String state;
    if (totalStationMode) {
      color = const Color(0xff047857);
      icon = Icons.public_rounded;
      title = '全站仪任务执行';
      detail = '使用 LN150 + IMU 工程坐标闭环，路径按全局坐标规划与执行';
      state = localizationValid ? '全局定位有效' : '等待全局定位';
    } else if (relativeMode) {
      color = const Color(0xffb45309);
      icon = Icons.trip_origin_rounded;
      title = '相对定位任务执行';
      detail = '小车运行环境启动时的位置为原点 0,0、车头为 0°；规划读取当前相对位姿，适合短距离任务';
      state = localizationValid ? '相对定位有效' : '等待相对定位';
    } else {
      color = const Color(0xff64748b);
      icon = Icons.location_disabled_rounded;
      title = '定位模式未就绪';
      detail = '后端尚未确认全站仪或相对定位来源，任务执行已锁定';
      state = '不可执行';
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.07),
        border: Border.all(color: color.withValues(alpha: 0.55)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 24),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        title,
                        style: const TextStyle(fontWeight: FontWeight.w800),
                      ),
                    ),
                    Text(
                      state,
                      style: TextStyle(
                        color: color,
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 5),
                Text(
                  detail,
                  style: const TextStyle(
                    color: Color(0xff475569),
                    fontSize: 12,
                    height: 1.35,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _MissionDrawingEmptyState extends StatelessWidget {
  const _MissionDrawingEmptyState({
    required this.onCreateDrawing,
    required this.onRefresh,
    required this.onImportCad,
  });

  final VoidCallback onCreateDrawing;
  final VoidCallback onRefresh;
  final VoidCallback onImportCad;

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
              OutlinedButton.icon(
                onPressed: onImportCad,
                icon: const Icon(Icons.upload_file_rounded),
                label: const Text('导入 CAD'),
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
