part of '../main.dart';

/// 设备管理页：切换小车、测试/断开连接、查看 Bridge 日志。
class _DevicePage extends StatelessWidget {
  const _DevicePage({
    required this.devices,
    required this.message,
    required this.bridgeState,
    required this.logs,
    required this.onAddDevice,
    required this.onConnect,
    required this.onDelete,
    required this.onTestActive,
    required this.onDisconnect,
    required this.onProvisionWifi,
  });

  final List<RoverDevice> devices;
  final String message;
  final BridgeState bridgeState;
  final List<String> logs;
  final VoidCallback onAddDevice;
  final ValueChanged<int> onConnect;
  final ValueChanged<int> onDelete;
  final VoidCallback onTestActive;
  final VoidCallback onDisconnect;
  final VoidCallback onProvisionWifi;

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
              OutlinedButton.icon(
                onPressed: onProvisionWifi,
                icon: const Icon(Icons.wifi_find_rounded),
                label: const Text('为小车接入 Wi-Fi'),
              ),
              const SizedBox(height: 12),
              for (var i = 0; i < devices.length; i++)
                _DeviceTile(
                  device: devices[i],
                  onConnect: () => onConnect(i),
                  onDelete: () => onDelete(i),
                ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        _ConnectionDiagnostics(
          device: devices.isEmpty ? null : devices.first,
          bridgeState: bridgeState,
          message: message,
          logs: logs,
        ),
        const SizedBox(height: 14),
        _Panel(
          title: 'Bridge 通信日志',
          trailing: const Text(
            'JSON ROS Bridge',
            style: TextStyle(color: Color(0xff94a3b8), fontSize: 12),
          ),
          child: ExpansionTile(
            tilePadding: EdgeInsets.zero,
            childrenPadding: EdgeInsets.zero,
            title: Text(
              logs.isEmpty ? '暂无日志' : '查看最近 ${logs.take(10).length} 条日志',
              style: const TextStyle(fontSize: 13, color: Color(0xff64748b)),
            ),
            children: [
              for (final line in logs.take(10))
                Align(
                  alignment: Alignment.centerLeft,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Text(
                      line,
                      style: const TextStyle(
                        color: Color(0xff64748b),
                        fontSize: 12,
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ConnectionDiagnostics extends StatelessWidget {
  const _ConnectionDiagnostics({
    required this.device,
    required this.bridgeState,
    required this.message,
    required this.logs,
  });
  final RoverDevice? device;
  final BridgeState bridgeState;
  final String message;
  final List<String> logs;

  @override
  Widget build(BuildContext context) {
    final connected = bridgeState == BridgeState.connected;
    final connecting = bridgeState == BridgeState.connecting;
    final checks = <_DiagnosticCheck>[
      _DiagnosticCheck(
        '设备配置',
        device == null ? '未配置设备' : '${device!.ip}:${device!.port}',
        device != null,
      ),
      _DiagnosticCheck(
        'FastAPI Bridge',
        connecting
            ? '正在连接'
            : connected
            ? '已连接'
            : '未连接',
        connected,
      ),
      _DiagnosticCheck(
        'ROS2 运行层',
        connected ? '等待遥测确认' : '等待 Bridge 连接',
        connected,
      ),
      _DiagnosticCheck(
        '遥测链路',
        logs.any((line) => line.contains('telemetry')) ? '已收到数据' : '等待数据',
        logs.any((line) => line.contains('telemetry')),
      ),
    ];
    return _Panel(
      title: '连接诊断',
      trailing: _StatusChip(
        text: connected
            ? '诊断通过'
            : connecting
            ? '检测中'
            : '需要处理',
        color: connected
            ? const Color(0xff16a66a)
            : connecting
            ? const Color(0xff2563eb)
            : const Color(0xffb45309),
      ),
      child: Column(
        children: [
          for (final check in checks) _DiagnosticCheckRow(check: check),
          const Divider(height: 18),
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              message,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 12, color: Color(0xff64748b)),
            ),
          ),
        ],
      ),
    );
  }
}

class _DiagnosticCheck {
  const _DiagnosticCheck(this.title, this.detail, this.ok);
  final String title, detail;
  final bool ok;
}

class _DiagnosticCheckRow extends StatelessWidget {
  const _DiagnosticCheckRow({required this.check});
  final _DiagnosticCheck check;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 5),
    child: Row(
      children: [
        Icon(
          check.ok
              ? Icons.check_circle_rounded
              : Icons.radio_button_unchecked_rounded,
          size: 18,
          color: check.ok ? const Color(0xff16a66a) : const Color(0xff94a3b8),
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Text(
            check.title,
            style: const TextStyle(fontWeight: FontWeight.w700),
          ),
        ),
        Text(
          check.detail,
          style: TextStyle(
            fontSize: 12,
            color: check.ok ? const Color(0xff15803d) : const Color(0xff64748b),
          ),
        ),
      ],
    ),
  );
}

class _WifiProvisionSheet extends StatefulWidget {
  const _WifiProvisionSheet({
    required this.device,
    required this.onStatus,
    required this.onScan,
    required this.onConnect,
  });

  final RoverDevice device;
  final Future<Map<String, dynamic>> Function() onStatus;
  final Future<Map<String, dynamic>> Function() onScan;
  final Future<Map<String, dynamic>> Function({
    required String ssid,
    required String password,
    required bool hidden,
  })
  onConnect;

  @override
  State<_WifiProvisionSheet> createState() => _WifiProvisionSheetState();
}

class _WifiProvisionSheetState extends State<_WifiProvisionSheet> {
  final ssidController = TextEditingController();
  final passwordController = TextEditingController();
  List<Map<String, dynamic>> networks = const [];
  String status = '正在检查小车无线网卡...';
  bool loading = true;
  bool connecting = false;
  bool hidden = false;
  bool obscurePassword = true;

  @override
  void initState() {
    super.initState();
    unawaited(_loadNetworks());
  }

  @override
  void dispose() {
    ssidController.dispose();
    passwordController.dispose();
    super.dispose();
  }

  Future<void> _loadNetworks() async {
    setState(() {
      loading = true;
      status = '正在扫描小车周边 Wi-Fi...';
    });
    try {
      final adapter = await widget.onStatus();
      if (adapter['available'] != true) {
        if (!mounted) return;
        setState(() => status = adapter['message']?.toString() ?? '小车无线网卡不可用');
        return;
      }
      final result = await widget.onScan();
      if (!mounted) return;
      final raw = result['networks'];
      setState(() {
        networks = raw is List
            ? raw.whereType<Map>().map(Map<String, dynamic>.from).toList()
            : const [];
        status = result['message']?.toString() ?? '扫描完成';
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => status = '无法访问小车网络配置接口，请确认后端已同步');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _connect() async {
    final ssid = ssidController.text.trim();
    if (ssid.isEmpty) {
      setState(() => status = '请选择或输入 Wi-Fi 名称');
      return;
    }
    setState(() {
      connecting = true;
      status = '正在将 Wi-Fi 配置保存到小车...';
    });
    try {
      final result = await widget.onConnect(
        ssid: ssid,
        password: passwordController.text,
        hidden: hidden,
      );
      if (!mounted) return;
      setState(() => status = result['message']?.toString() ?? '配置完成');
    } catch (_) {
      if (!mounted) return;
      setState(() => status = '配置请求失败，请保持连接后重试');
    } finally {
      if (mounted) setState(() => connecting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final keyboard = MediaQuery.of(context).viewInsets.bottom;
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(18, 18, 18, keyboard + 18),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 620),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(
                      Icons.wifi_find_rounded,
                      color: Color(0xff168a60),
                    ),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Text(
                        '为小车接入互联网',
                        style: TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: '关闭',
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  '当前小车：${widget.device.name} · ${widget.device.ip}',
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xff64748b),
                  ),
                ),
                const SizedBox(height: 14),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xffecfdf5),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: const Color(0xffa7f3d0)),
                  ),
                  child: const Text(
                    '配置会保存到小车的 NetworkManager。小车切换到新 Wi-Fi 后，当前 App 连接可能中断；请在同一网络下用新的小车地址重新连接。密码不会显示、保存到 App 或写入日志。',
                    style: TextStyle(
                      fontSize: 12,
                      height: 1.45,
                      color: Color(0xff166534),
                    ),
                  ),
                ),
                const SizedBox(height: 14),
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        '可用 Wi-Fi',
                        style: TextStyle(fontWeight: FontWeight.w800),
                      ),
                    ),
                    IconButton(
                      tooltip: '重新扫描',
                      onPressed: loading ? null : _loadNetworks,
                      icon: loading
                          ? const SizedBox(
                              height: 18,
                              width: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.refresh_rounded),
                    ),
                  ],
                ),
                if (networks.isEmpty && !loading)
                  Text(
                    status,
                    style: const TextStyle(
                      color: Color(0xff64748b),
                      fontSize: 12,
                    ),
                  )
                else
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 180),
                    child: ListView.separated(
                      shrinkWrap: true,
                      itemCount: networks.length,
                      separatorBuilder: (_, _) => const Divider(height: 1),
                      itemBuilder: (context, index) {
                        final network = networks[index];
                        final ssid = network['ssid']?.toString() ?? '';
                        final signal = network['signal']?.toString() ?? '--';
                        return ListTile(
                          dense: true,
                          leading: const Icon(Icons.wifi_rounded),
                          title: Text(ssid),
                          subtitle: Text(
                            '${network['security'] ?? '未知加密'} · 信号 $signal%',
                          ),
                          onTap: () => setState(() {
                            ssidController.text = ssid;
                            hidden = false;
                          }),
                        );
                      },
                    ),
                  ),
                const SizedBox(height: 12),
                TextField(
                  controller: ssidController,
                  maxLength: 32,
                  decoration: const InputDecoration(
                    labelText: 'Wi-Fi 名称（SSID）',
                    prefixIcon: Icon(Icons.wifi_rounded),
                  ),
                ),
                TextField(
                  controller: passwordController,
                  obscureText: obscurePassword,
                  enableSuggestions: false,
                  autocorrect: false,
                  decoration: InputDecoration(
                    labelText: 'Wi-Fi 密码（开放网络可留空）',
                    prefixIcon: const Icon(Icons.lock_outline_rounded),
                    suffixIcon: IconButton(
                      tooltip: obscurePassword ? '显示密码' : '隐藏密码',
                      onPressed: () =>
                          setState(() => obscurePassword = !obscurePassword),
                      icon: Icon(
                        obscurePassword
                            ? Icons.visibility_outlined
                            : Icons.visibility_off_outlined,
                      ),
                    ),
                  ),
                ),
                SwitchListTile.adaptive(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('隐藏 Wi-Fi'),
                  subtitle: const Text('未出现在扫描列表时打开'),
                  value: hidden,
                  onChanged: connecting
                      ? null
                      : (value) => setState(() => hidden = value),
                ),
                Text(
                  status,
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xff64748b),
                  ),
                ),
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: connecting ? null : _connect,
                    icon: connecting
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.wifi_password_rounded),
                    label: const Text('保存到小车并切换网络'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 添加小车的底部弹窗入口。
class _AddDeviceSheet extends StatefulWidget {
  const _AddDeviceSheet();

  @override
  State<_AddDeviceSheet> createState() => _AddDeviceSheetState();
}

/// 管理设备表单、输入校验和测试状态。
class _AddDeviceSheetState extends State<_AddDeviceSheet> {
  final nameController = TextEditingController();
  final ipController = TextEditingController();
  final portController = TextEditingController(text: '8000');
  final domainController = TextEditingController(text: '0');
  static const String type = 'FastAPI Backend';
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
            const _ConfigRow('连接类型', 'FastAPI ROS2 Bridge'),
            const SizedBox(height: 12),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(8),
                color: const Color(0xfff8fafc),
                border: Border.all(color: const Color(0xffdce3ea)),
              ),
              child: Text(
                '连接地址：ws://${ipController.text}:${portController.text}\n状态：$testStatus',
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

  /// 请求后端 `/health`，只有收到 `ok: true` 才判定连接测试成功。
  Future<void> _testConnection() async {
    setState(() {
      testing = true;
      testStatus = '正在检查 FastAPI ROS2 Bridge...';
    });
    final ip = ipController.text.trim();
    final port = int.tryParse(portController.text.trim());
    String result;
    if (ip.isEmpty || port == null) {
      result = '失败：请填写有效的 IP 和端口';
    } else {
      final client = HttpClient()
        ..connectionTimeout = const Duration(seconds: 3);
      try {
        final request = await client.getUrl(
          Uri.parse('http://$ip:$port/health'),
        );
        final response = await request.close().timeout(
          const Duration(seconds: 4),
        );
        final body = await utf8.decoder.bind(response).join();
        final decoded = jsonDecode(body);
        result =
            response.statusCode == 200 &&
                decoded is Map &&
                decoded['ok'] == true
            ? '测试通过：后端健康检查正常'
            : '失败：后端响应无效';
      } catch (error) {
        result = '失败：无法访问后端';
      } finally {
        client.close(force: true);
      }
    }
    if (!mounted) return;
    setState(() {
      testing = false;
      testStatus = result;
    });
  }

  /// 校验必填项，生成 [RoverDevice] 并关闭弹窗。
  void _saveDevice() {
    final ip = ipController.text.trim();
    final name = nameController.text.trim();
    final port = int.tryParse(portController.text.trim()) ?? 8000;
    final domainId = int.tryParse(domainController.text.trim()) ?? 0;
    if (ip.isEmpty || name.isEmpty) {
      setState(() => testStatus = '失败：设备名称和 IP 不能为空');
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
      ),
    );
  }
}
