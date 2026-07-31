import 'package:flutter_test/flutter_test.dart';
import 'package:xline_car_app/main.dart';

void main() {
  testWidgets('opens xline rover dashboard', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    expect(find.text('XLine 划线小车'), findsOneWidget);
    expect(find.text('状态概览'), findsOneWidget);
    expect(find.text('添加设备'), findsOneWidget);
  });
}
