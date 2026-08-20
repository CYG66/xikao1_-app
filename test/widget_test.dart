import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xline_car_app/main.dart';
import 'package:xline_car_app/viewmodels/rover_device.dart';

void main() {
  test('设备配置可以序列化并恢复', () {
    const device = RoverDevice(
      name: 'XLine-Car-01',
      ip: '192.168.0.100',
      port: 8000,
      domainId: 0,
      type: 'FastAPI Backend',
      connected: true,
    );

    final restored = RoverDevice.fromJson(device.toJson(), connected: true);

    expect(restored.name, device.name);
    expect(restored.ip, device.ip);
    expect(restored.port, device.port);
    expect(restored.domainId, device.domainId);
    expect(restored.type, device.type);
    expect(restored.connected, isTrue);
  });

  testWidgets('底部仅保留首页、任务和设置', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    expect(find.text('首页'), findsOneWidget);
    expect(find.text('任务'), findsOneWidget);
    expect(find.text('设置'), findsOneWidget);
    expect(find.byType(NavigationDestination), findsNWidgets(3));
    expect(find.byTooltip('智能助手'), findsOneWidget);
    expect(find.byTooltip('紧急停车'), findsNothing);
    expect(find.byTooltip('解除急停'), findsNothing);
    expect(find.text('助手'), findsNothing);
  });

  testWidgets('智能助手入口可以打开对话页', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    await tester.tap(find.byTooltip('智能助手'));
    await tester.pumpAndSettle();

    expect(find.text('智能助手'), findsOneWidget);
    expect(find.text('XLine Agent'), findsOneWidget);
    expect(find.byTooltip('关闭助手'), findsOneWidget);
  });

  testWidgets('设置页也能随时打开悬浮助手', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('智能助手'));
    await tester.pumpAndSettle();

    expect(find.text('智能助手'), findsOneWidget);
    expect(find.byTooltip('关闭助手'), findsOneWidget);
    expect(find.text('XLine Agent'), findsOneWidget);
  });

  testWidgets('离线时不显示虚构的小车状态', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    expect(find.text('小车尚未连接'), findsOneWidget);
    expect(find.text('82%'), findsNothing);
    expect(find.text('0.34'), findsNothing);
  });

  testWidgets('离线时仍可进入设备管理并返回', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    await tester.tap(find.text('设备管理'));
    await tester.pumpAndSettle();
    expect(find.text('设备管理'), findsWidgets);

    await tester.tap(find.byTooltip('返回首页'));
    await tester.pumpAndSettle();
    expect(find.text('快捷操作'), findsOneWidget);
  });

  testWidgets('设置页只展示真实 ROS2 接口和当前 AI 模型', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();

    expect(find.text('/tablet_cmd_vel'), findsOneWidget);
    expect(find.text('/plan_path'), findsOneWidget);
    expect(find.text('/execute_plan'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('AI 服务'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('AI 服务'), findsOneWidget);
    expect(find.text('DeepSeek'), findsOneWidget);
    expect(find.text('deepseek-chat'), findsOneWidget);
    final modelDropdown = find.byType(DropdownButtonFormField<String>).last;
    await tester.ensureVisible(modelDropdown);
    await tester.pumpAndSettle();
    await tester.tap(modelDropdown);
    await tester.pumpAndSettle();
    expect(find.text('deepseek-v4-pro'), findsOneWidget);
    expect(find.text('保存 AI 配置'), findsOneWidget);
    expect(find.text('线宽'), findsNothing);
  });
}
