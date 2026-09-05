/// 一次连接结果的不可变数据快照。
///
/// [connected] 表示是否连接成功，[message] 用于向界面展示原因。
/// 当前连接主状态仍在 `main.dart` 中，后续拆分状态管理时可扩展此文件。
class ConnectionSnapshot {
  const ConnectionSnapshot({required this.connected, required this.message});

  final bool connected;
  final String message;
}
