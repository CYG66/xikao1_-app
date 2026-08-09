import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xline_car_app/main.dart';

void main() {
  testWidgets('底部仅保留首页、任务和设置', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    expect(find.text('首页'), findsOneWidget);
    expect(find.text('任务'), findsOneWidget);
    expect(find.text('设置'), findsOneWidget);
    expect(find.text('地图'), findsOneWidget);
    expect(find.text('控制'), findsOneWidget);
    expect(find.text('设备'), findsOneWidget);
    expect(find.byTooltip('智能助手'), findsOneWidget);
    expect(find.text('助手'), findsNothing);
  });

  testWidgets('智能助手入口可以打开对话页', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    await tester.tap(find.byTooltip('智能助手'));
    await tester.pumpAndSettle();

    expect(find.text('XLine Agent'), findsOneWidget);
    expect(find.text('输入任务或问题'), findsOneWidget);
    expect(find.textContaining('总计 0 tokens'), findsOneWidget);
  });

  testWidgets('设置页也能随时打开悬浮助手', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    await tester.tap(find.text('设置'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('智能助手'));
    await tester.pumpAndSettle();

    expect(find.text('智能助手'), findsOneWidget);
    expect(find.byTooltip('关闭助手'), findsOneWidget);
    expect(find.text('输入任务或问题'), findsOneWidget);
  });

  testWidgets('离线时不显示小车状态', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    expect(find.text('小车尚未连接'), findsOneWidget);
    expect(find.text('82%'), findsNothing);
    expect(find.text('0.34'), findsNothing);
  });

  testWidgets('离线时仍可进入设备管理并返回', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    await tester.tap(find.text('设备').first);
    await tester.pumpAndSettle();
    expect(find.text('设备管理'), findsWidgets);

    await tester.tap(find.byTooltip('返回首页'));
    await tester.pumpAndSettle();
    expect(find.text('快捷功能'), findsOneWidget);
  });

  testWidgets('设置页只展示真实 ROS2 接口', (tester) async {
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
    expect(find.text('OpenAI'), findsOneWidget);
    expect(find.text('gpt-5.1'), findsOneWidget);
    await tester.tap(find.byType(DropdownButtonFormField<String>).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('DeepSeek').last);
    await tester.pumpAndSettle();
    expect(find.text('deepseek-v4-pro'), findsOneWidget);
    expect(find.text('保存 AI 配置'), findsOneWidget);
    expect(find.text('线宽'), findsNothing);
  });
}
