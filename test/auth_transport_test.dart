import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xline_car_app/auth_transport.dart';

void main() {
  late HttpServer server;
  late List<Map<String, String>> requests;
  late List<String> requestIds;
  late String baseHost;
  late int basePort;

  setUp(() async {
    requests = <Map<String, String>>[];
    requestIds = <String>[];
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    baseHost = InternetAddress.loopbackIPv4.address;
    basePort = server.port;
    server.listen((HttpRequest request) async {
      final headers = <String, String>{};
      request.headers.forEach((name, values) {
        headers[name.toLowerCase()] = values.join(',');
      });
      requests.add(headers);
      if (request.uri.path == '/api/status') {
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'ok': true, 'bridge_mode': 'test'}));
        await request.response.close();
        return;
      }
      if (request.uri.path == '/api/cmd_vel') {
        final body = await utf8.decoder.bind(request).join();
        if (body.isEmpty) {
          request.response.statusCode = 400;
          await request.response.close();
          return;
        }
        final id = headers['x-xline-request-id'];
        if (id == null || id.isEmpty) {
          request.response.statusCode = 400;
          await request.response.close();
          return;
        }
        if (requestIds.contains(id)) {
          request.response.statusCode = 409;
          request.response.headers.contentType = ContentType.json;
          request.response.write(
            jsonEncode({
              'ok': false,
              'code': 'duplicate_request_id',
              'detail': 'duplicate request id',
            }),
          );
          await request.response.close();
          return;
        }
        requestIds.add(id);
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'ok': true}));
        await request.response.close();
        return;
      }
      if (WebSocketTransformer.isUpgradeRequest(request)) {
        final auth = headers['authorization'] ?? '';
        if (auth != 'Bearer valid-token') {
          request.response.statusCode = auth.isEmpty ? 401 : 403;
          await request.response.close();
          return;
        }
        final socket = await WebSocketTransformer.upgrade(request);
        socket.add(jsonEncode({'op': 'status', 'ok': true}));
        socket.listen((data) {
          socket.add(jsonEncode({'op': 'control_response', 'ok': true}));
        });
        return;
      }
      request.response.statusCode = 404;
      await request.response.close();
    });
  });

  tearDown(() async {
    await server.close(force: true);
  });

  AuthTransport transport(String token) => AuthTransport(
    host: baseHost,
    port: basePort,
    token: token,
    secure: false,
  );

  test('secure transport is the default and uses https/wss schemes', () {
    final client = AuthTransport(
      host: '192.168.31.42',
      port: 8000,
      token: 'valid-token',
    );
    addTearDown(client.close);
    expect(client.httpBase.scheme, 'https');
    expect(client.websocketUri.scheme, 'wss');
    expect(client.websocketUri.host, '192.168.31.42');
    expect(client.websocketUri.path, '/ws/rosbridge');
  });

  test(
    'plaintext to a non-loopback host is rejected before network I/O',
    () async {
      final client = AuthTransport(
        host: '192.168.31.42',
        port: 8000,
        token: 'valid-token',
        secure: false,
      );
      addTearDown(client.close);
      expect(
        () => client.getJson('/api/status'),
        throwsA(
          isA<AuthFailure>().having(
            (failure) => failure.kind,
            'kind',
            AuthFailureKind.insecureTransport,
          ),
        ),
      );
      expect(requests, isEmpty);
      expect(client.httpBase.scheme, 'http');
      await expectLater(
        client.connectWebSocket(),
        throwsA(
          isA<AuthFailure>().having(
            (failure) => failure.kind,
            'kind',
            AuthFailureKind.insecureTransport,
          ),
        ),
      );
    },
  );

  test('local loopback plaintext is allowed for an offline drill', () {
    for (final host in ['127.0.0.1', 'localhost', '::1']) {
      final client = AuthTransport(
        host: host,
        port: 8000,
        token: 'valid-token',
        secure: false,
      );
      addTearDown(client.close);
      expect(() => client.validateTransport(), returnsNormally);
    }
  });

  test('HTTP GET sends bearer token and never puts it in the URL', () async {
    final client = transport('valid-token');
    addTearDown(client.close);
    final response = await client.getJson('/api/status');
    expect(response.statusCode, 200);
    expect(response.body['ok'], isTrue);
    expect(requests.single['authorization'], 'Bearer valid-token');
    expect(requests.single['host'], contains('127.0.0.1'));
  });

  test(
    'state-changing POST sends unique request ids and rejects replay',
    () async {
      final client = transport('valid-token');
      addTearDown(client.close);
      final first = await client.postJson('/api/cmd_vel', {
        'linear': 0,
        'angular': 0,
      });
      expect(first.statusCode, 200);
      expect(first.requestId, isNotNull);
      expect(first.requestId!.length, greaterThanOrEqualTo(8));
      expect(first.requestId, matches(RegExp(r'^[A-Za-z0-9._:-]{8,128}$')));

      final second = await client.postJson('/api/cmd_vel', {
        'linear': 0,
        'angular': 0,
      });
      expect(second.requestId, isNot(equals(first.requestId)));

      expect(
        () => client.postJson('/api/cmd_vel', {
          'linear': 0,
          'angular': 0,
        }, requestId: first.requestId),
        throwsA(
          isA<AuthFailure>().having(
            (failure) => failure.kind,
            'kind',
            AuthFailureKind.replay,
          ),
        ),
      );
    },
  );

  test('missing token fails before any network request', () async {
    final client = transport('');
    addTearDown(client.close);
    expect(
      () => client.getJson('/api/status'),
      throwsA(
        isA<AuthFailure>().having(
          (failure) => failure.kind,
          'kind',
          AuthFailureKind.missingToken,
        ),
      ),
    );
    expect(requests, isEmpty);
  });

  test('WebSocket handshake carries the Authorization header', () async {
    final client = transport('valid-token');
    addTearDown(client.close);
    final socket = await client.connectWebSocket();
    addTearDown(() => socket.close());
    final first = await socket.first.timeout(const Duration(seconds: 2));
    final payload = jsonDecode(first as String) as Map<String, dynamic>;
    expect(payload['op'], 'status');
    expect(requests.last['authorization'], 'Bearer valid-token');
    socket.add(jsonEncode({'op': 'claim_control'}));
  });

  test('forged WebSocket token is rejected by the server', () async {
    final client = transport('forged-token');
    addTearDown(client.close);
    await expectLater(
      client.connectWebSocket(),
      throwsA(
        isA<AuthFailure>().having(
          (failure) => failure.kind,
          'kind',
          AuthFailureKind.invalidToken,
        ),
      ),
    );
  });

  test('close code 1008 maps token expiry and forbidden scope', () {
    expect(
      AuthTransport.fromClose(1008, 'token expired')!.kind,
      AuthFailureKind.expired,
    );
    expect(
      AuthTransport.fromClose(1008, 'forbidden scope')!.kind,
      AuthFailureKind.forbidden,
    );
    expect(AuthTransport.fromClose(1000, 'normal'), isNull);
  });

  test('WebSocket auth errors stop the App gate', () {
    final expired = AuthTransport.fromWsMessage({
      'ok': false,
      'code': 'forbidden_scope',
      'message': 'operator token lacks printer scope',
    });
    expect(expired?.kind, AuthFailureKind.forbidden);
    expect(
      AuthTransport.fromWsMessage({
        'ok': false,
        'message': 'control lease required',
      }),
      isNull,
    );
  });
}
