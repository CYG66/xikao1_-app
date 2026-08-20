part of '../main.dart';

/// 手动控制页：速度调节、方向控制和喷码机快捷指令。
class _ControlPage extends StatelessWidget {
  const _ControlPage({
    required this.linearSpeed,
    required this.angularSpeed,
    required this.onLinearSpeedChanged,
    required this.onAngularSpeedChanged,
    required this.onDriveCommand,
  });

  final double linearSpeed;
  final double angularSpeed;
  final ValueChanged<double> onLinearSpeedChanged;
  final ValueChanged<double> onAngularSpeedChanged;
  final void Function(double linear, double angular) onDriveCommand;

  @override
  Widget build(BuildContext context) {
    final drive = _Panel(
      title: '遥控底盘',
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '${linearSpeed.toStringAsFixed(2)}m/s · ${angularSpeed.toStringAsFixed(1)}rad/s',
            style: const TextStyle(color: Color(0xff64748b), fontSize: 12),
          ),
          const SizedBox(width: 4),
          IconButton(
            tooltip: '控制设置',
            onPressed: () => _showControlSettings(context),
            icon: const Icon(Icons.tune_rounded, size: 20),
          ),
        ],
      ),
      child: Column(
        children: [
          const Text(
            '/tablet_cmd_vel',
            style: TextStyle(color: Color(0xff64748b), fontSize: 12),
          ),
          const SizedBox(height: 8),
          _Joystick(
            maxLinearSpeed: linearSpeed,
            maxAngularSpeed: angularSpeed,
            onCommand: onDriveCommand,
          ),
          const SizedBox(height: 14),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            alignment: WrapAlignment.center,
            children: [
              _DriveCommandButton(
                label: '前进',
                icon: Icons.arrow_upward_rounded,
                onStart: () => onDriveCommand(linearSpeed, 0),
                onStop: () => onDriveCommand(0, 0),
              ),
              _DriveCommandButton(
                label: '左转',
                icon: Icons.turn_left_rounded,
                onStart: () => onDriveCommand(0, angularSpeed),
                onStop: () => onDriveCommand(0, 0),
              ),
              _CommandButton(
                label: '停止',
                icon: Icons.stop_rounded,
                onPressed: () => onDriveCommand(0, 0),
              ),
              _DriveCommandButton(
                label: '右转',
                icon: Icons.turn_right_rounded,
                onStart: () => onDriveCommand(0, -angularSpeed),
                onStop: () => onDriveCommand(0, 0),
              ),
              _DriveCommandButton(
                label: '后退',
                icon: Icons.arrow_downward_rounded,
                onStart: () => onDriveCommand(-linearSpeed, 0),
                onStop: () => onDriveCommand(0, 0),
              ),
            ],
          ),
        ],
      ),
    );
    return LayoutBuilder(
      builder: (context, constraints) {
        return SingleChildScrollView(
          key: const ValueKey('control'),
          padding: EdgeInsets.all(constraints.maxWidth < 840 ? 16 : 24),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 760),
              child: drive,
            ),
          ),
        );
      },
    );
  }

  Future<void> _showControlSettings(BuildContext context) async {
    var draftLinear = linearSpeed.clamp(0.01, AppConstants.maxLinearVelocity);
    var draftAngular = angularSpeed.clamp(0.1, AppConstants.maxAngularVelocity);
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('控制设置'),
          contentPadding: const EdgeInsets.fromLTRB(24, 12, 24, 8),
          content: SizedBox(
            width: 520,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '预设档位',
                  style: TextStyle(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 8),
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'slow', label: Text('慢速')),
                    ButtonSegment(value: 'standard', label: Text('标准')),
                    ButtonSegment(value: 'fast', label: Text('快速')),
                  ],
                  selected: <String>{
                    draftLinear <= 0.03
                        ? 'slow'
                        : draftLinear >= 0.16
                        ? 'fast'
                        : 'standard',
                  },
                  onSelectionChanged: (selected) => setDialogState(() {
                    switch (selected.first) {
                      case 'slow':
                        draftLinear = 0.03;
                        draftAngular = 0.2;
                      case 'fast':
                        draftLinear = AppConstants.maxLinearVelocity;
                        draftAngular = AppConstants.maxAngularVelocity;
                      default:
                        draftLinear = 0.08;
                        draftAngular = 0.3;
                    }
                  }),
                ),
                const SizedBox(height: 20),
                _SpeedSettingRow(
                  label: '线速度',
                  valueLabel: '${draftLinear.toStringAsFixed(2)} m/s',
                  value: draftLinear,
                  min: 0.01,
                  max: AppConstants.maxLinearVelocity,
                  divisions: 19,
                  onChanged: (value) =>
                      setDialogState(() => draftLinear = value),
                ),
                const SizedBox(height: 12),
                _SpeedSettingRow(
                  label: '角速度',
                  valueLabel: '${draftAngular.toStringAsFixed(1)} rad/s',
                  value: draftAngular,
                  min: 0.1,
                  max: AppConstants.maxAngularVelocity,
                  divisions: 3,
                  onChanged: (value) =>
                      setDialogState(() => draftAngular = value),
                ),
              ],
            ),
          ),
          actions: [
            OutlinedButton.icon(
              onPressed: () => setDialogState(() {
                draftLinear = 0.05;
                draftAngular = 0.3;
              }),
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('恢复默认'),
            ),
            FilledButton.icon(
              onPressed: () {
                onLinearSpeedChanged(draftLinear);
                onAngularSpeedChanged(draftAngular);
                Navigator.pop(dialogContext);
              },
              icon: const Icon(Icons.save_rounded),
              label: const Text('保存设置'),
            ),
          ],
        ),
      ),
    );
  }
}

class _PrinterControlPanel extends StatelessWidget {
  const _PrinterControlPanel({
    required this.enabled,
    required this.status,
    required this.onPrinterChanged,
    required this.onPrinterEnabledChanged,
    required this.onPrinterCommand,
    required this.onPrinterRawCommand,
  });

  final bool enabled;
  final Map<String, dynamic> status;
  final void Function(String printerName, bool active) onPrinterChanged;
  final void Function(String printerName, bool enabled) onPrinterEnabledChanged;
  final void Function(String printerName, String action) onPrinterCommand;
  final void Function(String printerName, String jsonData) onPrinterRawCommand;

  @override
  Widget build(BuildContext context) {
    final printers =
        status.keys
            .where((key) => key.startsWith('printer_') && status[key] is Map)
            .map((key) => key.substring('printer_'.length))
            .toList()
          ..sort();
    return _Panel(
      title: '喷码机控制',
      trailing: _StatusChip(
        text: enabled ? 'Ready' : 'Off',
        color: enabled ? const Color(0xff16a66a) : const Color(0xff64748b),
      ),
      child: Column(
        children: [
          if (printers.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 18),
              child: Text('未检测到已配置的喷码机'),
            ),
          for (var index = 0; index < printers.length; index++) ...[
            _PrinterControlRow(
              name: printers[index],
              status: Map<String, dynamic>.from(
                status['printer_${printers[index]}'] as Map,
              ),
              onActive: (active) => onPrinterChanged(printers[index], active),
              onEnabled: (value) =>
                  onPrinterEnabledChanged(printers[index], value),
              onCommand: (action) => onPrinterCommand(printers[index], action),
              onRawCommand: (jsonData) =>
                  onPrinterRawCommand(printers[index], jsonData),
            ),
            if (index != printers.length - 1) const Divider(height: 20),
          ],
        ],
      ),
    );
  }
}

class _SpeedSettingRow extends StatelessWidget {
  const _SpeedSettingRow({
    required this.label,
    required this.valueLabel,
    required this.value,
    required this.min,
    required this.max,
    required this.divisions,
    required this.onChanged,
  });

  final String label;
  final String valueLabel;
  final double value;
  final double min;
  final double max;
  final int divisions;
  final ValueChanged<double> onChanged;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: const TextStyle(fontWeight: FontWeight.w700),
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: const Color(0xffe8f5ef),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              valueLabel,
              style: const TextStyle(
                color: Color(0xff0f8a5f),
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
      Slider(
        value: value,
        min: min,
        max: max,
        divisions: divisions,
        onChanged: onChanged,
      ),
    ],
  );
}

class _PrinterControlRow extends StatelessWidget {
  const _PrinterControlRow({
    required this.name,
    required this.status,
    required this.onActive,
    required this.onEnabled,
    required this.onCommand,
    required this.onRawCommand,
  });

  final String name;
  final Map<String, dynamic> status;
  final ValueChanged<bool> onActive;
  final ValueChanged<bool> onEnabled;
  final ValueChanged<String> onCommand;
  final ValueChanged<String> onRawCommand;

  @override
  Widget build(BuildContext context) {
    final connected = status['connected'] == true;
    final enabled = status['enabled'] == true;
    final autoConnect = status['auto_connect'] == true;
    return Column(
      children: [
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          value: enabled,
          onChanged: connected ? onActive : null,
          title: Text('${name.toUpperCase()} 喷码机'),
          subtitle: Text(
            connected ? (status['status']?.toString() ?? '已连接') : '未连接',
          ),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          value: autoConnect,
          onChanged: onEnabled,
          title: const Text('自动连接'),
          subtitle: const Text('对应 printer/set_enabled'),
        ),
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: connected && enabled
                    ? () => onCommand('test_print')
                    : null,
                icon: const Icon(Icons.science_rounded),
                label: const Text('测试'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: connected ? () => onCommand('stop_print') : null,
                icon: const Icon(Icons.stop_circle_rounded),
                label: const Text('停止'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            onPressed: connected ? () => _showRawCommandDialog(context) : null,
            icon: const Icon(Icons.data_object_rounded),
            label: const Text('JSON 命令'),
          ),
        ),
      ],
    );
  }

  Future<void> _showRawCommandDialog(BuildContext context) async {
    final controller = TextEditingController(text: '{\n  \"EU2L\": {}\n}');
    final result = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('${name.toUpperCase()} JSON 命令'),
        content: SizedBox(
          width: 520,
          child: TextField(
            controller: controller,
            minLines: 6,
            maxLines: 12,
            decoration: const InputDecoration(border: OutlineInputBorder()),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () {
              try {
                final decoded = jsonDecode(controller.text);
                if (decoded is! Map) throw const FormatException();
                Navigator.pop(context, jsonEncode(decoded));
              } catch (_) {
                ScaffoldMessenger.of(
                  context,
                ).showSnackBar(const SnackBar(content: Text('请输入有效的 JSON 对象')));
              }
            },
            child: const Text('发送'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (result != null) onRawCommand(result);
  }
}
