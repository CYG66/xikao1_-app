import 'dart:async';

/// Control-lease states mirroring the backend's 3-second lease contract.
enum ControlLeaseState { idle, claiming, granted, locked, released }

/// Small, testable state machine shared by the real Flutter page.
///
/// The App must never treat "WebSocket connected" as "control granted":
/// motion and mission commands are only allowed after the backend returns
/// `control_response {ok: true}`.  Heartbeats must be sent more often than the
/// backend's 3-second lease window, and a missing acknowledgement closes the
/// local control gate.
class ControlLeaseManager {
  ControlLeaseManager({
    required this.send,
    this.heartbeatInterval = const Duration(milliseconds: 1500),
    this.ackTimeout = const Duration(milliseconds: 2500),
    this.claimTimeout = const Duration(milliseconds: 2500),
    this.onLock,
    DateTime Function()? clock,
  }) : _clock = clock ?? DateTime.now;

  /// Sends lease frames only; callers must not route this through the normal
  /// control gate or the claim itself would be blocked.
  final void Function(Map<String, Object?> payload) send;

  /// Must stay below the backend's 3.0-second lease expiry.
  final Duration heartbeatInterval;

  /// Local watchdog: no heartbeat acknowledgement for this long loses control.
  final Duration ackTimeout;

  /// A claim without a backend response must not leave the UI indefinitely
  /// waiting in the "claiming" state.
  final Duration claimTimeout;

  /// Invoked once when a granted or pending lease becomes invalid, so the page
  /// can close the socket and stop telemetry/control traffic.
  final void Function(String reason)? onLock;

  final DateTime Function() _clock;

  ControlLeaseState _state = ControlLeaseState.idle;
  String? _reason;
  DateTime? _lastAck;
  Timer? _claimTimer;

  ControlLeaseState get state => _state;
  String? get reason => _reason;
  bool get granted => _state == ControlLeaseState.granted;

  void reset() {
    _claimTimer?.cancel();
    _claimTimer = null;
    _state = ControlLeaseState.idle;
    _reason = null;
    _lastAck = null;
  }

  void startClaim() {
    if (_state == ControlLeaseState.claiming ||
        _state == ControlLeaseState.granted) {
      return;
    }
    _claimTimer?.cancel();
    _state = ControlLeaseState.claiming;
    _reason = null;
    _lastAck = null;
    try {
      send(const {'op': 'claim_control'});
    } catch (error) {
      lock('控制权申请发送失败：$error');
      return;
    }
    _claimTimer = Timer(claimTimeout, () {
      if (_state == ControlLeaseState.claiming) {
        lock('控制权申请超时，后端未确认租约');
      }
    });
  }

  /// Applies one decoded backend frame.  Returns true when the caller must
  /// immediately close the control session.
  bool handleMessage(Map<String, dynamic> payload) {
    final op = payload['op'];
    if (op == 'control_response') {
      if (_state == ControlLeaseState.claiming) {
        _claimTimer?.cancel();
        _claimTimer = null;
        if (payload['ok'] == true) {
          _state = ControlLeaseState.granted;
          _reason = null;
          _lastAck = _clock();
        } else {
          lock('控制权申请被拒绝：${payload['message'] ?? '后端未授予租约'}');
        }
      }
      return false;
    }

    if (op == 'control_heartbeat_response') {
      if (_state != ControlLeaseState.granted) return false;
      if (payload['ok'] == true) {
        _lastAck = _clock();
      } else {
        lock('控制心跳失败，控制权已丢失');
        return true;
      }
      return false;
    }

    final message = payload['message']?.toString() ?? '';
    if (payload['ok'] == false && message.contains('control lease required')) {
      lock('控制租约已丢失，请重新连接');
      return true;
    }
    return false;
  }

  /// Sends one heartbeat, or locks the gate if the last acknowledgement is
  /// older than [ackTimeout].  Returns false when control is no longer valid.
  bool heartbeat() {
    if (_state != ControlLeaseState.granted) return false;
    final now = _clock();
    final last = _lastAck;
    if (last != null && now.difference(last) > ackTimeout) {
      lock('控制心跳超时，控制权已丢失');
      return false;
    }
    try {
      send(const {'op': 'control_heartbeat'});
    } catch (error) {
      lock('控制心跳发送失败，控制权已丢失');
      return false;
    }
    return true;
  }

  void lock(String reason) {
    if (_state == ControlLeaseState.locked ||
        _state == ControlLeaseState.released) {
      return;
    }
    _claimTimer?.cancel();
    _claimTimer = null;
    _state = ControlLeaseState.locked;
    _reason = reason;
    onLock?.call(reason);
  }

  /// Normal disconnect: ask the server to release before closing.
  void release() {
    if (_state == ControlLeaseState.granted ||
        _state == ControlLeaseState.claiming) {
      try {
        send(const {'op': 'release_control'});
      } catch (_) {
        // A broken socket cannot carry the release frame; closing the socket
        // still trips the backend's fail-safe stop.
      }
    }
    _claimTimer?.cancel();
    _claimTimer = null;
    _state = ControlLeaseState.released;
    _reason = null;
    _lastAck = null;
  }

  void dispose() {
    _claimTimer?.cancel();
    _claimTimer = null;
  }
}
