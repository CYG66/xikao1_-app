part of '../main.dart';

// -----------------------------------------------------------------------------
// 业务页面与页面级导航
// -----------------------------------------------------------------------------

/// 可重复拖动并自动吸附屏幕边缘的智能助手悬浮球。
class _DraggableAgentBall extends StatefulWidget {
  const _DraggableAgentBall({required this.onTap});

  final VoidCallback onTap;

  @override
  State<_DraggableAgentBall> createState() => _DraggableAgentBallState();
}

class _DraggableAgentBallState extends State<_DraggableAgentBall> {
  static const double hitSize = 64;
  static const double visualSize = 48;
  static const double edgeInset = 12;
  Offset? position;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 840;
        final fallback = Offset(
          constraints.maxWidth - hitSize - edgeInset,
          wide
              ? (constraints.maxHeight - hitSize) / 2
              : constraints.maxHeight - hitSize - edgeInset,
        );
        final raw = position ?? fallback;
        final current = Offset(
          raw.dx.clamp(edgeInset, constraints.maxWidth - hitSize - edgeInset),
          raw.dy.clamp(edgeInset, constraints.maxHeight - hitSize - edgeInset),
        );
        return Stack(
          children: [
            Positioned(
              left: current.dx,
              top: current.dy,
              child: GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: widget.onTap,
                onPanUpdate: (details) => setState(() {
                  final last = position ?? current;
                  position = Offset(
                    (last.dx + details.delta.dx)
                        .clamp(
                          edgeInset,
                          constraints.maxWidth - hitSize - edgeInset,
                        )
                        .toDouble(),
                    (last.dy + details.delta.dy)
                        .clamp(
                          edgeInset,
                          constraints.maxHeight - hitSize - edgeInset,
                        )
                        .toDouble(),
                  );
                }),
                onPanEnd: (_) {
                  setState(() {
                    final last = position ?? current;
                    position = Offset(
                      last.dx < constraints.maxWidth / 2
                          ? edgeInset
                          : constraints.maxWidth - hitSize - edgeInset,
                      last.dy,
                    );
                  });
                },
                child: SizedBox(
                  width: hitSize,
                  height: hitSize,
                  child: Center(
                    child: Tooltip(
                      message: '智能助手',
                      child: Material(
                        color: Colors.transparent,
                        child: Ink(
                          width: visualSize,
                          height: visualSize,
                          decoration: BoxDecoration(
                            color: const Color(0xff16a66a),
                            shape: BoxShape.circle,
                            border: Border.all(color: Colors.white, width: 2),
                            boxShadow: const [
                              BoxShadow(
                                color: Color(0x260f172a),
                                blurRadius: 12,
                                offset: Offset(0, 4),
                              ),
                            ],
                          ),
                          child: const Icon(
                            Icons.smart_toy_rounded,
                            size: 23,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

/// 顶部栏：显示 App 名称、当前设备地址和 Bridge 状态。
class _Header extends StatelessWidget {
  const _Header({
    required this.device,
    required this.lineRunning,
    required this.bridgeState,
    required this.emergencyStopped,
    required this.onEmergencyPressed,
  });

  final RoverDevice device;
  final bool lineRunning;
  final BridgeState bridgeState;
  final bool emergencyStopped;
  final VoidCallback onEmergencyPressed;

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 840;
    final connected = bridgeState == BridgeState.connected;
    return Container(
      padding: EdgeInsets.fromLTRB(wide ? 24 : 16, 8, wide ? 24 : 16, 8),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: Color(0xffe2e8f0))),
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(10),
              color: const Color(0xff16a66a),
            ),
            child: const Icon(Icons.precision_manufacturing_rounded),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'XLine 划线小车',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
                ),
                Text(
                  '${device.name} · ${device.bridgeUrl}',
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: Color(0xff64748b),
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
          _StatusChip(
            text: lineRunning ? '划线中' : bridgeState.label,
            color: lineRunning ? const Color(0xfff59e0b) : bridgeState.color,
          ),
          const SizedBox(width: 6),
          if (connected && wide)
            OutlinedButton.icon(
              onPressed: onEmergencyPressed,
              style: OutlinedButton.styleFrom(
                foregroundColor: emergencyStopped
                    ? Colors.white
                    : const Color(0xffdc2626),
                backgroundColor: emergencyStopped
                    ? const Color(0xffdc2626)
                    : const Color(0xfffff1f2),
                side: const BorderSide(color: Color(0xfffecdd3)),
              ),
              icon: Icon(
                emergencyStopped ? Icons.lock_open_rounded : Icons.stop_rounded,
                size: 18,
              ),
              label: Text(emergencyStopped ? '解除急停' : '紧急停车'),
            )
          else if (connected)
            IconButton(
              tooltip: emergencyStopped ? '解除急停' : '紧急停车',
              onPressed: onEmergencyPressed,
              style: IconButton.styleFrom(
                backgroundColor: emergencyStopped
                    ? const Color(0xffdc2626)
                    : const Color(0xfffff1f2),
                foregroundColor: emergencyStopped
                    ? Colors.white
                    : const Color(0xffdc2626),
                side: const BorderSide(color: Color(0xfffecdd3)),
                minimumSize: const Size(38, 38),
                maximumSize: const Size(38, 38),
                padding: EdgeInsets.zero,
              ),
              icon: Icon(
                emergencyStopped ? Icons.lock_open_rounded : Icons.stop_rounded,
                size: 19,
              ),
            ),
        ],
      ),
    );
  }
}
