import 'package:flutter_test/flutter_test.dart';
import 'package:xline_car_app/main.dart';

void main() {
  testWidgets('opens xline rover dashboard', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    expect(find.text('XLine 划线小车'), findsOneWidget);
    expect(find.text('等待连接'), findsOneWidget);
    expect(find.text('设备管理'), findsOneWidget);
  });
}
