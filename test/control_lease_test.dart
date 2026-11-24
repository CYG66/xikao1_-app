import 'package:flutter_test/flutter_test.dart';
import 'package:xline_car_app/control_lease.dart';
import 'package:xline_car_app/main.dart';

void main() {
  late DateTime now;
  late List<Map<String, Object?>> sent;
  late ControlLeaseManager lease;

  setUp(() {
    now = DateTime.utc(2026, 1, 1, 12);
    sent = [];
    lease = ControlLeaseManager(
      send: sent.add,
      clock: () => now,
      heartbeatInterval: const Duration(milliseconds: 1500),
      ackTimeout: const Duration(milliseconds: 2500),
    );
  });

  test('motion stays locked while the claim is pending', () {
    expect(
      controlCommandsAllowed(BridgeState.connected, null, lease: lease.state),
      isFalse,
    );

    lease.startClaim();
    expect(sent, [
      {'op': 'claim_control'},
    ]);
    expect(lease.state, ControlLeaseState.claiming);
    expect(
      controlCommandsAllowed(BridgeState.connected, null, lease: lease.state),
      isFalse,
    );

    lease.handleMessage({'op': 'control_response', 'ok': true, 'owner': 'op1'});
    expect(lease.granted, isTrue);
    expect(
      controlCommandsAllowed(BridgeState.connected, null, lease: lease.state),
      isTrue,
    );
  });

  test('rejected claim locks the real App gate', () {
    lease.startClaim();
    lease.handleMessage({
      'op': 'control_response',
      'ok': false,
      'message': 'control owner conflict',
    });

    expect(lease.state, ControlLeaseState.locked);
    expect(lease.reason, contains('控制权申请被拒绝'));
    expect(
      controlCommandsAllowed(BridgeState.connected, null, lease: lease.state),
      isFalse,
    );
  });

  test('heartbeat interval is below the backend 3 second lease', () {
    lease.startClaim();
    lease.handleMessage({'op': 'control_response', 'ok': true});

    expect(lease.heartbeatInterval.inMilliseconds, lessThan(3000));
    expect(lease.heartbeat(), isTrue);
    expect(sent.last, {'op': 'control_heartbeat'});

    now = now.add(const Duration(milliseconds: 1400));
    lease.handleMessage({'op': 'control_heartbeat_response', 'ok': true});
    expect(lease.heartbeat(), isTrue);
    expect(sent.last, {'op': 'control_heartbeat'});
  });

  test('missing heartbeat acknowledgement locks control', () {
    lease.startClaim();
    lease.handleMessage({'op': 'control_response', 'ok': true});

    now = now.add(const Duration(milliseconds: 2600));
    expect(lease.heartbeat(), isFalse);
    expect(lease.state, ControlLeaseState.locked);
    expect(lease.reason, contains('心跳超时'));
    expect(sent.where((frame) => frame['op'] == 'control_heartbeat'), isEmpty);
  });

  test('heartbeat rejection and lease-required command lock control', () {
    lease.startClaim();
    lease.handleMessage({'op': 'control_response', 'ok': true});
    expect(
      lease.handleMessage({'op': 'control_heartbeat_response', 'ok': false}),
      isTrue,
    );
    expect(lease.state, ControlLeaseState.locked);

    lease.reset();
    lease.startClaim();
    lease.handleMessage({'op': 'control_response', 'ok': true});
    expect(
      lease.handleMessage({
        'op': 'publish_response',
        'ok': false,
        'message': 'control lease required',
      }),
      isTrue,
    );
    expect(lease.state, ControlLeaseState.locked);
    expect(lease.reason, contains('租约'));
  });

  test('normal disconnect releases the lease', () {
    lease.startClaim();
    lease.handleMessage({'op': 'control_response', 'ok': true});
    lease.release();

    expect(sent.last, {'op': 'release_control'});
    expect(lease.state, ControlLeaseState.released);
    expect(lease.granted, isFalse);
    lease.lock('too late');
    expect(lease.state, ControlLeaseState.released);
  });

  test('unanswered claim times out and notifies the page', () async {
    final reasons = <String>[];
    final shortLease = ControlLeaseManager(
      send: sent.add,
      clock: () => now,
      claimTimeout: const Duration(milliseconds: 20),
      onLock: reasons.add,
    );
    shortLease.startClaim();
    expect(shortLease.state, ControlLeaseState.claiming);

    await Future<void>.delayed(const Duration(milliseconds: 40));
    expect(shortLease.state, ControlLeaseState.locked);
    expect(shortLease.reason, contains('申请超时'));
    expect(reasons, hasLength(1));
    shortLease.dispose();
  });
}
