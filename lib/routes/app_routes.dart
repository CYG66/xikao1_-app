/// 页面路由名称表。
///
/// 当前主界面使用底部导航和内部状态切换，这些常量是为后续
/// 拆分成 Navigator 命名路由保留的。新增独立页面时可在此增加路径。
class AppRoutes {
  const AppRoutes._();

  static const dashboard = '/';
  static const map = '/map';
  static const control = '/control';
  static const mission = '/mission';
  static const devices = '/devices';
  static const settings = '/settings';
}
