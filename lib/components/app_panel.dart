import 'package:flutter/material.dart';

/// 通用内容面板，统一提供背景、边框、圆角和内边距。
///
/// 页面拆分后可优先复用该组件，不要在每个页面重复编写卡片样式。
class AppPanel extends StatelessWidget {
  const AppPanel({
    required this.child,
    this.padding = const EdgeInsets.all(16),
    super.key,
  });

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: padding,
      decoration: BoxDecoration(
        color: const Color(0xff111827),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0xff273449)),
      ),
      child: child,
    );
  }
}
