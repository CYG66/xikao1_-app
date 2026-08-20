part of '../main.dart';

class _SettingsPage extends StatelessWidget {
  const _SettingsPage({
    required this.device,
    required this.localizationSource,
    required this.onAddDevice,
    required this.bridgeState,
    required this.printerEnabled,
    required this.printerStatus,
    required this.onPrinterChanged,
    required this.onPrinterEnabledChanged,
    required this.onPrinterCommand,
    required this.onPrinterRawCommand,
  });

  final RoverDevice device;
  final String localizationSource;
  final VoidCallback onAddDevice;
  final BridgeState bridgeState;
  final bool printerEnabled;
  final Map<String, dynamic> printerStatus;
  final void Function(String printerName, bool active) onPrinterChanged;
  final void Function(String printerName, bool enabled) onPrinterEnabledChanged;
  final void Function(String printerName, String action) onPrinterCommand;
  final void Function(String printerName, String jsonData) onPrinterRawCommand;

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
          title: 'ROS2 接口',
          child: Column(
            children: [
              _ConfigRow('定位来源', _localizationLabel),
              _ConfigRow('手动控制', '/tablet_cmd_vel'),
              _ConfigRow('路径规划', '/plan_path'),
              _ConfigRow('任务执行', '/execute_plan'),
            ],
          ),
        ),
        const SizedBox(height: 14),
        _PrinterControlPanel(
          enabled: printerEnabled,
          status: printerStatus,
          onPrinterChanged: onPrinterChanged,
          onPrinterEnabledChanged: onPrinterEnabledChanged,
          onPrinterCommand: onPrinterCommand,
          onPrinterRawCommand: onPrinterRawCommand,
        ),
        const SizedBox(height: 14),
        _AiSettingsPanel(
          device: device,
          bridgeConnected: bridgeState == BridgeState.connected,
        ),
      ],
    );
  }

  String get _localizationLabel {
    switch (localizationSource) {
      case 'ln150_imu':
        return 'LN150 + IMU';
      case 'odom_imu_relative':
        return '轮速里程计 + IMU（相对定位）';
      default:
        return '未就绪';
    }
  }
}

class _AiSettingsPanel extends StatefulWidget {
  const _AiSettingsPanel({required this.device, required this.bridgeConnected});

  final RoverDevice device;
  final bool bridgeConnected;

  @override
  State<_AiSettingsPanel> createState() => _AiSettingsPanelState();
}

class _AiSettingsPanelState extends State<_AiSettingsPanel> {
  static const Map<String, String> providerLabels = {
    'openai': 'OpenAI',
    'anthropic': 'Claude（Anthropic）',
    'gemini': 'Gemini（Google）',
    'deepseek': 'DeepSeek',
    'qwen': '通义千问（Qwen）',
    'kimi': 'Kimi（月之暗面）',
    'glm': '智谱 GLM',
    'minimax': 'MiniMax',
    'local': '本地诊断助手（零 Token）',
  };

  static const Map<String, List<String>> modelsByProvider = {
    'openai': ['gpt-5.1', 'gpt-5-mini', 'gpt-5-nano', 'gpt-4.1'],
    'anthropic': ['claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5'],
    'gemini': [
      'gemini-3.6-flash',
      'gemini-3.5-flash',
      'gemini-3.1-pro-preview',
      'gemini-2.5-pro',
    ],
    'deepseek': ['deepseek-chat', 'deepseek-reasoner', 'deepseek-v4-pro'],
    'qwen': ['qwen3.7-max', 'qwen3.7-plus', 'qwen3.6-flash'],
    'kimi': ['kimi-k2.5', 'kimi-k2-thinking', 'moonshot-v1-auto'],
    'glm': ['glm-5', 'glm-4.7', 'glm-4.5-air'],
    'minimax': ['MiniMax-M2.7', 'MiniMax-M2.7-highspeed', 'MiniMax-M2.5'],
    'local': ['xline-local-diagnostics'],
  };

  final TextEditingController apiKeyController = TextEditingController();
  String mode = 'deepseek';
  String model = 'deepseek-chat';
  bool apiKeyConfigured = false;
  Set<String> configuredProviders = {};
  bool showApiKey = false;
  bool loading = false;
  String message = '连接小车后读取 AI 配置';

  @override
  void initState() {
    super.initState();
    if (widget.bridgeConnected) unawaited(_load());
  }

  @override
  void didUpdateWidget(covariant _AiSettingsPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!oldWidget.bridgeConnected && widget.bridgeConnected) {
      unawaited(_load());
    }
  }

  @override
  void dispose() {
    apiKeyController.dispose();
    super.dispose();
  }

  Future<Map<String, dynamic>> _request(String method, {Object? body}) async {
    final client = HttpClient()..connectionTimeout = const Duration(seconds: 4);
    try {
      final uri = Uri.parse(
        'http://${widget.device.ip}:${widget.device.port}/api/agent/config',
      );
      final request = method == 'GET'
          ? await client.getUrl(uri)
          : await client.postUrl(uri);
      request.headers.contentType = ContentType.json;
      if (body != null) request.write(jsonEncode(body));
      final response = await request.close().timeout(
        const Duration(seconds: 6),
      );
      final text = await utf8.decoder.bind(response).join();
      final decoded = jsonDecode(text);
      if (response.statusCode != 200 || decoded is! Map) {
        throw const FormatException('AI 配置响应无效');
      }
      return Map<String, dynamic>.from(decoded);
    } finally {
      client.close(force: true);
    }
  }

  Future<void> _load() async {
    setState(() => loading = true);
    try {
      final result = await _request('GET');
      if (!mounted) return;
      setState(() {
        final loadedMode = result['mode']?.toString() ?? 'deepseek';
        mode = modelsByProvider.containsKey(loadedMode)
            ? loadedMode
            : 'deepseek';
        final loadedModel = result['model']?.toString();
        model = modelsByProvider[mode]!.contains(loadedModel)
            ? loadedModel!
            : modelsByProvider[mode]!.first;
        apiKeyConfigured = result['api_key_configured'] == true;
        configuredProviders =
            ((result['configured_providers'] as List?) ?? const [])
                .map((item) => item.toString())
                .toSet();
        message = '配置已同步';
      });
    } catch (_) {
      if (mounted) setState(() => message = '无法读取后端 AI 配置');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _save() async {
    if (!widget.bridgeConnected) {
      setState(() => message = '请先连接小车');
      return;
    }
    setState(() {
      loading = true;
      message = '正在保存...';
    });
    try {
      final result = await _request(
        'POST',
        body: {
          'mode': mode,
          'model': model,
          if (apiKeyController.text.trim().isNotEmpty)
            'api_key': apiKeyController.text.trim(),
          'clear_api_key': false,
        },
      );
      if (!mounted) return;
      setState(() {
        apiKeyConfigured = result['api_key_configured'] == true;
        configuredProviders =
            ((result['configured_providers'] as List?) ?? const [])
                .map((item) => item.toString())
                .toSet();
        apiKeyController.clear();
        message = 'AI 配置已保存';
      });
    } catch (_) {
      if (mounted) setState(() => message = '保存失败，请检查后端连接');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _clearApiKey() async {
    if (!widget.bridgeConnected) {
      setState(() => message = '请先连接小车');
      return;
    }
    setState(() => loading = true);
    try {
      final result = await _request(
        'POST',
        body: {'mode': mode, 'model': model, 'clear_api_key': true},
      );
      if (!mounted) return;
      setState(() {
        apiKeyConfigured = result['api_key_configured'] == true;
        configuredProviders =
            ((result['configured_providers'] as List?) ?? const [])
                .map((item) => item.toString())
                .toSet();
        apiKeyController.clear();
        message = 'API Key 已清除';
      });
    } catch (_) {
      if (mounted) setState(() => message = '清除失败，请检查后端连接');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _testConnection() async {
    if (!widget.bridgeConnected) {
      setState(() => message = '请先连接小车');
      return;
    }
    setState(() {
      loading = true;
      message = '正在测试 AI 服务...';
    });
    try {
      final client = HttpClient()
        ..connectionTimeout = const Duration(seconds: 4);
      final request = await client.postUrl(
        Uri.parse(
          'http://${widget.device.ip}:${widget.device.port}/api/agent/test',
        ),
      );
      request.headers.contentType = ContentType.json;
      final response = await request.close().timeout(
        const Duration(seconds: 18),
      );
      final result = jsonDecode(await utf8.decoder.bind(response).join());
      client.close(force: true);
      if (!mounted) return;
      setState(
        () => message = result is Map
            ? result['message']?.toString() ?? '测试完成'
            : 'AI 服务响应无效',
      );
    } catch (_) {
      if (mounted) setState(() => message = '测试失败，请检查网络和后端');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cloudProvider = mode != 'local';
    final serviceReady = !cloudProvider || apiKeyConfigured;
    final availableModels = modelsByProvider[mode]!;
    return _Panel(
      title: 'AI 服务',
      trailing: _StatusChip(
        text: serviceReady ? '可用' : '缺少 API Key',
        color: serviceReady ? const Color(0xff22c55e) : const Color(0xfff59e0b),
      ),
      child: Column(
        children: [
          DropdownButtonFormField<String>(
            key: ValueKey('agent-mode-$mode'),
            initialValue: mode,
            decoration: _inputDecoration('AI 类型', Icons.psychology_rounded),
            items: providerLabels.entries
                .map(
                  (entry) => DropdownMenuItem(
                    value: entry.key,
                    child: Text(
                      configuredProviders.contains(entry.key)
                          ? '${entry.value}  ·  已配置'
                          : entry.value,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                )
                .toList(),
            onChanged: loading
                ? null
                : (value) => setState(() {
                    mode = value ?? mode;
                    model = modelsByProvider[mode]!.first;
                    apiKeyConfigured = configuredProviders.contains(mode);
                    apiKeyController.clear();
                    message = mode == 'local' ? '本地模式无需密钥' : '请选择模型并保存配置';
                  }),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            key: ValueKey('agent-model-$model-$mode'),
            initialValue: availableModels.contains(model)
                ? model
                : availableModels.first,
            decoration: _inputDecoration('模型', Icons.memory_rounded),
            items: availableModels
                .map((item) => DropdownMenuItem(value: item, child: Text(item)))
                .toList(),
            onChanged: !loading
                ? (value) => setState(() => model = value ?? model)
                : null,
          ),
          const SizedBox(height: 10),
          if (cloudProvider) ...[
            TextField(
              controller: apiKeyController,
              obscureText: !showApiKey,
              enableSuggestions: false,
              autocorrect: false,
              decoration:
                  _inputDecoration(
                    apiKeyConfigured ? 'API Key（已配置，留空则保持）' : 'API Key',
                    Icons.key_rounded,
                  ).copyWith(
                    suffixIcon: IconButton(
                      tooltip: showApiKey ? '隐藏 API Key' : '显示 API Key',
                      onPressed: () => setState(() => showApiKey = !showApiKey),
                      icon: Icon(
                        showApiKey ? Icons.visibility_off : Icons.visibility,
                      ),
                    ),
                  ),
            ),
            const SizedBox(height: 8),
            _ConfigRow('密钥状态', apiKeyConfigured ? '已安全保存在小车' : '未配置'),
          ],
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              message,
              style: const TextStyle(color: Color(0xff94a3b8)),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: loading ? null : _testConnection,
                  icon: const Icon(Icons.wifi_tethering_rounded),
                  label: const Text('测试连接'),
                ),
              ),
              if (cloudProvider && apiKeyConfigured) ...[
                const SizedBox(width: 10),
                IconButton.outlined(
                  tooltip: '清除 API Key',
                  onPressed: loading ? null : _clearApiKey,
                  icon: const Icon(Icons.delete_outline_rounded),
                ),
              ],
            ],
          ),
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: loading ? null : _save,
              icon: loading
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.save_rounded),
              label: const Text('保存 AI 配置'),
            ),
          ),
        ],
      ),
    );
  }
}
