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
    required this.battery,
    required this.printerReady,
    required this.localizationValid,
    required this.onAskAi,
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
  final Map<String, dynamic> telemetryContract;
  final VoidCallback onAskAi;
  @override
  State<_MonitorPage> createState() => _MonitorPageState();
}

class _MonitorPageState extends State<_MonitorPage> {
  int tab = 0;
  bool aiChecked = false;
  bool saved = false;
  bool get healthy =>
      widget.backendOnline &&
      widget.rosAvailable &&
      widget.controlReady &&
      widget.driveDeviceConnected &&
      widget.motorDriverReady;
  List<String> get issues => [
    if (!widget.backendOnline) '后端未连接',
    if (!widget.rosAvailable) 'ROS2 运行层未就绪',
    if (!widget.driveDeviceConnected) 'CAN 设备未连接',
    if (!widget.motorDriverReady) '底盘驱动未就绪',
    if (!widget.localizationValid) '定位数据无效',
  ];

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final wide = constraints.maxWidth >= 900;
      final content = tab == 0 && wide
          ? Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: _deviceView()),
                const SizedBox(width: 12),
                Expanded(child: _linkView()),
              ],
            )
          : [_deviceView(), _linkView(), _energyView(), _faultView()][tab];
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
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 6),
            child: wide
                ? Row(
                    children: [
                      const Spacer(),
                      tabs,
                      const SizedBox(width: 12),
                      _StatusChip(
                        text: healthy ? '实时监控' : '发现异常',
                        color: healthy
                            ? const Color(0xff16a66a)
                            : const Color(0xffdc2626),
                      ),
                    ],
                  )
                : Row(
                    children: [
                      const Spacer(),
                      _StatusChip(
                        text: healthy ? '实时监控' : '发现异常',
                        color: healthy
                            ? const Color(0xff16a66a)
                            : const Color(0xffdc2626),
                      ),
                    ],
                  ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text(
                widget.telemetryAgeMs == null
                    ? '等待设备遥测数据'
                    : '最后更新 ${(widget.telemetryAgeMs! / 1000).toStringAsFixed(1)} 秒前',
                style: const TextStyle(color: Color(0xff64748b)),
              ),
            ),
          ),
          const SizedBox(height: 8),
          if (!wide)
            Align(
              alignment: Alignment.centerLeft,
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: tabs,
              ),
            ),
          const SizedBox(height: 6),
          Expanded(
            child: SingleChildScrollView(
              padding: EdgeInsets.fromLTRB(
                wide ? 16 : 14,
                4,
                wide ? 16 : 14,
                16,
              ),
              child: content,
            ),
          ),
        ],
      );
    },
  );

  Widget _deviceView() => Column(
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
              widget.printerReady ? '就绪' : '未就绪',
              Icons.print_rounded,
              widget.printerReady,
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
    ],
  );

  Widget _linkView() => _MonitorSection(
    title: '链路监控',
    child: Column(
      children: [
        _LinkNode('App / FastAPI', 'WebSocket 服务', widget.backendOnline),
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
      ],
    ),
  );

  Widget _energyView() {
    final energy = widget.telemetryContract['energy'] is Map
        ? Map<String, dynamic>.from(widget.telemetryContract['energy'] as Map)
        : const <String, dynamic>{};
    final voltage = energy['voltage'];
    final current = energy['current'];
    final temperature = energy['temperature'];
    final level = ((widget.battery ?? 0).clamp(0, 100)) / 100;
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
              _BarMetric('线速度', 0, const Color(0xff2563eb)),
              _BarMetric(
                '轮速反馈',
                widget.wheelSpeeds.isEmpty ? 0 : .5,
                const Color(0xff16a66a),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _faultView() => Column(
    children: [
      _MonitorSection(
        title: '故障记录',
        child: issues.isEmpty && !aiChecked
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
                  if (aiChecked) ...[
                    const Divider(height: 24),
                    const Text(
                      'AI 分析已完成',
                      style: TextStyle(fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 6),
                    const Text('AI 已结合实时快照与本地诊断规则完成核验，请根据建议处理设备。'),
                  ],
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      FilledButton.icon(
                        onPressed: () {
                          setState(() => aiChecked = true);
                          widget.onAskAi();
                        },
                        icon: const Icon(Icons.auto_awesome_rounded),
                        label: const Text('让 AI 检查'),
                      ),
                      const SizedBox(width: 10),
                      OutlinedButton.icon(
                        onPressed: issues.isEmpty
                            ? null
                            : () => setState(() => saved = true),
                        icon: const Icon(Icons.bookmark_add_outlined),
                        label: Text(saved ? '已保存' : '保存记录'),
                      ),
                    ],
                  ),
                ],
              ),
      ),
    ],
  );

  double _number(dynamic value) =>
      value is num ? (value.abs() / 2).clamp(0.0, 1.0).toDouble() : 0;
}

class _MonitorSection extends StatelessWidget {
  const _MonitorSection({required this.title, required this.child});
  final String title;
  final Widget child;
  @override
  Widget build(BuildContext context) => _Panel(title: title, child: child);
}

class _MonitorMetricCard extends StatelessWidget {
  const _MonitorMetricCard(this.title, this.value, this.icon, this.ok);
  final String title, value;
  final IconData icon;
  final bool ok;
  @override
  Widget build(BuildContext context) => SizedBox(
    width: 164,
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              icon,
              color: ok ? const Color(0xff16a66a) : const Color(0xffdc2626),
            ),
            const SizedBox(height: 10),
            Text(title),
            const SizedBox(height: 4),
            Text(
              value,
              style: TextStyle(
                fontSize: 17,
                fontWeight: FontWeight.w800,
                color: ok ? const Color(0xff15803d) : const Color(0xffdc2626),
              ),
            ),
          ],
        ),
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
  final double value;
  final Color color;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 7),
    child: Row(
      children: [
        SizedBox(width: 78, child: Text(label)),
        Expanded(
          child: LinearProgressIndicator(
            value: value,
            minHeight: 10,
            color: color,
          ),
        ),
        const SizedBox(width: 10),
        Text('${(value * 100).round()}%'),
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
