import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xline_car_app/main.dart';

void main() {
  testWidgets('opens xline rover dashboard', (tester) async {
    await tester.pumpWidget(const XLineCarApp());

    expect(find.text('XLine 划线小车'), findsOneWidget);
    expect(find.text('状态概览'), findsOneWidget);
    expect(find.text('添加设备'), findsOneWidget);
  });

  testWidgets('auth failure banner is visible and locks the control gate',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: AuthStatusBanner(message: '访问令牌已过期，控制连接已关闭'),
        ),
      ),
    );

    expect(find.byKey(const ValueKey('auth-status-banner')), findsOneWidget);
    expect(find.text('访问令牌已过期，控制连接已关闭'), findsOneWidget);
    expect(find.text('控制已锁定'), findsOneWidget);
    expect(
      controlCommandsAllowed(BridgeState.connected, '访问令牌已过期'),
      isFalse,
    );
    expect(controlCommandsAllowed(BridgeState.connected, null), isTrue);
    expect(controlCommandsAllowed(BridgeState.disconnected, null), isFalse);
  });

  testWidgets('device page exposes an obscured token input', (tester) async {
    await tester.pumpWidget(const XLineCarApp());
    await tester.tap(find.text('设备'));
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('auth-token-field')), findsOneWidget);
    final field = tester.widget<TextField>(
      find.byKey(const ValueKey('auth-token-field')),
    );
    expect(field.obscureText, isTrue);
    expect(find.text('认证并连接'), findsOneWidget);
  });
}
