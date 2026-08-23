part of '../main.dart';

// -----------------------------------------------------------------------------
// 可复用界面组件
// -----------------------------------------------------------------------------

/// 紧凑的当前设备摘要行。
class _CompactDeviceRow extends StatelessWidget {
  const _CompactDeviceRow({required this.device});

  final RoverDevice device;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 42,
          height: 42,
          decoration: BoxDecoration(
            color: const Color(0xff172033),
            borderRadius: BorderRadius.circular(14),
          ),
          child: const Icon(
            Icons.precision_manufacturing_rounded,
            color: Color(0xff60a5fa),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                device.name,
                style: const TextStyle(fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 2),
              Text(
                device.bridgeUrl,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: Color(0xff94a3b8), fontSize: 12),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 首页遥测指标条。所有值均来自后端状态，未上报时显示未知状态。
class _DriveStatusPanel extends StatelessWidget {
  const _DriveStatusPanel({
    required this.transport,
    required this.deviceConnected,
    required this.motorDriverReady,
    required this.controlReady,
  });

  final String transport;
  final bool deviceConnected;
  final bool motorDriverReady;
  final bool controlReady;

  @override
  Widget build(BuildContext context) {
    final ready = controlReady;
    return _Panel(
      title: '底盘驱动',
      trailing: _StatusChip(
        text: ready ? '可控制' : '未就绪',
        color: ready ? const Color(0xff22c55e) : const Color(0xfff59e0b),
      ),
      child: Column(
        children: [
          _ConfigRow('通信方式', transport.toUpperCase()),
          _ConfigRow('电机型号', 'M1505'),
          _ConfigRow(
            transport == 'socketcan' ? 'CAN 接口' : 'USB2CAN',
            deviceConnected ? '已启用' : '未启用',
          ),
          _ConfigRow('电机节点', motorDriverReady ? '运行中' : '未运行'),
        ],
      ),
    );
  }
}

class _MetricStrip extends StatelessWidget {
  const _MetricStrip({
    required this.controlReady,
    required this.linearVelocity,
    required this.localizationAccuracyMm,
    required this.localizationReady,
    required this.printerStatus,
  });

  final bool controlReady;
  final double? linearVelocity;
  final double? localizationAccuracyMm;
  final bool localizationReady;
  final String printerStatus;

  @override
  Widget build(BuildContext context) {
    final localizationText = localizationAccuracyMm != null
        ? '±${localizationAccuracyMm!.toStringAsFixed(0)}mm'
        : localizationReady
        ? '已定位'
        : '未定位';
    return Row(
      children: [
        Expanded(
          child: _MiniMetric(label: '底盘', value: controlReady ? '已就绪' : '未就绪'),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _MiniMetric(
            label: '速度',
            value: linearVelocity == null
                ? '--'
                : '${linearVelocity!.toStringAsFixed(2)}m/s',
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _MiniMetric(label: '定位', value: localizationText),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: _MiniMetric(label: '喷码', value: printerStatus),
        ),
      ],
    );
  }
}

/// 显示后端实际上报的机器人位姿。
/// 没有 `/robot_pose` 数据时不绘制虚构地图或路径。
class _RealtimeRobotView extends StatelessWidget {
  const _RealtimeRobotView({
    required this.rosAvailable,
    required this.pose,
    required this.gridMap,
    required this.plannedPaths,
    required this.poseTrace,
    required this.lineRunning,
    required this.onTap,
    this.height,
    this.showPoseOverlay = true,
  });

  final bool rosAvailable;
  final Map<String, dynamic> pose;
  final Map<String, dynamic> gridMap;
  final List<Map<String, dynamic>> plannedPaths;
  final List<List<double>> poseTrace;
  final bool lineRunning;
  final VoidCallback onTap;
  final double? height;
  final bool showPoseOverlay;

  String _number(String key) {
    final value = pose[key];
    return value is num ? value.toStringAsFixed(2) : '--';
  }

  @override
  Widget build(BuildContext context) {
    final mapReady = gridMap.isNotEmpty;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(12),
          child: SizedBox(
            height: height ?? 220,
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (mapReady)
                  CustomPaint(
                    painter: _MapPainter(
                      lineRunning: lineRunning,
                      gridMap: gridMap,
                      plannedPaths: plannedPaths,
                      robotPose: pose,
                      poseTrace: poseTrace,
                    ),
                  )
                else
                  ColoredBox(
                    color: const Color(0xfff8fafc),
                    child: Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            rosAvailable
                                ? Icons.map_outlined
                                : Icons.hub_outlined,
                            size: 34,
                            color: const Color(0xff64748b),
                          ),
                          const SizedBox(height: 10),
                          Text(
                            rosAvailable ? '等待地图数据' : 'ROS2 节点未就绪',
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                        ],
                      ),
                    ),
                  ),
                if (showPoseOverlay)
                  Positioned(
                    left: 10,
                    right: 10,
                    bottom: 10,
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 8,
                      ),
                      decoration: BoxDecoration(
                        color: const Color(0xf2ffffff),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: const Color(0xffdce3ea)),
                      ),
                      child: Row(
                        children: [
                          const Icon(
                            Icons.my_location_rounded,
                            size: 17,
                            color: Color(0xff22c55e),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              'X ${_number('x')}   Y ${_number('y')}   航向 ${_number('theta')}°',
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                          const Icon(
                            Icons.chevron_right_rounded,
                            size: 20,
                            color: Color(0xff94a3b8),
                          ),
                        ],
                      ),
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

/// 单个紧凑遥测值卡片。
class _MiniMetric extends StatelessWidget {
  const _MiniMetric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 74,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xffdce3ea)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: const TextStyle(color: Color(0xff94a3b8), fontSize: 12),
          ),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              value,
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900),
            ),
          ),
        ],
      ),
    );
  }
}

/// 设备列表项，显示小车配置并允许切换连接。
class _DeviceTile extends StatelessWidget {
  const _DeviceTile({
    required this.device,
    required this.onConnect,
    required this.onDelete,
  });

  final RoverDevice device;
  final VoidCallback onConnect;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      child: Material(
        color: Colors.white,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: BorderSide(
            color: device.connected
                ? const Color(0xff22c55e)
                : const Color(0xffdce3ea),
          ),
        ),
        clipBehavior: Clip.antiAlias,
        child: ListTile(
          leading: Icon(
            Icons.precision_manufacturing_rounded,
            color: device.connected
                ? const Color(0xff22c55e)
                : const Color(0xff60a5fa),
          ),
          title: Text(device.name),
          subtitle: Text(
            '${device.type} · ${device.bridgeUrl} · Domain ${device.domainId}',
          ),
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (device.connected)
                const _StatusChip(text: '已连接', color: Color(0xff22c55e))
              else
                TextButton(onPressed: onConnect, child: const Text('连接')),
              IconButton(
                tooltip: '删除设备',
                onPressed: onDelete,
                color: const Color(0xffdc2626),
                icon: const Icon(Icons.delete_outline_rounded),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 主文件内使用的标准内容面板，统一标题、边框和内边距。
class _Panel extends StatelessWidget {
  const _Panel({
    required this.title,
    required this.child,
    this.trailing,
    this.expandChild = false,
  });

  final String title;
  final Widget child;
  final Widget? trailing;
  final bool expandChild;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: const BorderSide(color: Color(0xffdce3ea)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: const TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
                ?trailing,
              ],
            ),
            const SizedBox(height: 12),
            if (expandChild) Expanded(child: child) else child,
          ],
        ),
      ),
    );
  }
}

/// 默认收起的详情面板：首页保持简洁，需要时再查看完整状态。
class _CollapsiblePanel extends StatefulWidget {
  const _CollapsiblePanel({
    required this.title,
    required this.statusText,
    required this.statusColor,
    required this.child,
  });

  final String title;
  final String statusText;
  final Color statusColor;
  final Widget child;

  @override
  State<_CollapsiblePanel> createState() => _CollapsiblePanelState();
}

class _CollapsiblePanelState extends State<_CollapsiblePanel> {
  bool expanded = false;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(10),
        side: const BorderSide(color: Color(0xffdce3ea)),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          InkWell(
            onTap: () => setState(() => expanded = !expanded),
            borderRadius: BorderRadius.circular(10),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      widget.title,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                  _StatusChip(
                    text: widget.statusText,
                    color: widget.statusColor,
                  ),
                  const SizedBox(width: 4),
                  AnimatedRotation(
                    turns: expanded ? 0.5 : 0,
                    duration: const Duration(milliseconds: 180),
                    child: const Icon(
                      Icons.keyboard_arrow_down_rounded,
                      color: Color(0xff64748b),
                    ),
                  ),
                ],
              ),
            ),
          ),
          AnimatedCrossFade(
            firstChild: const SizedBox(width: double.infinity),
            secondChild: Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
              child: widget.child,
            ),
            crossFadeState: expanded
                ? CrossFadeState.showSecond
                : CrossFadeState.showFirst,
            duration: const Duration(milliseconds: 180),
          ),
        ],
      ),
    );
  }
}

/// 大型指标卡，用于航点数、路径长度等统计值。
class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.title,
    required this.value,
    required this.note,
    required this.icon,
  });

  final String title;
  final String value;
  final String note;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 88,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xffdce3ea)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18, color: const Color(0xff16a66a)),
              const SizedBox(width: 6),
              Text(title, style: const TextStyle(color: Color(0xff94a3b8))),
            ],
          ),
          const Spacer(),
          Text(
            value,
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900),
          ),
          Text(
            note,
            style: const TextStyle(color: Color(0xff64748b), fontSize: 12),
          ),
        ],
      ),
    );
  }
}

/// 状态标签，文字和颜色由上层业务状态决定。
class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.text, required this.color});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.45)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 5),
          Text(
            text,
            style: TextStyle(
              color: color,
              fontSize: 11,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

/// 任务流程中的单个步骤和完成状态。
class _MissionStep extends StatelessWidget {
  const _MissionStep({required this.title, required this.done});

  final String title;
  final bool done;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Icon(
            done
                ? Icons.check_circle_rounded
                : Icons.radio_button_unchecked_rounded,
            color: done ? const Color(0xff22c55e) : const Color(0xff64748b),
          ),
          const SizedBox(width: 10),
          Expanded(child: Text(title)),
        ],
      ),
    );
  }
}

/// 方向控制区，将按钮点击映射为线速度和角速度。
class _Joystick extends StatefulWidget {
  const _Joystick({
    required this.maxLinearSpeed,
    required this.maxAngularSpeed,
    required this.onCommand,
  });

  final double maxLinearSpeed;
  final double maxAngularSpeed;
  final void Function(double linear, double angular) onCommand;

  @override
  State<_Joystick> createState() => _JoystickState();
}

class _JoystickState extends State<_Joystick> {
  static const double deadZone = 0.10;

  Offset knobOffset = Offset.zero;
  double linear = 0;
  double angular = 0;
  Timer? commandTimer;
  ScrollHoldController? scrollHold;

  void _holdPageScroll() {
    scrollHold ??= Scrollable.maybeOf(context)?.position.hold(() {});
  }

  void _releasePageScroll() {
    scrollHold?.cancel();
    scrollHold = null;
  }

  void _update(Offset localPosition, double size) {
    final travelRadius = size * 0.305;
    var offset = localPosition - Offset(size / 2, size / 2);
    if (offset.distance > travelRadius) {
      offset = Offset.fromDirection(offset.direction, travelRadius);
    }
    final normalizedX = offset.dx / travelRadius;
    final normalizedY = offset.dy / travelRadius;
    // Scale the dead zone continuously so crossing its edge does not create
    // a sudden velocity jump on a touch screen.
    double applyDeadZone(double value) {
      final magnitude = value.abs();
      if (magnitude <= deadZone) return 0.0;
      final scaled = ((magnitude - deadZone) / (1 - deadZone)).clamp(0.0, 1.0);
      return value.sign * scaled;
    }

    final nextLinear = -applyDeadZone(normalizedY) * widget.maxLinearSpeed;
    final nextAngular = -applyDeadZone(normalizedX) * widget.maxAngularSpeed;
    setState(() {
      knobOffset = offset;
      linear = nextLinear;
      angular = nextAngular;
    });
    widget.onCommand(linear, angular);
  }

  void _start(DragStartDetails details, double size) {
    _holdPageScroll();
    commandTimer?.cancel();
    _update(details.localPosition, size);
    commandTimer = Timer.periodic(
      const Duration(milliseconds: 40),
      (_) => widget.onCommand(linear, angular),
    );
  }

  void _stop() {
    _releasePageScroll();
    commandTimer?.cancel();
    commandTimer = null;
    if (mounted) {
      setState(() {
        knobOffset = Offset.zero;
        linear = 0;
        angular = 0;
      });
    }
    widget.onCommand(0, 0);
  }

  @override
  void dispose() {
    _releasePageScroll();
    commandTimer?.cancel();
    widget.onCommand(0, 0);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final boundedWidth = constraints.hasBoundedWidth
            ? constraints.maxWidth
            : 320.0;
        final boundedHeight = constraints.hasBoundedHeight
            ? constraints.maxHeight
            : 270.0;
        final size = math
            .min(boundedWidth, math.max(140, boundedHeight - 48))
            .clamp(140.0, 300.0)
            .toDouble();
        final knobSize = size * 0.38;
        return Column(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Expanded(
              child: Center(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onPanDown: (_) => _holdPageScroll(),
                  onPanStart: (details) => _start(details, size),
                  onPanUpdate: (details) =>
                      _update(details.localPosition, size),
                  onPanEnd: (_) => _stop(),
                  onPanCancel: _stop,
                  child: Container(
                    width: size,
                    height: size,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: const Color(0xfff8fafc),
                      border: Border.all(
                        color: const Color(0xffcbd5e1),
                        width: 2,
                      ),
                    ),
                    child: Stack(
                      alignment: Alignment.center,
                      children: [
                        Container(
                          width: 2,
                          height: size * 0.61,
                          color: const Color(0xff1e3352),
                        ),
                        Container(
                          width: size * 0.61,
                          height: 2,
                          color: const Color(0xff1e3352),
                        ),
                        Transform.translate(
                          offset: knobOffset,
                          child: AnimatedContainer(
                            duration: const Duration(milliseconds: 70),
                            width: knobSize,
                            height: knobSize,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              gradient: const LinearGradient(
                                colors: [Color(0xff2563eb), Color(0xff22c55e)],
                              ),
                              boxShadow: [
                                BoxShadow(
                                  color: const Color(
                                    0xff2563eb,
                                  ).withValues(alpha: 0.35),
                                  blurRadius: 26,
                                ),
                              ],
                            ),
                            child: const Icon(
                              Icons.open_with_rounded,
                              size: 30,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 8),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
              decoration: BoxDecoration(
                color: const Color(0xff0f172a),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0xff22304a)),
              ),
              child: Text(
                '线速度 ${linear.toStringAsFixed(2)} m/s   '
                '角速度 ${angular.toStringAsFixed(2)} rad/s',
                textAlign: TextAlign.center,
                style: const TextStyle(color: Color(0xff94a3b8), fontSize: 12),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _CommandButton extends StatelessWidget {
  const _CommandButton({
    required this.label,
    required this.icon,
    required this.onPressed,
  });

  final String label;
  final IconData icon;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: onPressed,
      icon: Icon(icon),
      label: Text(label),
    );
  }
}

/// 任务列表项，展示业务名称、ROS2 模块名和运行状态。
class _TaskTile extends StatelessWidget {
  const _TaskTile(this.title, this.subtitle, this.done);

  final String title;
  final String subtitle;
  final bool done;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: ListTile(
        contentPadding: EdgeInsets.zero,
        leading: Icon(
          done ? Icons.task_alt_rounded : Icons.pending_rounded,
          color: done ? const Color(0xff22c55e) : const Color(0xfff59e0b),
        ),
        title: Text(title),
        subtitle: Text(subtitle),
      ),
    );
  }
}

/// ROS2 Topic 名称与消息类型说明行。
class _TopicRow extends StatelessWidget {
  const _TopicRow(this.topic, this.type);

  final String topic;
  final String type;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: ListTile(
        dense: true,
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.topic_rounded, color: Color(0xff60a5fa)),
        title: Text(topic),
        subtitle: Text(type),
      ),
    );
  }
}

/// 设置页中的键值配置行。
class _ConfigRow extends StatelessWidget {
  const _ConfigRow(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: const TextStyle(color: Color(0xff94a3b8)),
            ),
          ),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    );
  }
}

/// 添加设备表单使用的统一输入框。
class _Field extends StatelessWidget {
  const _Field({
    required this.label,
    required this.controller,
    required this.icon,
    this.keyboardType,
  });

  final String label;
  final TextEditingController controller;
  final IconData icon;
  final TextInputType? keyboardType;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextField(
        controller: controller,
        keyboardType: keyboardType,
        decoration: _inputDecoration(label, icon),
        onChanged: (_) => (context as Element).markNeedsBuild(),
      ),
    );
  }
}

InputDecoration _inputDecoration(String label, IconData icon) {
  return InputDecoration(
    labelText: label,
    prefixIcon: Icon(icon),
    filled: true,
    fillColor: const Color(0xfff8fafc),
    border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: const BorderSide(color: Color(0xffcbd5e1)),
    ),
  );
}
