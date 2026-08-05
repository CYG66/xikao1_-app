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
}
