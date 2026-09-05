part of '../main.dart';

class _MonitorPage extends StatefulWidget {
  const _MonitorPage({
    required this.backendOnline,
    required this.rosAvailable,
    required this.controlReady,
    required this.controlGranted,
    required this.driveDeviceConnected,
    required this.motorDriverReady,
    required this.driveTransport,
    required this.driveDevicePath,
    required this.telemetryAgeMs,
    required this.wheelSpeeds,
    required this.motorStatus,
    required this.telemetryContract,
    required this.telemetryApiOnline,
    required this.telemetryApiError,
    required this.telemetryRequestLatencyMs,
    required this.controlChannelConnected,
    required this.battery,
    required this.printerReady,
    required this.printerStatus,
    required this.localizationValid,
    required this.linearVelocity,
    required this.onRefreshTelemetry,
    required this.onRunDiagnosis,
  });
  final bool backendOnline,
      rosAvailable,
      controlReady,
      controlGranted,
      driveDeviceConnected,
      motorDriverReady,
      printerReady,
      localizationValid;
  final String driveTransport, driveDevicePath;
  final int? telemetryAgeMs, battery;
  final Map<String, dynamic> wheelSpeeds, motorStatus;
  final Map<String, dynamic> printerStatus;
  final Map<String, dynamic> telemetryContract;
  final bool telemetryApiOnline;
  final String telemetryApiError;
  final int? telemetryRequestLatencyMs;
  final bool controlChannelConnected;
  final VoidCallback onRefreshTelemetry;
  final Future<Map<String, dynamic>> Function() onRunDiagnosis;
  final double? linearVelocity;
  @override
  State<_MonitorPage> createState() => _MonitorPageState();
}

class _MonitorPageState extends State<_MonitorPage> {
  int tab = 0;
  bool diagnosisRunning = false;
  String? diagnosisError;
  Map<String, dynamic>? diagnosisResult;
  final List<_TelemetrySample> _samples = [];
  final List<_FaultEvent> _faultTimeline = [];
  String _lastIssueKey = '';
  Timer? _sampleTimer;

  @override
  void initState() {
    super.initState();
    _sample();
    widget.onRefreshTelemetry();
    _sampleTimer = Timer.periodic(const Duration(seconds: 2), (_) => _sample());
  }

  @override
  void dispose() {
    _sampleTimer?.cancel();
    super.dispose();
  }

  void _sample() {
    _recordFaults();
    final energy = widget.telemetryContract['energy'] is Map
        ? Map<String, dynamic>.from(widget.telemetryContract['energy'] as Map)
        : const <String, dynamic>{};
    final sample = _TelemetrySample(
      battery: widget.battery?.toDouble(),
      voltage: _asNumber(energy['voltage']),
      current: _asNumber(energy['current']),
      latency: widget.telemetryAgeMs?.toDouble(),
    );
    if (!mounted || !sample.hasValue) return;
    setState(() {
      _samples.add(sample);
      if (_samples.length > 60) _samples.removeAt(0);
    });
  }

  void _recordFaults() {
    final key = issues.join('|');
    if (key == _lastIssueKey) return;
    if (!mounted) {
      _lastIssueKey = key;
      return;
    }
    final resolved = key.isEmpty && _lastIssueKey.isNotEmpty;
    final details = resolved
        ? const ['所有已知异常已恢复']
        : key.isEmpty
        ? const ['当前没有硬件异常']
        : List<String>.from(issues);
    setState(() {
      _faultTimeline.insert(
        0,
        _FaultEvent(
          time: DateTime.now(),
          title: resolved
              ? '异常已恢复'
              : key.isEmpty
              ? '设备状态正常'
              : '检测到异常',
          details: details,
          resolved: resolved || key.isEmpty,
        ),
      );
      if (_faultTimeline.length > 30) _faultTimeline.removeLast();
    });
    _lastIssueKey = key;
  }

  static double? _asNumber(dynamic value) =>
      value is num ? value.toDouble() : null;
  bool get healthy =>
      widget.backendOnline &&
      widget.rosAvailable &&
      widget.controlReady &&
      widget.driveDeviceConnected &&
      widget.motorDriverReady &&
      _printerHealthy;
  List<String> get issues => [
    if (!widget.telemetryApiOnline) '监控接口未连接',
    if (!widget.backendOnline) '后端未连接',
    if (!widget.rosAvailable) 'ROS2 运行层未就绪',
    if (!widget.driveDeviceConnected) 'CAN 设备未连接',
    if (!widget.motorDriverReady) '底盘驱动未就绪',
    if (widget.printerStatus['spray_state']?.toString() == 'error') '喷码机状态异常',
    if (!widget.localizationValid) '定位数据无效',
  ];

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final wide = constraints.maxWidth >= 900;
      final content = switch (tab) {
        0 => _hardwareView(),
        1 =>
          wide
              ? Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: _linkView()),
                    const SizedBox(width: 12),
                    Expanded(
                      child: _LinkQualityPanel(
                        requestLatencyMs: widget.telemetryRequestLatencyMs,
                        backendOnline: widget.backendOnline,
                        controlGranted: widget.controlGranted,
                      ),
                    ),
                  ],
                )
              : Column(
                  children: [
                    _linkView(),
                    const SizedBox(height: 12),
                    _LinkQualityPanel(
                      requestLatencyMs: widget.telemetryRequestLatencyMs,
                      backendOnline: widget.backendOnline,
                      controlGranted: widget.controlGranted,
                    ),
                  ],
                ),
        2 => _energyView(),
        _ => _faultView(),
      };
      final tabs = SegmentedButton<int>(
        segments: const [
          ButtonSegment(
            value: 0,
            label: Text('设备监控'),
            icon: Icon(Icons.memory_rounded),
          ),
          ButtonSegment(
            value: 1,
            label: Text('链路监控'),
            icon: Icon(Icons.account_tree_rounded),
          ),
          ButtonSegment(
            value: 2,
            label: Text('能源监控'),
            icon: Icon(Icons.battery_full_rounded),
          ),
          ButtonSegment(
            value: 3,
            label: Text('故障记录'),
            icon: Icon(Icons.history_rounded),
          ),
        ],
        selected: {tab},
        onSelectionChanged: (value) => setState(() => tab = value.first),
      );
      return Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
            child: wide
                ? Row(
                    children: [
                      Text(
                        const ['设备监控', '链路监控', '能源监控', '故障记录'][tab],
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const Spacer(),
                      IconButton(
                        tooltip: '刷新实时监控',
                        onPressed: widget.onRefreshTelemetry,
                        icon: Icon(
                          Icons.refresh_rounded,
                          color: widget.telemetryApiOnline
                              ? const Color(0xff16a66a)
                              : const Color(0xffdc2626),
                        ),
                      ),
                      tabs,
                    ],
                  )
                : Align(alignment: Alignment.centerLeft, child: tabs),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 6, 16, 0),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text(
                !widget.telemetryApiOnline
                    ? widget.telemetryApiError.isEmpty
                          ? '监控接口未连接，正在尝试读取小车遥测'
                          : widget.telemetryApiError
                    : widget.telemetryAgeMs == null
                    ? '监控接口已连接，等待设备遥测数据'
                    : '最后更新 ${(widget.telemetryAgeMs! / 1000).toStringAsFixed(1)} 秒前',
                style: const TextStyle(color: Color(0xff64748b), fontSize: 12),
              ),
            ),
          ),
          if (!widget.telemetryApiOnline)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 9,
                ),
                decoration: BoxDecoration(
                  color: const Color(0xfffff7ed),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: const Color(0xfffed7aa)),
                ),
                child: Row(
                  children: [
                    const Icon(
                      Icons.sensors_off_rounded,
                      color: Color(0xffc2410c),
                      size: 18,
                    ),
                    const SizedBox(width: 8),
                    const Expanded(
                      child: Text(
                        '未收到小车遥测，当前内容不会作为实时监控结果。',
                        style: TextStyle(fontSize: 12),
                      ),
                    ),
                    TextButton(
                      onPressed: widget.onRefreshTelemetry,
                      child: const Text('重试'),
                    ),
                  ],
                ),
              ),
            ),
          Expanded(
            child: SingleChildScrollView(
              padding: EdgeInsets.fromLTRB(
                wide ? 16 : 14,
                4,
                wide ? 16 : 14,
                16,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [content],
              ),
            ),
          ),
        ],
      );
    },
  );

  Widget _hardwareView() => Column(
    children: [
      _MonitorSection(
        title: '执行机构状态',
        child: Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            _MonitorMetricCard(
              '底盘驱动',
              widget.motorDriverReady ? '运行中' : '未就绪',
              Icons.settings_input_component_rounded,
              widget.motorDriverReady,
            ),
            _MonitorMetricCard(
              '喷码机',
              _printerLabel(),
              Icons.print_rounded,
              _printerHealthy,
            ),
            _MonitorMetricCard(
              '定位',
              widget.localizationValid ? '有效' : '无效',
              Icons.gps_fixed_rounded,
              widget.localizationValid,
            ),
          ],
        ),
      ),
      const SizedBox(height: 12),
      _MonitorSection(
        title: '轮速与电机',
        child: Column(
          children: [
            _BarMetric(
              '左轮',
              _number(widget.wheelSpeeds['left']),
              const Color(0xff16a66a),
            ),
            _BarMetric(
              '右轮',
              _number(widget.wheelSpeeds['right']),
              const Color(0xff2563eb),
            ),
            _BarMetric(
              '电机负载',
              _number(widget.motorStatus['load']),
              const Color(0xfff59e0b),
            ),
          ],
        ),
      ),
      const SizedBox(height: 12),
      _printerView(),
    ],
  );

  Widget _printerView() => _MonitorSection(
    title: '喷码机状态闭环',
    child: _PrinterLifecycle(
      status: widget.printerStatus,
      ready: widget.printerReady,
    ),
  );

  bool get _printerHealthy {
    final state = widget.printerStatus['spray_state']?.toString() ?? 'idle';
    return widget.printerReady && state != 'error';
  }

  String _printerLabel() {
    final state = widget.printerStatus['spray_state']?.toString() ?? 'idle';
    return switch (state) {
      'starting' => '开启中',
      'stopping' => '关闭中',
      'spraying' => '喷墨中',
      'triggered_unverified' => '待确认',
      'error' => '故障',
      _ => widget.printerReady ? '待机' : '未就绪',
    };
  }

  Widget _linkView() => _MonitorSection(
    title: '链路监控',
    child: Column(
      children: [
        _LinkNode('监控通道', 'FastAPI /api/telemetry', widget.telemetryApiOnline),
        _LinkNode('控制通道', 'WebSocket 指令通道', widget.controlChannelConnected),
        _LinkNode('ROS2 运行层', '节点与话题', widget.rosAvailable),
        _LinkNode(
          'CAN 总线',
          '${widget.driveTransport} · ${widget.driveDevicePath}',
          widget.driveDeviceConnected,
        ),
        _LinkNode('底盘驱动', '电机控制节点', widget.motorDriverReady),
        _LinkNode(
          '控制权限',
          widget.controlGranted ? '当前 App 已获得' : '未获得',
          widget.controlGranted,
        ),
        const Divider(height: 18),
        _LinkLatencyList(data: _linkLatencyData()),
      ],
    ),
  );

  Map<String, dynamic> _linkLatencyData() {
    final raw =
        widget.telemetryContract['link_latency'] ??
        widget.telemetryContract['link'] ??
        widget.telemetryContract['links'];
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return {
      'App → FastAPI 轮询 RTT': widget.telemetryRequestLatencyMs,
      'ROS2 位姿数据年龄': widget.telemetryAgeMs,
    };
  }

  Widget _energyView() {
    final energy = widget.telemetryContract['energy'] is Map
        ? Map<String, dynamic>.from(widget.telemetryContract['energy'] as Map)
        : const <String, dynamic>{};
    final voltage = energy['voltage'];
    final current = energy['current'];
    final temperature = energy['temperature'];
    final energyAvailable = energy['available'] == true;
    final energySource = energy['source']?.toString();
    final energyAgeMs = energy['age_ms'] as num?;
    final level = ((widget.battery ?? 0).clamp(0, 100)) / 100;
    final rails = _energyRails(energy);
    return Column(
      children: [
        _MonitorSection(
          title: '能源监控',
          child: Row(
            children: [
              SizedBox(
                width: 118,
                height: 118,
                child: CustomPaint(
                  painter: _BatteryPainter(level: level),
                  child: Center(
                    child: Text(
                      widget.battery == null ? '--' : '${widget.battery}%',
                      style: const TextStyle(
                        fontSize: 22,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      '电池电量',
                      style: TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      energyAvailable
                          ? '数据源：${energySource == 'ros_battery_state' ? '车载 BMS' : energySource ?? '已接入'}${energyAgeMs == null ? '' : ' · ${energyAgeMs.toInt()} ms 前'}'
                          : '主电源 BMS 未接入 ROS2，无法读取真实电量、电压、电流和温度',
                      style: TextStyle(
                        color: energyAvailable
                            ? const Color(0xff148a5d)
                            : const Color(0xffb45309),
                        fontSize: 12,
                        height: 1.35,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      '电压：${voltage is num ? '${voltage.toStringAsFixed(1)} V' : '设备未提供'}',
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '电流：${current is num ? '${current.toStringAsFixed(1)} A' : '设备未提供'}',
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '温度：${temperature is num ? '${temperature.toStringAsFixed(1)} °C' : '设备未提供'}',
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        _MonitorSection(
          title: '运行遥测',
          child: Column(
            children: [
              _BarMetric(
                '线速度',
                _speedRatio(widget.linearVelocity),
                const Color(0xff2563eb),
              ),
              _BarMetric('轮速反馈', _wheelRatio(), const Color(0xff16a66a)),
            ],
          ),
        ),
        const SizedBox(height: 12),
        _MonitorSection(
          title: '能源分路',
          child: _EnergyRailGrid(rails: rails),
        ),
        const SizedBox(height: 12),
        _energyTrendSection(),
      ],
    );
  }

  Map<String, dynamic> _energyRails(Map<String, dynamic> energy) {
    final raw = energy['rails'] ?? energy['power_rails'] ?? energy['channels'];
    if (raw is Map) return Map<String, dynamic>.from(raw);
    if (energy['voltage'] is num || energy['current'] is num) {
      return {'整机电源': energy};
    }
    return const {};
  }

  Widget _energyTrendSection() => _MonitorSection(
    title: '趋势（最近 2 分钟）',
    child: _TrendGrid(samples: _samples),
  );

  Widget _faultView() => Column(
    children: [
      _MonitorSection(
        title: '故障记录',
        child:
            issues.isEmpty && diagnosisResult == null && diagnosisError == null
            ? const _EmptyFault()
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (issues.isNotEmpty) ...[
                    const Text(
                      '当前异常',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 8),
                    for (final issue in issues) _FaultItem(issue),
                  ],
                  if (diagnosisRunning) ...[
                    const Divider(height: 24),
                    const Row(
                      children: [
                        SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                        SizedBox(width: 8),
                        Text('正在请求后端 AI 与本地诊断规则核验'),
                      ],
                    ),
                  ],
                  if (diagnosisError != null) ...[
                    const Divider(height: 24),
                    Text(
                      diagnosisError!,
                      style: const TextStyle(color: Color(0xffdc2626)),
                    ),
                  ],
                  if (diagnosisResult != null) ...[
                    const Divider(height: 24),
                    Text(
                      diagnosisResult!['diagnosis_source'] ==
                              'api_confirmed_plus_local_rules'
                          ? 'API 分析与本地规则已完成核验'
                          : 'API 分析已完成',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 6),
                    Text(_diagnosisText(diagnosisResult!['api_analysis'])),
                    if (diagnosisResult!['local_diagnosis'] != null) ...[
                      const SizedBox(height: 6),
                      Text(
                        '本地核验：${_diagnosisText(diagnosisResult!['local_diagnosis'])}',
                        style: const TextStyle(color: Color(0xff64748b)),
                      ),
                    ],
                    const SizedBox(height: 10),
                    _DiagnosticSnapshot(
                      battery: widget.battery,
                      telemetryAgeMs: widget.telemetryAgeMs,
                      printerStatus: widget.printerStatus,
                      backendOnline: widget.backendOnline,
                      rosAvailable: widget.rosAvailable,
                      driveDeviceConnected: widget.driveDeviceConnected,
                    ),
                  ],
                  if (_faultTimeline.isNotEmpty) ...[
                    const Divider(height: 24),
                    const Text(
                      '故障时间线',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 6),
                    for (final event in _faultTimeline.take(8))
                      _FaultTimelineItem(event: event),
                  ],
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      FilledButton.icon(
                        onPressed: diagnosisRunning ? null : _runDiagnosis,
                        icon: const Icon(Icons.auto_awesome_rounded),
                        label: Text(diagnosisRunning ? '诊断中' : '真实诊断'),
                      ),
                    ],
                  ),
                ],
              ),
      ),
    ],
  );

  Future<void> _runDiagnosis() async {
    setState(() {
      diagnosisRunning = true;
      diagnosisError = null;
    });
    try {
      final result = await widget.onRunDiagnosis();
      if (!mounted) return;
      setState(() => diagnosisResult = result);
    } catch (error) {
      if (!mounted) return;
      setState(() => diagnosisError = '真实诊断失败：$error');
    } finally {
      if (mounted) setState(() => diagnosisRunning = false);
    }
  }

  String _diagnosisText(dynamic value) {
    if (value is String && value.trim().isNotEmpty) return value.trim();
    if (value is Map) {
      for (final key in const ['message', 'reply', 'content', 'analysis']) {
        final text = value[key]?.toString().trim();
        if (text != null && text.isNotEmpty) return text;
      }
    }
    return '后端未返回可展示的诊断说明。';
  }

  double? _number(dynamic value) =>
      value is num ? (value.abs() / 2).clamp(0.0, 1.0).toDouble() : null;

  double? _speedRatio(double? value) =>
      value == null ? null : (value.abs() / 1.0).clamp(0.0, 1.0).toDouble();

  double? _wheelRatio() {
    final direct =
        widget.wheelSpeeds['left_mps'] ??
        widget.wheelSpeeds['right_mps'] ??
        widget.wheelSpeeds['left'] ??
        widget.wheelSpeeds['right'];
    if (direct is num) return _number(direct);
    final joints = widget.wheelSpeeds['joints_rad_s'];
    if (joints is Map) {
      final left = joints['left_wheel_joint'];
      final right = joints['right_wheel_joint'];
      final peak = [left, right]
          .whereType<num>()
          .map((value) => value.abs().toDouble())
          .fold<double>(
            0,
            (current, value) => current > value ? current : value,
          );
      return (peak / 12).clamp(0.0, 1.0).toDouble();
    }
    return null;
  }
}

class _FaultEvent {
  const _FaultEvent({
    required this.time,
    required this.title,
    required this.details,
    required this.resolved,
  });
  final DateTime time;
  final String title;
  final List<String> details;
  final bool resolved;
}

class _FaultTimelineItem extends StatelessWidget {
  const _FaultTimelineItem({required this.event});
  final _FaultEvent event;

  @override
  Widget build(BuildContext context) {
    final color = event.resolved
        ? const Color(0xff16a66a)
        : const Color(0xffdc2626);
    final time =
        '${event.time.hour.toString().padLeft(2, '0')}:${event.time.minute.toString().padLeft(2, '0')}';
    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            event.resolved ? Icons.check_circle_rounded : Icons.error_rounded,
            color: color,
            size: 18,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        event.title,
                        style: TextStyle(
                          color: color,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    Text(
                      time,
                      style: const TextStyle(
                        fontSize: 11,
                        color: Color(0xff64748b),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  event.details.join(' · '),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xff64748b),
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

class _DiagnosticSnapshot extends StatelessWidget {
  const _DiagnosticSnapshot({
    required this.battery,
    required this.telemetryAgeMs,
    required this.printerStatus,
    required this.backendOnline,
    required this.rosAvailable,
    required this.driveDeviceConnected,
  });
  final int? battery, telemetryAgeMs;
  final Map<String, dynamic> printerStatus;
  final bool backendOnline, rosAvailable, driveDeviceConnected;

  @override
  Widget build(BuildContext context) {
    final printer = printerStatus['spray_state']?.toString() ?? 'idle';
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xfff8fafc),
        border: Border.all(color: const Color(0xffdbe4ec)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Wrap(
        spacing: 14,
        runSpacing: 5,
        children: [
          const Text('本次诊断快照', style: TextStyle(fontWeight: FontWeight.w800)),
          Text('后端 ${backendOnline ? '在线' : '离线'}'),
          Text('ROS2 ${rosAvailable ? '在线' : '离线'}'),
          Text('CAN ${driveDeviceConnected ? '在线' : '离线'}'),
          Text('喷码 $printer'),
          Text('电量 ${battery == null ? '未提供' : '$battery%'}'),
          Text('遥测 ${telemetryAgeMs == null ? '未提供' : '${telemetryAgeMs}ms'}'),
        ],
      ),
    );
  }
}

class _PrinterLifecycle extends StatelessWidget {
  const _PrinterLifecycle({required this.status, required this.ready});
  final Map<String, dynamic> status;
  final bool ready;

  @override
  Widget build(BuildContext context) {
    final state = status['spray_state']?.toString() ?? 'idle';
    final active = switch (state) {
      'starting' => 1,
      'spraying' => 2,
      'stopping' => 3,
      'error' => -1,
      _ => 0,
    };
    const labels = ['连接', '开启中', '喷墨中', '关闭中', '待机'];
    final color = state == 'error'
        ? const Color(0xffdc2626)
        : state == 'spraying'
        ? const Color(0xff16a66a)
        : const Color(0xff2563eb);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                state == 'error'
                    ? '喷码机故障'
                    : !ready
                    ? '喷码节点未就绪'
                    : state == 'spraying'
                    ? '当前正在喷墨'
                    : '当前状态：${state == 'starting'
                          ? '开启中'
                          : state == 'stopping'
                          ? '关闭中'
                          : '待机'}',
                style: TextStyle(color: color, fontWeight: FontWeight.w700),
              ),
            ),
            Text(
              status['ink_level'] is num
                  ? '余量 ${(status['ink_level'] as num).toStringAsFixed(0)}%'
                  : '余量未提供',
              style: const TextStyle(fontSize: 12, color: Color(0xff64748b)),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            for (var i = 0; i < labels.length; i++) ...[
              Expanded(
                child: _PrinterStep(
                  label: labels[i],
                  state: active < 0
                      ? i == 0
                            ? 'done'
                            : 'error'
                      : i < active
                      ? 'done'
                      : i == active
                      ? 'active'
                      : 'pending',
                ),
              ),
              if (i < labels.length - 1)
                Expanded(
                  child: Container(
                    height: 2,
                    color: active > i
                        ? const Color(0xff16a66a)
                        : const Color(0xffdbe4ec),
                  ),
                ),
            ],
          ],
        ),
        if (state == 'error' && status['spray_error'] is String)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              status['spray_error'].toString(),
              style: const TextStyle(color: Color(0xffdc2626), fontSize: 12),
            ),
          ),
      ],
    );
  }
}

class _PrinterStep extends StatelessWidget {
  const _PrinterStep({required this.label, required this.state});
  final String label, state;

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
          size: 19,
          color: color,
        ),
        const SizedBox(height: 3),
        Text(label, style: TextStyle(fontSize: 10, color: color)),
      ],
    );
  }
}

class _EnergyRailGrid extends StatelessWidget {
  const _EnergyRailGrid({required this.rails});
  final Map<String, dynamic> rails;

  @override
  Widget build(BuildContext context) {
    if (rails.isEmpty) {
      return const Text(
        '设备未提供分路电源数据',
        style: TextStyle(color: Color(0xff64748b)),
      );
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 560 ? 2 : 1;
        return GridView.count(
          crossAxisCount: columns,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 8,
          crossAxisSpacing: 12,
          childAspectRatio: 3.8,
          children: rails.entries.map((entry) {
            final data = entry.value is Map
                ? Map<String, dynamic>.from(entry.value as Map)
                : const <String, dynamic>{};
            final voltage = data['voltage'];
            final current = data['current'];
            final temperature = data['temperature'];
            final ok = data['ok'] != false && data['fault'] != true;
            String value(dynamic item, String unit) =>
                item is num ? '${item.toStringAsFixed(1)} $unit' : '--';
            return Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
              decoration: BoxDecoration(
                color: const Color(0xfff8fafc),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: const Color(0xffe2e8f0)),
              ),
              child: Row(
                children: [
                  Icon(
                    Icons.power_rounded,
                    size: 17,
                    color: ok
                        ? const Color(0xff16a66a)
                        : const Color(0xffdc2626),
                  ),
                  const SizedBox(width: 7),
                  Expanded(
                    child: Text(
                      entry.key,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                  Text(
                    '${value(voltage, 'V')} · ${value(current, 'A')} · ${value(temperature, '°C')}',
                    style: const TextStyle(
                      fontSize: 11,
                      color: Color(0xff64748b),
                    ),
                  ),
                ],
              ),
            );
          }).toList(),
        );
      },
    );
  }
}

class _LinkLatencyList extends StatelessWidget {
  const _LinkLatencyList({required this.data});
  final Map<String, dynamic> data;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Align(
        alignment: Alignment.centerLeft,
        child: Text('链路延迟', style: TextStyle(fontWeight: FontWeight.w800)),
      ),
      const SizedBox(height: 4),
      for (final entry in data.entries)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(
            children: [
              Expanded(
                child: Text(entry.key, style: const TextStyle(fontSize: 12)),
              ),
              Text(
                entry.value is num
                    ? '${(entry.value as num).toStringAsFixed(0)} ms'
                    : '设备未提供',
                style: TextStyle(
                  fontSize: 12,
                  color: entry.value is num && (entry.value as num) > 200
                      ? const Color(0xffdc2626)
                      : const Color(0xff64748b),
                ),
              ),
            ],
          ),
        ),
    ],
  );
}

class _LinkQualityPanel extends StatelessWidget {
  const _LinkQualityPanel({
    required this.requestLatencyMs,
    required this.backendOnline,
    required this.controlGranted,
  });
  final int? requestLatencyMs;
  final bool backendOnline, controlGranted;

  @override
  Widget build(BuildContext context) {
    final latency = requestLatencyMs;
    final quality = latency == null
        ? '等待数据'
        : latency > 200
        ? '延迟较高'
        : '连接良好';
    final color = latency == null
        ? const Color(0xff64748b)
        : latency > 200
        ? const Color(0xffdc2626)
        : const Color(0xff16a66a);
    return _MonitorSection(
      title: '链路质量',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.speed_rounded, color: color),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  quality,
                  style: TextStyle(color: color, fontWeight: FontWeight.w800),
                ),
              ),
              Text(
                latency == null ? '--' : '$latency ms',
                style: TextStyle(color: color, fontWeight: FontWeight.w800),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(child: _QualityLine('后端响应', backendOnline)),
              const SizedBox(width: 12),
              Expanded(child: _QualityLine('控制权限', controlGranted)),
            ],
          ),
        ],
      ),
    );
  }
}

class _QualityLine extends StatelessWidget {
  const _QualityLine(this.label, this.ok);
  final String label;
  final bool ok;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Icon(
        ok ? Icons.check_circle_rounded : Icons.error_outline_rounded,
        size: 16,
        color: ok ? const Color(0xff16a66a) : const Color(0xffdc2626),
      ),
      const SizedBox(width: 5),
      Expanded(child: Text(label, style: const TextStyle(fontSize: 12))),
      Text(
        ok ? '正常' : '异常',
        style: TextStyle(
          fontSize: 12,
          color: ok ? const Color(0xff15803d) : const Color(0xffdc2626),
        ),
      ),
    ],
  );
}

class _TelemetrySample {
  const _TelemetrySample({
    this.battery,
    this.voltage,
    this.current,
    this.latency,
  });
  final double? battery, voltage, current, latency;
  bool get hasValue =>
      battery != null || voltage != null || current != null || latency != null;
}

class _TrendGrid extends StatelessWidget {
  const _TrendGrid({required this.samples});
  final List<_TelemetrySample> samples;

  @override
  Widget build(BuildContext context) {
    if (samples.isEmpty) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 18),
        child: Text('暂无可用遥测历史', style: TextStyle(color: Color(0xff64748b))),
      );
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 600 ? 2 : 1;
        return GridView.count(
          crossAxisCount: columns,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 12,
          crossAxisSpacing: 16,
          childAspectRatio: columns == 2 ? 2.7 : 3.6,
          children: [
            _TrendChart(
              title: '电量',
              unit: '%',
              color: const Color(0xff16a66a),
              values: samples.map((e) => e.battery).toList(),
            ),
            _TrendChart(
              title: '电压',
              unit: 'V',
              color: const Color(0xff2563eb),
              values: samples.map((e) => e.voltage).toList(),
            ),
            _TrendChart(
              title: '电流',
              unit: 'A',
              color: const Color(0xfff59e0b),
              values: samples.map((e) => e.current).toList(),
            ),
            _TrendChart(
              title: '通信延迟',
              unit: 'ms',
              color: const Color(0xff7c3aed),
              values: samples.map((e) => e.latency).toList(),
            ),
          ],
        );
      },
    );
  }
}

class _TrendChart extends StatelessWidget {
  const _TrendChart({
    required this.title,
    required this.unit,
    required this.color,
    required this.values,
  });
  final String title, unit;
  final Color color;
  final List<double?> values;

  @override
  Widget build(BuildContext context) {
    final available = values.whereType<double>().toList();
    final latest = available.isEmpty ? null : available.last;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                title,
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
            ),
            Text(
              latest == null ? '--' : '${latest.toStringAsFixed(1)} $unit',
              style: TextStyle(color: color, fontWeight: FontWeight.w800),
            ),
          ],
        ),
        const SizedBox(height: 4),
        Expanded(
          child: CustomPaint(
            painter: _TrendPainter(values: values, color: color),
          ),
        ),
      ],
    );
  }
}

class _TrendPainter extends CustomPainter {
  const _TrendPainter({required this.values, required this.color});
  final List<double?> values;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final border = Paint()
      ..color = const Color(0xffe2e8f0)
      ..style = PaintingStyle.stroke;
    canvas.drawRRect(
      RRect.fromRectAndRadius(Offset.zero & size, const Radius.circular(6)),
      border,
    );
    final data = values.whereType<double>().toList();
    if (data.isEmpty) return;
    final min = data.reduce(math.min);
    final max = data.reduce(math.max);
    final range = (max - min).abs() < 0.001 ? 1.0 : max - min;
    final points = <Offset>[];
    for (var i = 0; i < data.length; i++) {
      final x = data.length == 1
          ? size.width / 2
          : size.width * i / (data.length - 1);
      final y = size.height - ((data[i] - min) / range) * (size.height - 8) - 4;
      points.add(Offset(x, y));
    }
    final line = Paint()
      ..color = color
      ..strokeWidth = 2.2
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;
    final path = Path()..moveTo(points.first.dx, points.first.dy);
    for (final point in points.skip(1)) {
      path.lineTo(point.dx, point.dy);
    }
    canvas.drawPath(path, line);
    canvas.drawCircle(points.last, 3.5, Paint()..color = color);
  }

  @override
  bool shouldRepaint(covariant _TrendPainter oldDelegate) =>
      oldDelegate.values != values || oldDelegate.color != color;
}

class _MonitorSection extends StatelessWidget {
  const _MonitorSection({required this.title, required this.child});
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

class _MonitorMetricCard extends StatelessWidget {
  const _MonitorMetricCard(this.title, this.value, this.icon, this.ok);
  final String title, value;
  final IconData icon;
  final bool ok;
  @override
  Widget build(BuildContext context) => SizedBox(
    width: 164,
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: ok ? const Color(0xfff8fafc) : const Color(0xfffff7f7),
        border: Border(
          left: BorderSide(
            color: ok ? const Color(0xff86efac) : const Color(0xfffca5a5),
            width: 3,
          ),
        ),
      ),
      child: Row(
        children: [
          Icon(
            icon,
            size: 19,
            color: ok ? const Color(0xff16a66a) : const Color(0xffdc2626),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontSize: 12)),
                const SizedBox(height: 2),
                Text(
                  value,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                    color: ok
                        ? const Color(0xff15803d)
                        : const Color(0xffdc2626),
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

class _LinkNode extends StatelessWidget {
  const _LinkNode(this.title, this.detail, this.ok);
  final String title, detail;
  final bool ok;
  @override
  Widget build(BuildContext context) => ListTile(
    leading: Icon(
      ok ? Icons.check_circle_rounded : Icons.error_rounded,
      color: ok ? const Color(0xff16a66a) : const Color(0xffdc2626),
    ),
    title: Text(title),
    subtitle: Text(detail),
    trailing: Text(
      ok ? '正常' : '异常',
      style: TextStyle(
        color: ok ? const Color(0xff15803d) : const Color(0xffdc2626),
        fontWeight: FontWeight.w700,
      ),
    ),
  );
}

class _BarMetric extends StatelessWidget {
  const _BarMetric(this.label, this.value, this.color);
  final String label;
  final double? value;
  final Color color;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 7),
    child: Row(
      children: [
        SizedBox(width: 78, child: Text(label)),
        Expanded(
          child: LinearProgressIndicator(
            value: value ?? 0,
            minHeight: 10,
            color: value == null ? const Color(0xffcbd5e1) : color,
          ),
        ),
        const SizedBox(width: 10),
        Text(value == null ? '--' : '${(value! * 100).round()}%'),
      ],
    ),
  );
}

class _FaultItem extends StatelessWidget {
  const _FaultItem(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 5),
    child: Row(
      children: [
        const Icon(
          Icons.warning_amber_rounded,
          color: Color(0xffdc2626),
          size: 20,
        ),
        const SizedBox(width: 8),
        Text(text),
      ],
    ),
  );
}

class _EmptyFault extends StatelessWidget {
  const _EmptyFault();
  @override
  Widget build(BuildContext context) => const Padding(
    padding: EdgeInsets.symmetric(vertical: 18),
    child: Row(
      children: [
        Icon(Icons.verified_rounded, color: Color(0xff16a66a)),
        SizedBox(width: 10),
        Text('当前没有需要处理的硬件异常'),
      ],
    ),
  );
}

class _BatteryPainter extends CustomPainter {
  const _BatteryPainter({required this.level});
  final double level;
  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final radius = size.shortestSide / 2 - 12;
    final base = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 12
      ..color = const Color(0xffe2e8f0);
    canvas.drawCircle(center, radius, base);
    final active = Paint()
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeWidth = 12
      ..color = level > .2 ? const Color(0xff16a66a) : const Color(0xffdc2626);
    canvas.drawArc(
      Rect.fromCircle(center: center, radius: radius),
      -math.pi / 2,
      2 * math.pi * level,
      false,
      active,
    );
  }

  @override
  bool shouldRepaint(covariant _BatteryPainter oldDelegate) =>
      oldDelegate.level != level;
}
