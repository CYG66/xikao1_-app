import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:xline_car_app/auth_transport.dart';

/*
Offline App<->backend E2E client used by RELEASE-AUTH-E2E-01.

Run from the Flutter project root:
  dart run tool/auth_e2e_client.dart --base http://127.0.0.1:PORT \
    --valid TOKEN_FILE --readonly TOKEN_FILE --expired TOKEN_FILE \
    --expiry TOKEN_FILE --forged TOKEN_FILE [--mode status]

It prints one JSON object per case and exits non-zero if any required case
fails. Tokens are read from files and never printed.
*/

Map<String, String> _args(List<String> argv) {
  final result = <String, String>{};
  for (var index = 0; index < argv.length; index++) {
    final item = argv[index];
    if (!item.startsWith('--') || index + 1 >= argv.length) continue;
    result[item.substring(2)] = argv[index + 1];
    index++;
  }
  return result;
}

String _token(String path) => File(path).readAsStringSync().trim();

void _emit(String id, {required bool ok, Object? evidence}) {
  stdout.writeln(jsonEncode({
    'case': id,
    'ok': ok,
    'evidence': evidence,
    'at': DateTime.now().toUtc().toIso8601String(),
  }));
}

class Reader {
  Reader(this.socket) : iterator = StreamIterator<dynamic>(socket);

  final WebSocket socket;
  final StreamIterator<dynamic> iterator;

  Future<Map<String, dynamic>?> next(
      {Duration timeout = const Duration(seconds: 3)}) async {
    if (!await iterator.moveNext().timeout(timeout)) return null;
    final value = iterator.current;
    if (value is String) {
      final decoded = jsonDecode(value);
      if (decoded is Map) return Map<String, dynamic>.from(decoded);
    }
    return <String, dynamic>{'raw': value.toString()};
  }

  Future<Map<String, dynamic>?> waitFor(
    String op, {
    Duration timeout = const Duration(seconds: 3),
  }) async {
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      final message = await next(timeout: deadline.difference(DateTime.now()));
      if (message == null) return null;
      if (message['op'] == op) return message;
    }
    return null;
  }
}

Future<void> main(List<String> argv) async {
  final args = _args(argv);
  final base = Uri.parse(args['base']!);
  final host = base.host;
  final port = base.port;
  final mode = args['mode'] ?? 'full';
  final failures = <String>[];
  void mark(String id, bool ok, Object? evidence) {
    _emit(id, ok: ok, evidence: evidence);
    if (!ok) failures.add(id);
  }

  AuthTransport client(String token) =>
      AuthTransport(host: host, port: port, token: token);

  if (mode == 'status') {
    final old = client(_token(args['valid']!));
    try {
      await old.getJson('/api/status');
      mark('revoked_old_token_rejected', false, {'status': 200});
    } on AuthFailure catch (error) {
      mark(
        'revoked_old_token_rejected',
        error.kind == AuthFailureKind.invalidToken ||
            error.statusCode == 401 ||
            error.statusCode == 403,
        {'kind': error.kind.name, 'code': error.code, 'status': error.statusCode},
      );
    } finally {
      old.close();
    }
    if (failures.isNotEmpty) exitCode = 1;
    exit(exitCode);
  }

  final valid = client(_token(args['valid']!));
  final validToken = _token(args['valid']!);

  try {
    final status = await valid.getJson('/api/status');
    mark('http_status_authenticated', status.body['ok'] != false, {
      'status': status.statusCode,
      'bridge_mode': status.body['bridge_mode'],
      'control_owner': status.body['control_owner'],
    });
  } on AuthFailure catch (error) {
    mark('http_status_authenticated', false, {
      'kind': error.kind.name,
      'code': error.code,
    });
  }

  try {
    final first = await valid.postJson('/api/cmd_vel', {
      'client_id': 'app-e2e',
      'linear': 0,
      'angular': 0,
    });
    mark('http_request_id_accepted', first.statusCode == 200, {
      'status': first.statusCode,
      'request_id_length': first.requestId?.length,
    });
    try {
      await valid.postJson(
        '/api/cmd_vel',
        {'client_id': 'app-e2e', 'linear': 0, 'angular': 0},
        requestId: first.requestId,
      );
      mark('http_replay_rejected', false, {'status': 200});
    } on AuthFailure catch (error) {
      mark(
        'http_replay_rejected',
        error.kind == AuthFailureKind.replay,
        {'kind': error.kind.name, 'code': error.code, 'status': error.statusCode},
      );
    }
  } on AuthFailure catch (error) {
    mark('http_request_id_accepted', false, {
      'kind': error.kind.name,
      'code': error.code,
      'status': error.statusCode,
    });
  }

  try {
    final socket = await valid.connectWebSocket();
    final reader = Reader(socket);
    final status = await reader.next();
    mark('ws_handshake_and_status', status?['op'] == 'status', {
      'op': status?['op'],
    });
    socket.add(jsonEncode({'op': 'claim_control'}));
    final lease = await reader.waitFor('control_response');
    mark('ws_control_lease', lease?['ok'] == true, {
      'ok': lease?['ok'],
      'message': lease?['message'],
      'owner': lease?['owner'],
    });
    socket.add(jsonEncode({
      'op': 'publish',
      'topic': '/tablet_cmd_vel',
      'type': 'geometry_msgs/msg/Twist',
      'msg': {
        'linear': {'x': 0.0, 'y': 0.0, 'z': 0.0},
        'angular': {'x': 0.0, 'y': 0.0, 'z': 0.0},
      },
    }));
    // Successful drive packets are intentionally not acknowledged by the
    // backend (to avoid a stale-ack queue at joystick rate).  A failed publish
    // still sends ok:false immediately, so assert that the next heartbeat
    // arrives without any rejected `published` frame in between.
    socket.add(jsonEncode({'op': 'control_heartbeat'}));
    var rejectedPublish = false;
    Map<String, dynamic>? heartbeat;
    final publishDeadline = DateTime.now().add(const Duration(seconds: 3));
    while (DateTime.now().isBefore(publishDeadline)) {
      final message = await reader.next(
        timeout: publishDeadline.difference(DateTime.now()),
      );
      if (message == null) break;
      if (message['op'] == 'published' && message['ok'] == false) {
        rejectedPublish = true;
      }
      if (message['op'] == 'control_heartbeat_response') {
        heartbeat = message;
        break;
      }
    }
    mark(
      'ws_zero_velocity_protocol',
      !rejectedPublish && heartbeat?['ok'] == true,
      {
        'ack': 'none-on-success',
        'rejected': rejectedPublish,
        'heartbeat_ok': heartbeat?['ok'],
      },
    );
    socket.add(jsonEncode({'op': 'control_heartbeat'}));
    final heartbeatConfirm = await reader.waitFor('control_heartbeat_response');
    mark('ws_control_heartbeat', heartbeatConfirm?['ok'] == true, {
      'ok': heartbeatConfirm?['ok'],
    });
    socket.add(jsonEncode({'op': 'release_control'}));
    final released = await reader.waitFor('control_response');
    mark('ws_release_control', released?['ok'] == true && released?['owner'] == null, {
      'ok': released?['ok'],
      'owner': released?['owner'],
    });
    await socket.close(1000, 'e2e done');
  } on AuthFailure catch (error) {
    mark('ws_handshake_and_status', false, {
      'kind': error.kind.name,
      'code': error.code,
      'status': error.statusCode,
    });
  } catch (error) {
    mark('ws_handshake_and_status', false, {'error': error.toString()});
  } finally {
    valid.close();
  }

  // No token: a real handshake with no Authorization header must be rejected.
  try {
    final socket = await WebSocket.connect(
      'ws://$host:$port/ws/rosbridge',
    ).timeout(const Duration(seconds: 3));
    await socket.close(1000, 'unexpected');
    mark('ws_missing_token_rejected', false, {'accepted': true});
  } catch (error) {
    final status = error is WebSocketException ? error.httpStatusCode : null;
    mark('ws_missing_token_rejected', status == 401 || status == 403, {
      'http_status': status,
    });
  }

  // Forged signature: App preflight HTTP should map to invalid token.
  final forged = client(_token(args['forged']!));
  try {
    await forged.getJson('/api/status');
    mark('http_forged_token_rejected', false, {'status': 200});
  } on AuthFailure catch (error) {
    mark(
      'http_forged_token_rejected',
      error.kind == AuthFailureKind.invalidToken,
      {'kind': error.kind.name, 'code': error.code, 'status': error.statusCode},
    );
  } finally {
    forged.close();
  }

  // Read-only token has read but not control; WS handshake requires control.
  final readonly = client(_token(args['readonly']!));
  try {
    await readonly.connectWebSocket();
    mark('ws_readonly_control_rejected', false, {'accepted': true});
  } on AuthFailure catch (error) {
    mark(
      'ws_readonly_control_rejected',
      error.kind == AuthFailureKind.forbidden ||
          error.kind == AuthFailureKind.invalidToken,
      {'kind': error.kind.name, 'status': error.statusCode},
    );
  } finally {
    readonly.close();
  }

  // Expired-before-connect token must be rejected by HTTP.
  final expired = client(_token(args['expired']!));
  try {
    await expired.getJson('/api/status');
    mark('http_expired_token_rejected', false, {'status': 200});
  } on AuthFailure catch (error) {
    mark(
      'http_expired_token_rejected',
      error.kind == AuthFailureKind.expired,
      {'kind': error.kind.name, 'code': error.code, 'status': error.statusCode},
    );
  } finally {
    expired.close();
  }

  // A token that expires while the socket is live: server closes 1008 and
  // releases the control lease; the App gate is then closed by fromClose().
  final expiry = client(_token(args['expiry']!));
  try {
    final socket = await expiry.connectWebSocket();
    final reader = Reader(socket);
    final status = await reader.next();
    mark('ws_expiry_connect', status?['op'] == 'status', {'op': status?['op']});
    socket.add(jsonEncode({'op': 'claim_control'}));
    final lease = await reader.waitFor('control_response');
    mark('ws_expiry_lease_claimed', lease?['ok'] == true, {'owner': lease?['owner']});
    await Future<void>.delayed(const Duration(seconds: 9));
    socket.add(jsonEncode({'op': 'control_heartbeat'}));
    var sawDataUntilClose = false;
    final closeDeadline = DateTime.now().add(const Duration(seconds: 6));
    while (DateTime.now().isBefore(closeDeadline)) {
      final message = await reader.next(
        timeout: closeDeadline.difference(DateTime.now()),
      );
      if (message == null) break;
      sawDataUntilClose = true;
    }
    await Future<void>.delayed(const Duration(milliseconds: 150));
    final closeFailure = AuthTransport.fromClose(socket.closeCode, socket.closeReason);
    mark(
      'ws_session_expiry_closes_1008',
      socket.closeCode == 1008 && closeFailure?.kind == AuthFailureKind.expired,
      {
        'close_code': socket.closeCode,
        'close_reason': socket.closeReason,
        'app_gate': closeFailure?.kind.name,
        'saw_status_before_close': sawDataUntilClose,
      },
    );
    final after = await expiry.getJson('/api/status').then<Object?>(
      (value) => value.body,
      onError: (Object error) => error is AuthFailure
          ? {'code': error.code, 'kind': error.kind.name}
          : {'error': error.toString()},
    );
    mark('expired_token_http_rejected_after_session', after is Map && after['code'] == 'token_expired', {
      'response': after,
    });
  } on AuthFailure catch (error) {
    mark('ws_expiry_connect', false, {
      'kind': error.kind.name,
      'code': error.code,
      'status': error.statusCode,
    });
  } catch (error) {
    mark('ws_expiry_connect', false, {'error': error.toString()});
  } finally {
    expiry.close();
  }

  // Lease release evidence: a fresh read-only status must not show the
  // expired subject as control owner.
  final probe = client(validToken);
  try {
    final status = await probe.getJson('/api/status');
    mark('session_expiry_releases_control', status.body['control_owner'] == null, {
      'control_owner': status.body['control_owner'],
    });
  } on AuthFailure catch (error) {
    mark('session_expiry_releases_control', false, {
      'kind': error.kind.name,
      'code': error.code,
    });
  } finally {
    probe.close();
  }

  if (failures.isNotEmpty) {
    stderr.writeln('failed cases: ${failures.join(', ')}');
    exitCode = 1;
  }
  exit(exitCode);
}
