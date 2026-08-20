part of '../main.dart';

/// 设置页：查看当前设备并调整划线宽度等 App 参数。
class _AgentPage extends StatefulWidget {
  const _AgentPage({
    required this.device,
    required this.bridgeConnected,
    required this.agentMotionNotifier,
    required this.onStopAgentMotion,
    required this.clientId,
  });

  final RoverDevice device;
  final bool bridgeConnected;
  final ValueListenable<int> agentMotionNotifier;
  final VoidCallback onStopAgentMotion;
  final String clientId;

  @override
  State<_AgentPage> createState() => _AgentPageState();
}

class _AgentPageState extends State<_AgentPage> {
  static const int _maxConversations = 20;
  static const int _maxMessages = 200;
  static const int _maxRequestHistory = 4;
  static const _welcomeMessage = _AgentChatItem(
    role: 'assistant',
    content: '我可以检查设备状态、解释故障、规划操作，并在你确认后调用机器人工具。',
  );
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<_AgentConversation> _conversations = [];
  List<_AgentChatItem> _messages = [_welcomeMessage];
  String? _conversationId;
  bool _sending = false;
  bool _historyLoaded = false;
  String _agentMode = 'base';
  bool _projectsLoading = false;
  List<Map<String, dynamic>> _projects = const [];
  String? _selectedProjectId;
  Timer? _projectTimer;
  int _inputTokens = 0;
  int _outputTokens = 0;

  int get _totalTokens => _inputTokens + _outputTokens;
  String get _deviceKey => '${widget.device.ip}:${widget.device.port}';

  @override
  void initState() {
    super.initState();
    unawaited(_loadHistory());
    if (widget.bridgeConnected && _agentMode == 'advanced') {
      unawaited(_loadProjects());
    }
    _projectTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      if (widget.bridgeConnected && _agentMode == 'advanced' && !_projectsLoading) {
        unawaited(_loadProjects(silent: true));
      }
    });
  }

  @override
  void didUpdateWidget(covariant _AgentPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.bridgeConnected &&
        _agentMode == 'advanced' &&
        (!oldWidget.bridgeConnected || oldWidget.device != widget.device)) {
      unawaited(_loadProjects());
    }
    if ((!widget.bridgeConnected || _agentMode != 'advanced') &&
        _projects.isNotEmpty) {
      setState(() {
        _projects = const [];
        _selectedProjectId = null;
      });
    }
  }

  @override
  void dispose() {
    unawaited(_persistHistory());
    _projectTimer?.cancel();
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Map<String, dynamic>? get _selectedProject {
    for (final project in _projects) {
      if (project['id']?.toString() == _selectedProjectId) return project;
    }
    return _projects.isEmpty ? null : _projects.first;
  }

  Future<void> _loadProjects({bool silent = false}) async {
    if (!widget.bridgeConnected || _agentMode != 'advanced' || _projectsLoading)
      return;
    _projectsLoading = true;
    if (!silent && mounted) setState(() {});
    try {
      final result = await _get('/api/agent/projects?limit=20');
      final raw = result['projects'] as List? ?? const [];
      final projects = raw
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();
      // The list endpoint is intentionally lightweight. Refresh the selected
      // project detail as well so planning/execution/report fields are not
      // left one polling cycle behind the backend lifecycle.
      final selectedId = _selectedProjectId;
      if (selectedId != null && projects.any(
        (item) => item['id']?.toString() == selectedId,
      )) {
        try {
          final detail = await _get('/api/agent/projects/$selectedId');
          final value = detail['project'];
          if (value is Map) {
            final updated = Map<String, dynamic>.from(value);
            final index = projects.indexWhere(
              (item) => item['id']?.toString() == selectedId,
            );
            if (index >= 0) projects[index] = updated;
          }
        } catch (_) {
          // Keep the list response usable during a transient detail failure.
        }
      }
      if (!mounted) return;
      setState(() {
        _projects = projects;
        if (projects.isEmpty) {
          _selectedProjectId = null;
        } else if (!projects.any(
          (item) => item['id']?.toString() == _selectedProjectId,
        )) {
          _selectedProjectId = projects.first['id']?.toString();
        }
      });
    } catch (_) {
      if (!silent && mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('无法读取 Agent 项目')));
      }
    } finally {
      _projectsLoading = false;
      if (!silent && mounted) setState(() {});
    }
  }

  Future<void> _runProjectAction(
    String suffix, {
    String method = 'post',
    Map<String, Object?> body = const {},
  }) async {
    final project = _selectedProject;
    final id = project?['id']?.toString();
    if (id == null || _sending) return;
    setState(() => _sending = true);
    try {
      final path = '/api/agent/projects/$id/$suffix';
      final result = method == 'get'
          ? await _get(path)
          : await _post(path, body);
      final pending = result['pending_action'] is Map
          ? Map<String, dynamic>.from(result['pending_action'] as Map)
          : null;
      final report = result['report'];
      if (!mounted) return;
      setState(() {
        _messages.add(
          _AgentChatItem(
            role: 'assistant',
            content:
                result['message']?.toString() ??
                _projectResultText(suffix, result, method),
            pendingAction: pending,
            jsonText: report is Map
                ? const JsonEncoder.withIndent('  ').convert(report)
                : null,
            isError: result['ok'] != true,
          ),
        );
      });
      await _loadProjects(silent: true);
    } catch (error) {
      if (mounted) {
        setState(
          () => _messages.add(
            _AgentChatItem(
              role: 'assistant',
              content: '项目操作失败：$error',
              isError: true,
            ),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _sending = false);
        unawaited(_loadProjects(silent: true));
        _saveHistory();
        _scrollToBottom();
      }
    }
  }

  Future<void> _selectProjectVariant(String variantId) async {
    final id = _selectedProject?['id']?.toString();
    if (id == null || _sending) return;
    setState(() => _sending = true);
    try {
      final result = await _post('/api/agent/projects/$id/select-variant', {
        'variant_id': variantId,
      });
      if (result['ok'] != true) throw StateError('候选方案无法选择');
      await _loadProjects(silent: true);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  static String _projectResultText(
    String action,
    Map<String, dynamic> result,
    String method,
  ) {
    if (action == 'report') {
      final report = result['report'] is Map
          ? Map<String, dynamic>.from(result['report'] as Map)
          : const <String, dynamic>{};
      return '项目验收结论：${report['verdict'] ?? '未生成'}。';
    }
    if (action == 'request-execution') return '执行请求已生成，请检查后确认。';
    if (action == 'recovery') {
      return method == 'get' ? '恢复评估已更新。' : '恢复规划已提交，等待 ROS2 返回。';
    }
    if (action == 'plan') return '项目规划已提交，等待 ROS2 返回。';
    return result['ok'] == true ? '项目状态已刷新。' : '项目操作未完成。';
  }

  Future<void> _loadHistory() async {
    try {
      final raw = await AgentChatPreferences.load();
      final decoded = raw == null || raw.isEmpty ? null : jsonDecode(raw);
      if (decoded is List) {
        _conversations.addAll(
          decoded
              .whereType<Map>()
              .map(
                (item) => _AgentConversation.fromJson(
                  Map<String, dynamic>.from(item),
                ),
              )
              .where((item) => item.messages.isNotEmpty),
        );
      }
    } catch (_) {
      _conversations.clear();
    }
    if (!mounted) return;
    final matching =
        _conversations
            .where(
              (item) => item.deviceKey == _deviceKey && item.mode == _agentMode,
            )
            .toList()
          ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    setState(() {
      _historyLoaded = true;
      if (matching.isEmpty) {
        _startNewConversation(notify: false);
      } else {
        _activateConversation(matching.first, notify: false);
      }
    });
    _scrollToBottom();
  }

  void _startNewConversation({bool notify = true}) {
    final now = DateTime.now();
    final conversation = _AgentConversation(
      id: now.microsecondsSinceEpoch.toString(),
      deviceKey: _deviceKey,
      mode: _agentMode,
      title: '新会话',
      createdAt: now,
      updatedAt: now,
      messages: [_welcomeMessage],
    );
    _conversations.insert(0, conversation);
    _activateConversation(conversation, notify: false);
    _saveHistory();
    if (notify && mounted) setState(() {});
  }

  void _switchAgentMode(String mode) {
    if (mode == _agentMode) return;
    _syncActiveConversation();
    _agentMode = mode;
    final matching =
        _conversations
            .where((item) => item.deviceKey == _deviceKey && item.mode == mode)
            .toList()
          ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    if (matching.isEmpty) {
      _startNewConversation(notify: false);
    } else {
      _activateConversation(matching.first, notify: false);
    }
    if (mode == 'base') {
      _projects = const [];
      _selectedProjectId = null;
    } else if (widget.bridgeConnected) {
      unawaited(_loadProjects());
    }
    if (mounted) setState(() {});
    _saveHistory();
    _scrollToBottom();
  }

  void _activateConversation(
    _AgentConversation conversation, {
    bool notify = true,
  }) {
    _conversationId = conversation.id;
    _messages = List<_AgentChatItem>.from(conversation.messages);
    _inputTokens = conversation.inputTokens;
    _outputTokens = conversation.outputTokens;
    if (notify && mounted) {
      setState(() {});
      _scrollToBottom();
    }
  }

  Future<void> _manageConversations() async {
    final current =
        _conversations.where((item) => item.deviceKey == _deviceKey).toList()
          ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    if (current.isEmpty || !_historyLoaded || _sending) return;
    final selected = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('最近会话'),
        content: SizedBox(
          width: 360,
          child: ListView(
            shrinkWrap: true,
            children: [
              for (final conversation in current)
                ListTile(
                  dense: true,
                  title: Text(
                    conversation.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  subtitle: Text(
                    '${conversation.messages.length} 条消息',
                    style: const TextStyle(fontSize: 12),
                  ),
                  trailing: IconButton(
                    tooltip: '删除会话',
                    icon: const Icon(
                      Icons.delete_outline,
                      color: Color(0xffdc2626),
                    ),
                    onPressed: () => Navigator.pop(context, conversation.id),
                  ),
                  onTap: () {
                    Navigator.pop(context);
                    _activateConversation(conversation);
                  },
                ),
              const Divider(),
              ListTile(
                dense: true,
                leading: const Icon(
                  Icons.delete_sweep_outlined,
                  color: Color(0xffdc2626),
                ),
                title: const Text('清空当前设备的全部会话'),
                onTap: () => Navigator.pop(context, '__clear__'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('关闭'),
          ),
        ],
      ),
    );
    if (!mounted || selected == null) return;
    if (selected == '__clear__') {
      final confirmed = await _confirmConversationAction(
        '清空会话',
        '将删除当前设备的全部本地聊天记录，不会影响小车任务、项目、图纸和审计记录。',
      );
      if (confirmed) _clearDeviceConversations();
      return;
    }
    final conversation = _conversationById(selected);
    if (conversation == null) return;
    final confirmed = await _confirmConversationAction(
      '删除会话',
      '确定删除“${conversation.title}”吗？此操作只删除本地聊天记录。',
    );
    if (confirmed) _deleteConversation(selected);
  }

  Future<bool> _confirmConversationAction(String title, String message) async {
    return await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text(title),
            content: Text(message),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('取消'),
              ),
              FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xffdc2626),
                ),
                onPressed: () => Navigator.pop(context, true),
                child: const Text('确认删除'),
              ),
            ],
          ),
        ) ??
        false;
  }

  void _deleteConversation(String id) {
    _conversations.removeWhere(
      (item) => item.id == id && item.deviceKey == _deviceKey,
    );
    if (_conversationId == id) {
      _conversationId = null;
      _messages = [_welcomeMessage];
      _inputTokens = 0;
      _outputTokens = 0;
      _startNewConversation(notify: false);
    }
    _saveHistory();
    if (mounted) setState(() {});
  }

  void _clearDeviceConversations() {
    _conversations.removeWhere((item) => item.deviceKey == _deviceKey);
    _conversationId = null;
    _messages = [_welcomeMessage];
    _inputTokens = 0;
    _outputTokens = 0;
    _startNewConversation(notify: false);
    _saveHistory();
    if (mounted) setState(() {});
  }

  _AgentConversation? _conversationById(String id) {
    for (final conversation in _conversations) {
      if (conversation.id == id) return conversation;
    }
    return null;
  }

  String _conversationTitle(String text) {
    final normalized = text.replaceAll(RegExp(r'\s+'), ' ').trim();
    return normalized.length <= 18
        ? normalized
        : '${normalized.substring(0, 18)}…';
  }

  void _syncActiveConversation() {
    final index = _conversations.indexWhere(
      (item) => item.id == _conversationId,
    );
    if (index < 0) return;
    final current = _conversations[index];
    final userMessages = _messages
        .where((item) => item.role == 'user')
        .toList();
    _conversations[index] = current.copyWith(
      title: userMessages.isEmpty
          ? current.title
          : _conversationTitle(userMessages.first.content),
      updatedAt: DateTime.now(),
      messages: _messages.length <= _maxMessages
          ? List<_AgentChatItem>.from(_messages)
          : _messages.sublist(_messages.length - _maxMessages),
      inputTokens: _inputTokens,
      outputTokens: _outputTokens,
    );
  }

  void _saveHistory() {
    _syncActiveConversation();
    _conversations.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    if (_conversations.length > _maxConversations) {
      _conversations.removeRange(_maxConversations, _conversations.length);
    }
    unawaited(_persistHistory());
  }

  Future<void> _persistHistory() async {
    _syncActiveConversation();
    await AgentChatPreferences.save(
      jsonEncode(_conversations.map((item) => item.toJson()).toList()),
    );
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
    if (_agentMode == 'base' &&
        RegExp(r'^(确认|确认执行|执行|好的|开始)$').hasMatch(text)) {
      for (var index = _messages.length - 1; index >= 0; index--) {
        final pending = _messages[index].pendingAction;
        if (pending != null &&
            (pending['name']?.toString() == 'drive_robot' ||
                pending['name']?.toString() == 'drive_sequence')) {
          setState(() {
            _messages.add(_AgentChatItem(role: 'user', content: text));
            _controller.clear();
          });
          await _confirm(pending, true);
          return;
        }
      }
    }

    // Persisted conversations may contain roles from older Agent versions.
    // FastAPI accepts only user/assistant messages for the chat history.
    final fullHistory = _messages
        .where(
          (item) =>
              (item.role == 'user' || item.role == 'assistant') &&
              item.content.trim().isNotEmpty,
        )
        .map(
          (item) => {
            'role': item.role,
            'content': item.content.length <= 4000
                ? item.content
                : item.content.substring(0, 4000),
          },
        )
        .toList();
    final history = fullHistory.length <= _maxRequestHistory
        ? fullHistory
        : fullHistory.sublist(fullHistory.length - _maxRequestHistory);
    setState(() {
      _messages.add(_AgentChatItem(role: 'user', content: text));
      _messages.add(
        const _AgentChatItem(role: 'assistant', content: '正在分析...'),
      );
      _controller.clear();
      _sending = true;
    });
    final assistantIndex = _messages.length - 1;
    _saveHistory();
    _scrollToBottom();

    try {
      var streamedText = '';
      final result = await _postStream(
        '/api/agent/chat/stream',
        {'message': text, 'history': history, 'mode': _agentMode},
        onDelta: (delta) {
          streamedText += delta;
          if (!mounted || assistantIndex >= _messages.length) return;
          setState(() {
            _messages[assistantIndex] = _messages[assistantIndex].copyWith(
              content: streamedText,
            );
          });
          _scrollToBottom();
        },
      );
      final usage = result['usage'] is Map
          ? Map<String, dynamic>.from(result['usage'] as Map)
          : const <String, dynamic>{};
      final pending = result['pending_action'] is Map
          ? Map<String, dynamic>.from(result['pending_action'] as Map)
          : null;
      final responseText = result['message']?.toString() ?? streamedText;
      final pendingPreview = _agentPreviewPaths(pending?['preview_paths']);
      if (!mounted) return;
      setState(() {
        _inputTokens += (usage['input_tokens'] as num?)?.toInt() ?? 0;
        _outputTokens += (usage['output_tokens'] as num?)?.toInt() ?? 0;
        _messages[assistantIndex] = _AgentChatItem(
          role: 'assistant',
          content: responseText,
          pendingAction: pending,
          previewPaths: pendingPreview.isNotEmpty
              ? pendingPreview
              : _agentPreviewPathsFromJson(responseText),
          jsonText:
              _agentJsonText(pending?['motion_json'] ?? pending?['arguments']) ??
              _agentJsonTextFromContent(responseText),
          isError: result['ok'] != true,
        );
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _messages[assistantIndex] = _AgentChatItem(
          role: 'assistant',
          content: '请求失败：$error',
          isError: true,
        );
      });
    } finally {
      if (mounted) {
        setState(() => _sending = false);
        _saveHistory();
        _scrollToBottom();
      }
    }
  }

  Future<void> _showProjectDrawingVersions(
    Map<String, dynamic> drawingVersion,
    String projectId,
    String status,
  ) async {
    final drawingId = drawingVersion['drawing_id']?.toString();
    if (drawingId == null || drawingId.isEmpty || _sending) return;
    setState(() => _sending = true);
    try {
      final result = await _get('/api/drawings/versions/$drawingId');
      final versions = (result['versions'] as List? ?? const [])
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();
      if (!mounted) return;
      final selected = await showDialog<Map<String, dynamic>>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('图纸版本历史'),
          content: SizedBox(
            width: 460,
            child: versions.isEmpty
                ? const Text('没有可用的历史版本。')
                : ListView.separated(
                    shrinkWrap: true,
                    itemCount: versions.length,
                    separatorBuilder: (_, __) => const Divider(height: 1),
                    itemBuilder: (context, index) {
                      final version = versions[index];
                      return ListTile(
                        dense: true,
                        title: Text(
                          'V${version['version'] ?? '-'} · ${version['file_name'] ?? ''}',
                        ),
                        subtitle: Text(
                          version['change_summary']?.toString().isNotEmpty == true
                              ? version['change_summary'].toString()
                              : '无修改说明',
                        ),
                        trailing: const Icon(Icons.restore_rounded),
                        enabled: !{
                          'planning',
                          'pending_execution',
                          'executing',
                          'paused',
                        }.contains(status),
                        onTap: () => Navigator.of(context).pop(version),
                      );
                    },
                  ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('关闭'),
            ),
          ],
        ),
      );
      if (selected == null || !mounted) return;
      final fileName = selected['file_name']?.toString();
      if (fileName == null || fileName.isEmpty) return;
      final rollback = await _post(
        '/api/drawings/versions/$fileName/rollback',
        {'project_id': projectId},
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(rollback['message']?.toString() ?? '图纸版本已回退')),
      );
      await _loadProjects(silent: true);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('读取或回退图纸版本失败：$error')),
        );
      }
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _copyAgentMessage(String content) async {
    await Clipboard.setData(ClipboardData(text: content));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('已复制消息内容'), duration: Duration(seconds: 1)),
    );
  }

  void _quoteAgentMessage(String content) {
    final quoted = content
        .trim()
        .split('\n')
        .map((line) => '> $line')
        .join('\n');
    setState(() {
      _controller.text = '$quoted\n\n';
      _controller.selection = TextSelection.fromPosition(
        TextPosition(offset: _controller.text.length),
      );
    });
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('已引用到输入框'), duration: Duration(seconds: 1)),
    );
  }

  void _regenerateAgentMessage(_AgentChatItem item) {
    final index = _messages.indexOf(item);
    if (index <= 0) return;
    for (var cursor = index - 1; cursor >= 0; cursor--) {
      if (_messages[cursor].role == 'user') {
        _send(_messages[cursor].content);
        return;
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
        'client_id': widget.clientId,
      });
      final shouldPlan =
          approved &&
          result['ok'] == true &&
          result['next_action'] == 'plan_preview' &&
          result['file_name'] is String;
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
            previewPaths: _agentPreviewPaths(result['preview_paths']),
            jsonText: _agentJsonText(result['drawing_json']),
            isError: result['ok'] != true,
          ),
        );
      });
      if (shouldPlan) {
        await _prepareAgentDrawing(result['file_name'] as String);
      }
      await _loadProjects(silent: true);
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
        _saveHistory();
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

  Future<Map<String, dynamic>> _postStream(
    String path,
    Map<String, Object?> body, {
    required ValueChanged<String> onDelta,
  }) async {
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
      if (response.statusCode >= 400) {
        final errorBody = await response.transform(utf8.decoder).join();
        var detail = 'HTTP ${response.statusCode}';
        try {
          final decoded = jsonDecode(errorBody);
          if (decoded is Map && decoded['detail'] != null) {
            detail = decoded['detail'] is List
                ? (decoded['detail'] as List)
                      .map(
                        (item) => item is Map
                            ? '${item['loc'] ?? ''}: ${item['msg'] ?? ''}'
                            : item.toString(),
                      )
                      .join('；')
                : decoded['detail'].toString();
          }
        } catch (_) {
          if (errorBody.trim().isNotEmpty) detail = errorBody.trim();
        }
        throw HttpException('$detail（请重试，旧聊天记录已自动过滤）');
      }
      Map<String, dynamic>? result;
      await for (final line
          in response.transform(utf8.decoder).transform(const LineSplitter())) {
        if (line.trim().isEmpty) continue;
        final decoded = jsonDecode(line);
        if (decoded is! Map) continue;
        final event = Map<String, dynamic>.from(decoded);
        if (event['type'] == 'delta') {
          onDelta(event['text']?.toString() ?? '');
        } else if (event['type'] == 'result') {
          result = event;
        }
      }
      if (result == null) throw const FormatException('流式响应未完成');
      return result;
    } finally {
      client.close(force: true);
    }
  }

  static List<Map<String, dynamic>> _agentPreviewPaths(Object? value) {
    if (value is! List) return const [];
    return value.whereType<Map>().map(Map<String, dynamic>.from).toList();
  }

  static String? _agentJsonText(Object? value) {
    if (value is! Map) return null;
    return const JsonEncoder.withIndent('  ').convert(value);
  }

  static String? _agentJsonTextFromContent(String content) {
    final trimmed = content.trim();
    if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return null;
    try {
      return const JsonEncoder.withIndent('  ').convert(jsonDecode(trimmed));
    } catch (_) {
      return null;
    }
  }

  Future<void> _deleteSelectedProject() async {
    final project = _selectedProject;
    final id = project?['id']?.toString();
    if (id == null || _sending) return;

    final selectedProject = project!;
    final name = selectedProject['name']?.toString() ?? '未命名项目';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除项目'),
        content: Text('确定删除“$name”吗？项目本身将被删除，图纸、任务和审计记录不会受影响。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xffdc2626),
            ),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _sending = true);
    try {
      final result = await _delete('/api/agent/projects/$id');
      if (!mounted) return;
      if (result['ok'] != true) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(result['message']?.toString() ?? '项目删除失败'),
            backgroundColor: const Color(0xffdc2626),
          ),
        );
        return;
      }
      setState(() {
        _projects = _projects
            .where((item) => item['id']?.toString() != id)
            .toList();
        _selectedProjectId = _projects.isEmpty
            ? null
            : _projects.first['id']?.toString();
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('已删除项目“$name”')));
      await _loadProjects(silent: true);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('删除项目失败：$error'),
          backgroundColor: const Color(0xffdc2626),
        ),
      );
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  static List<Map<String, dynamic>> _agentPreviewPathsFromJson(String content) {
    final trimmed = content.trim();
    if (!trimmed.startsWith('{') && !trimmed.startsWith('[')) return const [];
    dynamic decoded;
    try {
      decoded = jsonDecode(trimmed);
    } catch (_) {
      return const [];
    }
    final payload = decoded is Map
        ? Map<String, dynamic>.from(decoded)
        : <String, dynamic>{'paths': decoded};
    final raw =
        payload['paths'] ??
        payload['preview_paths'] ??
        payload['shapes'] ??
        payload['lines'];
    if (raw is! List) return const [];
    final output = <Map<String, dynamic>>[];
    for (final item in raw) {
      if (item is List && item.length >= 2) {
        output.add({
          'namespace': 'chat_json',
          'route_type': 'drawing',
          'points': item,
        });
      } else if (item is Map) {
        final map = Map<String, dynamic>.from(item);
        final points = map['points'] ?? map['vertices'];
        if (points is List && points.length >= 2) {
          output.add({
            'namespace': 'chat_json',
            'route_type': 'drawing',
            'points': points,
          });
        } else if (map['start'] is List && map['end'] is List) {
          output.add({
            'namespace': 'chat_json',
            'route_type': 'drawing',
            'points': [map['start'], map['end']],
          });
        }
      }
    }
    return output;
  }

  static String _missionSummaryText(Map<String, dynamic> status) {
    final rawSummary = status['mission_summary'];
    final rawValidation = status['mission_validation'];
    final summary = rawSummary is Map
        ? Map<String, dynamic>.from(rawSummary)
        : const <String, dynamic>{};
    final validation = rawValidation is Map
        ? Map<String, dynamic>.from(rawValidation)
        : const <String, dynamic>{};
    final printingSegments =
        (summary['printing_segment_count'] as num?)?.toInt() ?? 0;
    final travelSegments =
        (summary['travel_segment_count'] as num?)?.toInt() ?? 0;
    final printingLength =
        (summary['printing_length_m'] as num?)?.toDouble() ?? 0;
    final travelLength = (summary['travel_length_m'] as num?)?.toDouble() ?? 0;
    final seconds =
        (summary['estimated_duration_seconds'] as num?)?.toInt() ?? 0;
    final printers =
        (summary['required_printers'] as List?)
            ?.map((item) => item.toString())
            .join('、') ??
        '';
    final warnings =
        (validation['warnings'] as List?)
            ?.map((item) => item.toString())
            .where((item) => item.isNotEmpty)
            .toList() ??
        const <String>[];
    final errors =
        (validation['errors'] as List?)
            ?.map((item) => item.toString())
            .where((item) => item.isNotEmpty)
            .toList() ??
        const <String>[];
    final buffer = StringBuffer(
      '任务摘要：喷墨 $printingSegments 段 / ${printingLength.toStringAsFixed(2)} m，'
      '转场 $travelSegments 段 / ${travelLength.toStringAsFixed(2)} m，'
      '预计约 $seconds 秒，喷头 ${printers.isEmpty ? '无' : printers}。',
    );
    if (warnings.isNotEmpty) buffer.write(' 提醒：${warnings.join('；')}。');
    if (errors.isNotEmpty) buffer.write(' 检查未通过：${errors.join('；')}。');
    return buffer.toString();
  }

  Future<Map<String, dynamic>> _get(String path) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    try {
      final response = await (await client.getUrl(
        Uri.parse('http://${widget.device.ip}:${widget.device.port}$path'),
      )).close().timeout(const Duration(seconds: 10));
      final decoded = jsonDecode(await utf8.decoder.bind(response).join());
      if (decoded is! Map) throw const FormatException('后端响应格式错误');
      return Map<String, dynamic>.from(decoded);
    } finally {
      client.close(force: true);
    }
  }

  Future<Map<String, dynamic>> _delete(String path) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    try {
      final response = await (await client.deleteUrl(
        Uri.parse('http://${widget.device.ip}:${widget.device.port}$path'),
      )).close().timeout(const Duration(seconds: 10));
      final raw = await response.transform(utf8.decoder).join();
      final decoded = jsonDecode(raw);
      if (decoded is! Map) throw const FormatException('后端响应格式错误');
      if (response.statusCode >= 400) {
        final detail = decoded['detail'];
        throw HttpException(
          detail is Map
              ? detail['message']?.toString() ?? detail.toString()
              : detail?.toString() ?? 'HTTP ${response.statusCode}',
        );
      }
      return Map<String, dynamic>.from(decoded);
    } finally {
      client.close(force: true);
    }
  }

  Future<void> _prepareAgentDrawing(String fileName) async {
    final accepted = await _post('/api/agent/plan-preview', {
      'file_name': fileName,
    });
    if (!mounted) return;
    setState(() {
      _messages.add(
        _AgentChatItem(
          role: 'assistant',
          content: accepted['message']?.toString() ?? '已提交规划。',
          isError: accepted['ok'] != true,
        ),
      );
    });
    _saveHistory();
    if (accepted['ok'] != true) return;

    for (var attempt = 0; attempt < 60; attempt++) {
      await Future<void>.delayed(const Duration(milliseconds: 500));
      final status = await _get('/api/status');
      if (!mounted) return;
      if (status['mission_file']?.toString() != fileName) continue;
      final stage = status['mission_stage']?.toString();
      if (stage == 'failed') {
        setState(() {
          _messages.add(
            _AgentChatItem(
              role: 'assistant',
              content: status['mission_error']?.toString() ?? '路径规划失败。',
              isError: true,
            ),
          );
        });
        _saveHistory();
        return;
      }
      if (stage != 'ready') continue;

      final execution = await _post('/api/agent/request-execution', {
        'file_name': fileName,
      });
      final pending = execution['pending_action'] is Map
          ? Map<String, dynamic>.from(execution['pending_action'] as Map)
          : null;
      final duplicateInkPaths =
          (status['mission_duplicate_ink_paths'] as num?)?.toInt() ?? 0;
      final duplicateNotice = duplicateInkPaths > 0
          ? ' 已拦截 $duplicateInkPaths 条重复喷墨路径。'
          : '';
      final summaryText = _missionSummaryText(status);
      if (!mounted) return;
      setState(() {
        _messages.add(
          _AgentChatItem(
            role: 'assistant',
            content: execution['ok'] == true
                ? '真实路径规划完成。蓝色为喷墨路径，黄色为小车转场路径。$summaryText$duplicateNotice 请检查后再确认执行。'
                : execution['message']?.toString() ?? '无法请求执行。',
            previewPaths: _agentPreviewPaths(status['planned_paths']),
            pendingAction: pending,
            isError: execution['ok'] != true,
          ),
        );
      });
      _saveHistory();
      return;
    }
    if (mounted) {
      setState(() {
        _messages.add(
          const _AgentChatItem(
            role: 'assistant',
            content: '等待路径规划结果超时，请检查 /plan_path 服务和规划器日志。',
            isError: true,
          ),
        );
      });
      _saveHistory();
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
            color: Colors.white,
            border: Border.all(color: const Color(0xffdce3ea)),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Row(
            children: [
              const Icon(Icons.smart_toy_rounded, color: Color(0xff60a5fa)),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'XLine Agent',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
                    Text(
                      _agentMode == 'advanced' ? '进阶模式' : '基础模式',
                      style: TextStyle(
                        color: Color(0xff2563eb),
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text(
                      _agentMode == 'advanced'
                          ? '引导完成设计、规划和执行，设备操作需要确认'
                          : '直接生成运动 JSON，确认后调用 ROS2 底盘工具',
                      style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
                    ),
                  ],
                ),
              ),
              DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  value: _agentMode,
                  isDense: true,
                  borderRadius: BorderRadius.circular(8),
                  items: const [
                    DropdownMenuItem(value: 'base', child: Text('基础')),
                    DropdownMenuItem(value: 'advanced', child: Text('进阶')),
                  ],
                  onChanged: _sending
                      ? null
                      : (value) {
                          if (value == null) return;
                          _switchAgentMode(value);
                        },
                ),
              ),
              const SizedBox(width: 6),
              _StatusChip(
                text: widget.bridgeConnected ? '在线' : '离线',
                color: widget.bridgeConnected
                    ? const Color(0xff22c55e)
                    : const Color(0xff64748b),
              ),
              IconButton(
                tooltip: '最近会话',
                icon: const Icon(Icons.history_rounded),
                onPressed: _historyLoaded ? _manageConversations : null,
              ),
              IconButton(
                tooltip: '新建会话',
                onPressed: _sending
                    ? null
                    : () =>
                          setState(() => _startNewConversation(notify: false)),
                icon: const Icon(Icons.add_comment_outlined),
              ),
            ],
          ),
        ),
        Expanded(
          child: ListView(
            controller: _scrollController,
            padding: const EdgeInsets.fromLTRB(14, 14, 14, 8),
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 8,
                ),
                color: _agentMode == 'advanced'
                    ? const Color(0xffeff6ff)
                    : const Color(0xfff0fdf4),
                child: Text(
                  _agentMode == 'advanced'
                      ? '进阶模式对话 · 项目与精确路径规划'
                      : '基础模式对话 · JSON 与非精确运动控制',
                  style: TextStyle(
                    color: _agentMode == 'advanced'
                        ? const Color(0xff1d4ed8)
                        : const Color(0xff166534),
                    fontWeight: FontWeight.w700,
                    fontSize: 12,
                  ),
                ),
              ),
              if (_agentMode == 'advanced') ...[
                _buildWorkGuide(),
                const SizedBox(height: 10),
                _buildProjectWorkspace(),
                if (_projects.isNotEmpty) const SizedBox(height: 12),
              ],
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
                  onCopy: () => _copyAgentMessage(message.content),
                  onQuote: () => _quoteAgentMessage(message.content),
                  onRegenerate: message.role == 'assistant'
                      ? () => _regenerateAgentMessage(message)
                      : null,
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
            color: Colors.white,
            border: Border(top: BorderSide(color: Color(0xffe2e8f0))),
          ),
          child: SafeArea(
            top: false,
            child: Column(
              children: [
                ValueListenableBuilder<int>(
                  valueListenable: widget.agentMotionNotifier,
                  builder: (context, remainingMs, _) {
                    if (remainingMs < 0) return const SizedBox.shrink();
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: FilledButton.icon(
                        style: FilledButton.styleFrom(
                          backgroundColor: const Color(0xffdc2626),
                          foregroundColor: Colors.white,
                          minimumSize: const Size.fromHeight(50),
                        ),
                        onPressed: widget.onStopAgentMotion,
                        icon: const Icon(Icons.stop_circle_rounded),
                        label: Text(
                          '停止 AI 控制小车运动'
                          '${remainingMs > 0 ? ' · ${(remainingMs / 1000).ceil()} 秒' : ''}',
                        ),
                      ),
                    );
                  },
                ),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _controller,
                        enabled: !_sending && _historyLoaded,
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
                      onPressed: _sending || !_historyLoaded ? null : _send,
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

  Widget _buildWorkGuide() {
    final project = _selectedProject;
    final status = project?['status']?.toString();
    final step = _projectStep(status);
    final missing = project?['missing_parameters'] is List
        ? (project!['missing_parameters'] as List)
              .map((item) => item.toString())
              .where((item) => item.trim().isNotEmpty)
              .toList()
        : const <String>[];
    final title = switch (status) {
      null => '从需求开始',
      'clarifying' || 'ready_for_design' => '确认设计参数',
      'designing' => '选择候选方案',
      'ready_for_planning' || 'planning' => '等待真实规划',
      'planning_ready' || 'pending_execution' => '执行前确认',
      'executing' => '执行中',
      'paused' || 'execution_failed' => '任务需要恢复',
      'completed' => '任务已完成',
      'cancelled' => '任务已取消',
      _ => '检查当前任务',
    };
    final message = switch (status) {
      null => '描述图形、尺寸、是否喷墨和定位方式，AI 会逐项补齐参数。',
      'clarifying' || 'ready_for_design' => '先补齐缺失参数，再生成候选方案。当前不会控制小车。',
      'designing' => '比较方案尺寸和可制造性，选择后进入真实路径规划。',
      'ready_for_planning' || 'planning' => '规划器生成喷墨路径和转场路径后，再检查路线。',
      'planning_ready' || 'pending_execution' => '检查路线、定位、急停和周围环境，确认后才会发送运动指令。',
      'executing' => '正在按分段检查点执行，可随时停止 AI 控制。',
      'paused' || 'execution_failed' => '先查看失败原因，再重新规划并确认；不会自动恢复运动。',
      'completed' => '可查看实际轨迹、偏差和验收报告。',
      'cancelled' => '可以重新描述需求，创建新的设计任务。',
      _ => '查看项目状态和后端返回的下一步操作。',
    };
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      decoration: BoxDecoration(
        color: const Color(0xffeff6ff),
        border: Border.all(color: const Color(0xffbfdbfe)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.assistant_navigation, color: Color(0xff2563eb)),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '项目进度 · ${_projectStepLabel(step)}',
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      title == '从需求开始' ? '当前还没有项目。$message' : message,
                      style: const TextStyle(fontSize: 12, height: 1.35),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _buildProjectStepBar(step),
          if (missing.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              '还缺少：${missing.join('、')}',
              style: const TextStyle(
                fontSize: 12,
                color: Color(0xffb45309),
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
          const SizedBox(height: 8),
          Text(
            '下一步：${_projectNextStep(status, missing)}',
            style: const TextStyle(fontSize: 12, color: Color(0xff334155)),
          ),
        ],
      ),
    );
  }

  static int _projectStep(String? status) {
    return switch (status) {
      'designing' || 'ready_for_planning' => 1,
      'planning' || 'planning_ready' || 'planning_failed' => 2,
      'pending_execution' ||
      'executing' ||
      'paused' ||
      'execution_failed' => 3,
      'completed' || 'cancelled' => 4,
      _ => 0,
    };
  }

  static String _projectStepLabel(int step) => const [
        '需求',
        '设计',
        '规划',
        '执行',
        '验收',
      ][step.clamp(0, 4).toInt()];

  Widget _buildProjectStepBar(int currentStep) {
    const labels = ['需求', '设计', '规划', '执行', '验收'];
    return Row(
      children: [
        for (var index = 0; index < labels.length; index++) ...[
          Expanded(
            child: Column(
              children: [
                Container(
                  width: 24,
                  height: 24,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: index <= currentStep
                        ? const Color(0xff2563eb)
                        : const Color(0xffdbeafe),
                  ),
                  child: index < currentStep
                      ? const Icon(Icons.check, size: 15, color: Colors.white)
                      : Text(
                          '${index + 1}',
                          style: TextStyle(
                            fontSize: 11,
                            color: index == currentStep
                                ? Colors.white
                                : const Color(0xff2563eb),
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                ),
                const SizedBox(height: 3),
                Text(
                  labels[index],
                  style: TextStyle(
                    fontSize: 10,
                    color: index <= currentStep
                        ? const Color(0xff1e40af)
                        : const Color(0xff64748b),
                    fontWeight: index == currentStep
                        ? FontWeight.w700
                        : FontWeight.w400,
                  ),
                ),
              ],
            ),
          ),
          if (index < labels.length - 1)
            Expanded(
              child: Container(
                height: 2,
                margin: const EdgeInsets.only(bottom: 18),
                color: index < currentStep
                    ? const Color(0xff2563eb)
                    : const Color(0xffdbeafe),
              ),
            ),
        ],
      ],
    );
  }

  static String _projectNextStep(String? status, List<String> missing) {
    if (status == null) return '在下方描述要绘制的内容，AI 会创建项目并提取参数。';
    if (missing.isNotEmpty) return '补充缺失参数后，AI 才会生成候选设计。';
    return switch (status) {
      'clarifying' || 'ready_for_design' => '确认需求参数并生成候选方案。',
      'designing' => '比较候选方案并选择一个设计。',
      'ready_for_planning' => '提交规划预览，检查喷墨路径和转场路径。',
      'planning' => '等待 ROS2 规划完成，再刷新项目状态。',
      'planning_ready' => '检查规划质量、定位和安全条件，然后请求执行。',
      'planning_failed' => '查看规划错误，修改图纸或重新规划。',
      'pending_execution' => '确认执行操作后才会控制小车。',
      'executing' => '观察分段执行和验证结果，必要时停止任务。',
      'paused' || 'execution_failed' => '查看异常并进行人工检查，再重新规划恢复。',
      'completed' => '查看实际轨迹对比和验收报告。',
      'cancelled' => '重新描述需求或创建新的设计项目。',
      _ => '查看项目状态并按照后端返回的操作继续。',
    };
  }

  Widget _buildProjectWorkspace() {
    if (!widget.bridgeConnected) return const SizedBox.shrink();
    final project = _selectedProject;
    if (_projectsLoading && project == null) {
      return const LinearProgressIndicator(minHeight: 2);
    }
    if (project == null) {
      return Row(
        children: [
          const Expanded(child: Text('还没有设计项目，可在下方描述要绘制的内容。')),
          IconButton(
            tooltip: '刷新项目',
            onPressed: _loadProjects,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      );
    }
    final status = project['status']?.toString() ?? 'unknown';
    final execution = project['execution'] is Map
        ? Map<String, dynamic>.from(project['execution'] as Map)
        : const <String, dynamic>{};
    final planning = project['planning'] is Map
        ? Map<String, dynamic>.from(project['planning'] as Map)
        : const <String, dynamic>{};
    final recovery = planning['recovery'] is Map
        ? Map<String, dynamic>.from(planning['recovery'] as Map)
        : const <String, dynamic>{};
    final drawingVersion = planning['drawing_version'] is Map
        ? Map<String, dynamic>.from(planning['drawing_version'] as Map)
        : const <String, dynamic>{};
    final progress = ((execution['progress'] as num?)?.toDouble() ?? 0).clamp(
      0.0,
      1.0,
    );
    final variants = project['variants'] as List? ?? const [];
    final selectedVariantId = project['selected_variant_id']?.toString();
    Map<String, dynamic>? selectedVariant;
    for (final item in variants.whereType<Map>()) {
      if (item['id']?.toString() == selectedVariantId) {
        selectedVariant = Map<String, dynamic>.from(item);
        break;
      }
    }
    final previewPaths = _variantPreviewPaths(
      selectedVariant?['preview_paths'],
    );
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: const Color(0xffcbd5e1)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.account_tree_outlined, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    value: project['id']?.toString(),
                    isExpanded: true,
                    items: _projects
                        .map(
                          (item) => DropdownMenuItem<String>(
                            value: item['id']?.toString(),
                            child: Text(
                              item['name']?.toString() ?? '未命名项目',
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        )
                        .toList(),
                    onChanged: _sending
                        ? null
                        : (value) => setState(() => _selectedProjectId = value),
                  ),
                ),
              ),
              _StatusChip(
                text: _projectStatusText(status),
                color: _projectStatusColor(status),
              ),
              IconButton(
                tooltip: '刷新项目',
                onPressed: _projectsLoading ? null : _loadProjects,
                icon: const Icon(Icons.refresh_rounded),
              ),
              IconButton(
                tooltip: '删除项目',
                onPressed: _sending ? null : _deleteSelectedProject,
                icon: const Icon(Icons.delete_outline_rounded),
                color: const Color(0xffdc2626),
              ),
            ],
          ),
          if (previewPaths.isNotEmpty) ...[
            const SizedBox(height: 8),
            SizedBox(
              height: 150,
              width: double.infinity,
              child: CustomPaint(
                painter: _MapPainter(
                  lineRunning: false,
                  gridMap: const {},
                  plannedPaths: previewPaths,
                  robotPose: const {},
                  poseTrace: const [],
                  showPlan: false,
                  showTrace: false,
                  showRobot: false,
                ),
              ),
            ),
          ],
          if (variants.length > 1) ...[
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              initialValue: selectedVariantId,
              decoration: const InputDecoration(
                labelText: '候选方案',
                border: OutlineInputBorder(),
                isDense: true,
              ),
              items: variants.whereType<Map>().map((item) {
                final assessment = item['assessment'] is Map
                    ? Map<String, dynamic>.from(item['assessment'] as Map)
                    : const <String, dynamic>{};
                return DropdownMenuItem<String>(
                  value: item['id']?.toString(),
                  child: Text(
                    '${item['name'] ?? '未命名'} · ${assessment['score'] ?? '-'}分',
                    overflow: TextOverflow.ellipsis,
                  ),
                );
              }).toList(),
              onChanged:
                  _sending ||
                      !{'designing', 'ready_for_planning'}.contains(status)
                  ? null
                  : (value) {
                      if (value != null) {
                        unawaited(_selectProjectVariant(value));
                      }
                    },
            ),
          ],
          if (status == 'executing' || status == 'paused') ...[
            const SizedBox(height: 8),
            LinearProgressIndicator(value: progress),
            const SizedBox(height: 4),
            Text(
              '已完成 ${execution['completed_segments'] ?? 0}/${execution['total_segments'] ?? 0} 段'
              '${execution['last_verified_segment_id'] == null ? '' : ' · 已验证 ${execution['last_verified_segment_id']}'}',
              style: const TextStyle(fontSize: 12, color: Color(0xff64748b)),
            ),
          ],
          if (drawingVersion.isNotEmpty) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: _sending
                  ? null
                  : () => _showProjectDrawingVersions(
                      drawingVersion,
                      project['id'].toString(),
                      status,
                    ),
              icon: const Icon(Icons.history_rounded, size: 18),
              label: Text('图纸版本 V${drawingVersion['version'] ?? '-'}'),
            ),
          ],
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: _projectActions(status, recovery),
          ),
        ],
      ),
    );
  }

  List<Widget> _projectActions(String status, Map<String, dynamic> recovery) {
    final actions = <Widget>[];
    void add(
      String label,
      IconData icon,
      String action, {
      String method = 'post',
    }) {
      actions.add(
        FilledButton.tonalIcon(
          onPressed: _sending
              ? null
              : () => _runProjectAction(action, method: method),
          icon: Icon(icon, size: 18),
          label: Text(label),
        ),
      );
    }

    if (status == 'ready_for_planning' || status == 'planning_failed') {
      add('规划预览', Icons.route_outlined, 'plan');
    }
    if (status == 'planning') {
      add('刷新规划', Icons.refresh_rounded, 'plan', method: 'get');
    }
    if (status == 'planning_ready') {
      if (recovery['manual_inspection_required'] == true &&
          recovery['manual_inspection_confirmed'] != true) {
        actions.add(
          OutlinedButton.icon(
            onPressed: _sending
                ? null
                : () => _runProjectAction(
                    'recovery-inspection',
                    body: const {'confirmed': true},
                  ),
            icon: const Icon(Icons.fact_check_outlined, size: 18),
            label: const Text('已检查部分喷墨段'),
          ),
        );
      } else {
        add('请求执行', Icons.play_arrow_rounded, 'request-execution');
      }
    }
    if ({
      'pending_execution',
      'executing',
      'paused',
      'execution_failed',
    }.contains(status)) {
      add('刷新执行', Icons.sync_rounded, 'execution', method: 'get');
    }
    if ({'paused', 'execution_failed', 'cancelled'}.contains(status)) {
      add('恢复评估', Icons.health_and_safety_outlined, 'recovery', method: 'get');
      add('重新规划', Icons.restart_alt_rounded, 'recovery');
    }
    if ({'completed', 'execution_failed', 'cancelled'}.contains(status)) {
      add('验收报告', Icons.assignment_turned_in_outlined, 'report');
    }
    return actions;
  }

  static List<Map<String, dynamic>> _variantPreviewPaths(Object? value) {
    if (value is! List) return const [];
    return [
      for (final points in value.whereType<List>())
        {
          'namespace': 'creative_variant',
          'route_type': 'drawing',
          'points': points,
        },
    ];
  }

  static String _projectStatusText(String status) =>
      const {
        'clarifying': '待补参数',
        'ready_for_design': '待设计',
        'designing': '设计中',
        'ready_for_planning': '待规划',
        'planning': '规划中',
        'planning_ready': '可确认',
        'planning_failed': '规划失败',
        'pending_execution': '待确认',
        'executing': '执行中',
        'paused': '已暂停',
        'execution_failed': '执行失败',
        'completed': '已完成',
        'cancelled': '已取消',
      }[status] ??
      status;

  static Color _projectStatusColor(String status) {
    if (status == 'completed' || status == 'planning_ready') {
      return const Color(0xff16a34a);
    }
    if (status.contains('failed')) return const Color(0xffdc2626);
    if (status == 'executing' || status == 'planning') {
      return const Color(0xff2563eb);
    }
    if (status == 'paused' || status == 'pending_execution') {
      return const Color(0xffd97706);
    }
    return const Color(0xff64748b);
  }
}

class _AgentChatItem {
  const _AgentChatItem({
    required this.role,
    required this.content,
    this.pendingAction,
    this.previewPaths = const [],
    this.jsonText,
    this.isError = false,
  });

  final String role;
  final String content;
  final Map<String, dynamic>? pendingAction;
  final List<Map<String, dynamic>> previewPaths;
  final String? jsonText;
  final bool isError;

  _AgentChatItem copyWith({
    String? content,
    Map<String, dynamic>? pendingAction,
  }) {
    return _AgentChatItem(
      role: role,
      content: content ?? this.content,
      pendingAction: pendingAction,
      previewPaths: previewPaths,
      jsonText: jsonText,
      isError: isError,
    );
  }

  static String _redactSecrets(String value) => value
      .replaceAll(
        RegExp(r'\bsk-[A-Za-z0-9_-]{12,}\b', caseSensitive: false),
        '[已隐藏密钥]',
      )
      .replaceAll(
        RegExp(
          r'((?:api[_ -]?key|token|password)\s*[:=]\s*)\S+',
          caseSensitive: false,
        ),
        r'$1[已隐藏密钥]',
      );

  Map<String, dynamic> toJson() => {
    'role': role,
    'content': _redactSecrets(content),
    'preview_paths': previewPaths,
    'json_text': jsonText == null ? null : _redactSecrets(jsonText!),
    'is_error': isError,
  };

  factory _AgentChatItem.fromJson(Map<String, dynamic> json) => _AgentChatItem(
    role: json['role']?.toString() ?? 'assistant',
    content: json['content']?.toString() ?? '',
    previewPaths: _AgentPageState._agentPreviewPaths(json['preview_paths']),
    jsonText: json['json_text']?.toString(),
    isError: json['is_error'] == true,
  );
}

class _AgentConversation {
  const _AgentConversation({
    required this.id,
    required this.deviceKey,
    this.mode = 'base',
    required this.title,
    required this.createdAt,
    required this.updatedAt,
    required this.messages,
    this.inputTokens = 0,
    this.outputTokens = 0,
  });

  final String id;
  final String deviceKey;
  final String mode;
  final String title;
  final DateTime createdAt;
  final DateTime updatedAt;
  final List<_AgentChatItem> messages;
  final int inputTokens;
  final int outputTokens;

  _AgentConversation copyWith({
    String? title,
    DateTime? updatedAt,
    List<_AgentChatItem>? messages,
    int? inputTokens,
    int? outputTokens,
  }) => _AgentConversation(
    id: id,
    deviceKey: deviceKey,
    mode: mode,
    title: title ?? this.title,
    createdAt: createdAt,
    updatedAt: updatedAt ?? this.updatedAt,
    messages: messages ?? this.messages,
    inputTokens: inputTokens ?? this.inputTokens,
    outputTokens: outputTokens ?? this.outputTokens,
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'device_key': deviceKey,
    'mode': mode,
    'title': title,
    'created_at': createdAt.toIso8601String(),
    'updated_at': updatedAt.toIso8601String(),
    'messages': messages.map((item) => item.toJson()).toList(),
    'input_tokens': inputTokens,
    'output_tokens': outputTokens,
  };

  factory _AgentConversation.fromJson(Map<String, dynamic> json) {
    final now = DateTime.now();
    final rawMessages = json['messages'] as List? ?? const [];
    final messages = rawMessages
        .whereType<Map>()
        .map((item) => _AgentChatItem.fromJson(Map<String, dynamic>.from(item)))
        .toList();
    final retainedMessages = messages.length <= _AgentPageState._maxMessages
        ? messages
        : messages.sublist(messages.length - _AgentPageState._maxMessages);
    return _AgentConversation(
      id: json['id']?.toString() ?? now.microsecondsSinceEpoch.toString(),
      deviceKey: json['device_key']?.toString() ?? '',
      mode: json['mode']?.toString() == 'work'
          ? 'advanced'
          : (json['mode']?.toString() == 'chat'
                ? 'base'
                : json['mode']?.toString() ?? 'base'),
      title: json['title']?.toString() ?? '历史会话',
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? '') ?? now,
      updatedAt: DateTime.tryParse(json['updated_at']?.toString() ?? '') ?? now,
      messages: retainedMessages,
      inputTokens: (json['input_tokens'] as num?)?.toInt() ?? 0,
      outputTokens: (json['output_tokens'] as num?)?.toInt() ?? 0,
    );
  }
}

class _AgentBubble extends StatelessWidget {
  const _AgentBubble({
    required this.item,
    this.onCopy,
    this.onQuote,
    this.onRegenerate,
    this.onConfirm,
  });

  final _AgentChatItem item;
  final VoidCallback? onCopy;
  final VoidCallback? onQuote;
  final VoidCallback? onRegenerate;
  final ValueChanged<bool>? onConfirm;

  @override
  Widget build(BuildContext context) {
    final user = item.role == 'user';
    final displayContent = user
        ? item.content
        : _friendlyAgentContent(item.content);
    final color = item.isError
        ? const Color(0xfffff1f2)
        : user
        ? const Color(0xff16a66a)
        : const Color(0xfff1f5f9);
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
            SelectableText(displayContent, style: const TextStyle(height: 1.45)),
            const SizedBox(height: 4),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  tooltip: '复制',
                  visualDensity: VisualDensity.compact,
                  padding: EdgeInsets.zero,
                  onPressed: onCopy,
                  icon: const Icon(Icons.copy_all_outlined, size: 17),
                ),
                IconButton(
                  tooltip: '引用',
                  visualDensity: VisualDensity.compact,
                  padding: EdgeInsets.zero,
                  onPressed: onQuote,
                  icon: const Icon(Icons.format_quote_rounded, size: 18),
                ),
                if (onRegenerate != null)
                  IconButton(
                    tooltip: '重新生成',
                    visualDensity: VisualDensity.compact,
                    padding: EdgeInsets.zero,
                    onPressed: onRegenerate,
                    icon: const Icon(Icons.refresh_rounded, size: 18),
                  ),
              ],
            ),
            if (item.jsonText != null) ...[
              const SizedBox(height: 8),
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                childrenPadding: EdgeInsets.zero,
                dense: true,
                title: const Text('查看 JSON', style: TextStyle(fontSize: 12)),
                children: [
                  Container(
                    width: double.infinity,
                    constraints: const BoxConstraints(maxHeight: 240),
                    padding: const EdgeInsets.all(8),
                    color: const Color(0xff0f172a),
                    child: SingleChildScrollView(
                      child: SelectableText(
                        item.jsonText!,
                        style: const TextStyle(
                          color: Color(0xffe2e8f0),
                          fontFamily: 'monospace',
                          fontSize: 11,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ],
            if (item.previewPaths.isNotEmpty) ...[
              const SizedBox(height: 10),
              Container(
                width: double.infinity,
                height: 220,
                clipBehavior: Clip.antiAlias,
                decoration: BoxDecoration(
                  color: const Color(0xfff8fafc),
                  border: Border.all(color: const Color(0xffcbd5e1)),
                  borderRadius: BorderRadius.circular(7),
                ),
                child: CustomPaint(
                  painter: _MapPainter(
                    lineRunning: false,
                    gridMap: const {},
                    plannedPaths: item.previewPaths,
                    robotPose: const {},
                    poseTrace: const [],
                    showPlan: false,
                    showTrace: false,
                    showRobot: false,
                  ),
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                'AI JSON 草稿预览 · 保存图纸不等于执行任务',
                style: TextStyle(color: Color(0xff64748b), fontSize: 11),
              ),
            ],
            if (!user &&
                item.pendingAction != null &&
                (item.pendingAction!['name']?.toString() == 'drive_robot' ||
                    item.pendingAction!['name']?.toString() ==
                        'drive_sequence')) ...[
              const SizedBox(height: 6),
              const Text(
                '这是有限时移动演示，不保证精确距离、角度或闭合图形。需要精确路线时请切换到进阶模式。',
                style: TextStyle(color: Color(0xffb45309), fontSize: 11),
              ),
            ],
            if (item.pendingAction != null) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Colors.white,
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

String _friendlyAgentContent(String content) {
  final trimmed = content.trim();
  if (trimmed.isEmpty || !trimmed.startsWith('{')) return content;
  try {
    final decoded = jsonDecode(trimmed);
    if (decoded is! Map) return content;
    final data = Map<String, dynamic>.from(decoded);
    final ok = data['ok'] == true;
    final shape = data['shape']?.toString();
    final dimensions = data['dimensions'] is Map
        ? Map<String, dynamic>.from(data['dimensions'] as Map)
        : const <String, dynamic>{};
    final missing = (data['missing'] is List)
        ? (data['missing'] as List).map((item) => item.toString()).toList()
        : const <String>[];
    final capabilities =
        data['vehicle'] is Map &&
            (data['vehicle'] as Map)['capabilities'] is Map
        ? Map<String, dynamic>.from(
            ((data['vehicle'] as Map)['capabilities'] as Map),
          )
        : const <String, dynamic>{};
    final runtime =
        data['vehicle'] is Map && (data['vehicle'] as Map)['runtime'] is Map
        ? Map<String, dynamic>.from(
            ((data['vehicle'] as Map)['runtime'] as Map),
          )
        : const <String, dynamic>{};
    final safety =
        data['vehicle'] is Map && (data['vehicle'] as Map)['safety'] is Map
        ? Map<String, dynamic>.from(((data['vehicle'] as Map)['safety'] as Map))
        : const <String, dynamic>{};
    final inferredMissing = <String>[];
    if (data['shape'] == null &&
        data['paths'] == null &&
        data['lines'] == null) {
      inferredMissing.add('drawing');
    }
    if (runtime['control_ready'] == false || data['control_ready'] == false) {
      inferredMissing.add('control_ready');
    }
    if (safety['emergency_stopped'] == true ||
        data['emergency_stopped'] == true) {
      inferredMissing.add('emergency_stop');
    }
    if (data['localization_valid'] == false ||
        data['localization'] is Map &&
            (data['localization'] as Map)['valid'] == false) {
      inferredMissing.add('localization');
    }
    if (capabilities['path_planning'] == false)
      inferredMissing.add('path_planning');
    final allMissing = {...missing, ...inferredMissing}.toList();
    final lines = <String>[];

    if (shape != null && shape.isNotEmpty) {
      final shapeName =
          const {
            'circle': '圆形',
            'rectangle': '矩形',
            'line': '直线',
            'polyline': '折线',
          }[shape] ??
          shape;
      final size = <String>[];
      if (dimensions['radius_m'] != null) {
        size.add('半径 ${dimensions['radius_m']} 米');
      }
      if (dimensions['width_m'] != null) {
        size.add('宽 ${dimensions['width_m']} 米');
      }
      if (dimensions['height_m'] != null) {
        size.add('高 ${dimensions['height_m']} 米');
      }
      lines.add('已生成$shapeName${size.isEmpty ? '' : '（${size.join('，')}）'}。');
    }

    final origin = data['origin']?.toString();
    if (origin != null && origin.isNotEmpty) {
      lines.add('起点：${origin == 'current_robot_pose' ? '小车当前位置' : origin}。');
    }

    if (ok) {
      lines.add('设计结果已准备好，可以查看预览或继续规划。');
    } else {
      lines.add('当前还不能生成完整可执行任务。');
      if (allMissing.isNotEmpty) {
        final missingNames = allMissing
            .map(
              (item) =>
                  const {
                    'printer': '喷码机',
                    'localization': '定位',
                    'drawing': '图纸',
                    'vehicle': '小车连接',
                    'control_ready': '控制就绪',
                    'emergency_stop': '解除急停',
                    'path_planning': '路径规划能力',
                  }[item] ??
                  item,
            )
            .join('、');
        lines.add('当前缺少或未满足：$missingNames。');
        if (allMissing.contains('emergency_stop')) {
          lines.add('请先解除硬件急停，并确认车轮架空或现场环境安全。');
        } else if (allMissing.contains('control_ready')) {
          lines.add('请检查 CAN、电机节点、控制权和安全门禁状态。');
        } else if (allMissing.contains('printer')) {
          lines.add('请先配置喷码机，或选择“只生成小车行驶路径”。');
        } else if (allMissing.contains('drawing')) {
          lines.add('请先提供图形和尺寸，或让 AI 生成一份设计 JSON。');
        } else {
          lines.add('请补齐上述条件后再继续。');
        }
      } else {
        lines.add('请检查任务参数后重试。');
      }
    }
    return lines.join('\n');
  } catch (_) {
    return content;
  }
}
