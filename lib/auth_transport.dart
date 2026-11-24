import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

/// Authentication failure categories surfaced by the App.
enum AuthFailureKind {
  missingToken,
  invalidToken,
  forbidden,
  expired,
  replay,
  disconnected,
  network,
}

class AuthFailure implements Exception {
  const AuthFailure({
    required this.kind,
    required this.message,
    this.code = 'auth_failed',
    this.statusCode,
  });

  final AuthFailureKind kind;
  final String message;
  final String code;
  final int? statusCode;

  bool get isAuthFailure =>
      kind == AuthFailureKind.missingToken ||
      kind == AuthFailureKind.invalidToken ||
      kind == AuthFailureKind.forbidden ||
      kind == AuthFailureKind.expired;

  @override
  String toString() => message;
}

class AuthHttpResponse {
  const AuthHttpResponse({
    required this.statusCode,
    required this.body,
    this.requestId,
  });

  final int statusCode;
  final Map<String, dynamic> body;
  final String? requestId;

  bool get ok => statusCode >= 200 && statusCode < 300;
}

/// HTTP/WebSocket transport shared by the App UI and the offline E2E harness.
///
/// Tokens are passed in the request header for HTTP and in the WebSocket
/// handshake header.  The token is never placed in a URL, query string or log.
class AuthTransport {
  AuthTransport({
    required String host,
    required this.port,
    required String token,
    HttpClient? httpClient,
  })  : host = host.trim(),
        token = token.trim(),
        _http = httpClient ?? HttpClient() {
    _http.connectionTimeout = const Duration(seconds: 4);
    _http.idleTimeout = const Duration(seconds: 4);
  }

  final String host;
  final int port;
  final String token;
  final HttpClient _http;
  final Random _random = Random.secure();

  Uri get httpBase => Uri(scheme: 'http', host: host, port: port);
  Uri get websocketUri =>
      Uri(scheme: 'ws', host: host, port: port, path: '/ws/rosbridge');

  bool get hasToken => token.isNotEmpty;

  String newRequestId() {
    final bytes = List<int>.generate(16, (_) => _random.nextInt(256));
    final suffix = bytes.map((value) => value.toRadixString(16).padLeft(2, '0')).join();
    return 'xline-app-$suffix';
  }

  Map<String, String> get _authHeaders {
    if (!hasToken) {
      throw const AuthFailure(
        kind: AuthFailureKind.missingToken,
        message: '未配置访问令牌',
        code: 'missing_token',
      );
    }
    return {'Authorization': 'Bearer $token'};
  }

  Future<AuthHttpResponse> getJson(String path) async {
    final client = await _open('GET', path);
    final response = await client.close();
    return _readResponse(response);
  }

  Future<AuthHttpResponse> postJson(
    String path,
    Map<String, Object?> payload, {
    String? requestId,
  }) async {
    final id = requestId ?? newRequestId();
    final client = await _open('POST', path, requestId: id);
    client.write(jsonEncode(payload));
    final response = await client.close();
    return _readResponse(response, requestId: id);
  }

  Future<HttpClientRequest> _open(
    String method,
    String path, {
    String? requestId,
  }) async {
    if (!hasToken) {
      throw const AuthFailure(
        kind: AuthFailureKind.missingToken,
        message: '未配置访问令牌',
        code: 'missing_token',
      );
    }
    final uri = httpBase.resolve(path);
    final request = await _http.openUrl(method, uri);
    request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
    if (requestId != null) {
      request.headers.set('X-XLine-Request-Id', requestId);
    }
    request.headers.contentType = ContentType.json;
    return request;
  }

  Future<AuthHttpResponse> _readResponse(
    HttpClientResponse response, {
    String? requestId,
  }) async {
    final text = await utf8.decoder.bind(response).join();
    Map<String, dynamic> body = <String, dynamic>{};
    if (text.isNotEmpty) {
      try {
        final decoded = jsonDecode(text);
        if (decoded is Map<String, dynamic>) body = decoded;
        if (decoded is Map) body = Map<String, dynamic>.from(decoded);
      } catch (_) {
        body = <String, dynamic>{'raw': text};
      }
    }
    final result = AuthHttpResponse(
      statusCode: response.statusCode,
      body: body,
      requestId: requestId,
    );
    if (!result.ok) {
      throw _failureFromResponse(result);
    }
    return result;
  }

  Future<WebSocket> connectWebSocket({
    Duration timeout = const Duration(seconds: 4),
  }) async {
    final headers = _authHeaders;
    try {
      return await WebSocket.connect(
        websocketUri.toString(),
        headers: headers,
      ).timeout(timeout);
    } catch (error) {
      throw describeError(error);
    }
  }

  void close() => _http.close(force: true);

  AuthFailure _failureFromResponse(AuthHttpResponse response) {
    final code = str(response.body['code']);
    final detail = str(response.body['detail'] ?? response.body['message'] ?? 'HTTP ${response.statusCode}');
    final kind = switch (response.statusCode) {
      401 => code == 'token_expired'
          ? AuthFailureKind.expired
          : AuthFailureKind.invalidToken,
      403 => AuthFailureKind.forbidden,
      409 => AuthFailureKind.replay,
      _ => code == 'token_expired'
          ? AuthFailureKind.expired
          : AuthFailureKind.network,
    };
    return AuthFailure(
      kind: kind,
      message: detail,
      code: code.isEmpty ? 'auth_failed' : code,
      statusCode: response.statusCode,
    );
  }

  static String str(Object? value) => value == null ? '' : value.toString();

  static AuthFailure describeError(Object error) {
    if (error is AuthFailure) return error;
    if (error is TimeoutException) {
      return const AuthFailure(
        kind: AuthFailureKind.network,
        message: '连接超时，请检查小车网络',
        code: 'timeout',
      );
    }
    if (error is WebSocketException) {
      final text = error.message;
      final status = error.httpStatusCode;
      if (status == 401 || status == 403 || text.contains('401') || text.contains('403')) {
        return AuthFailure(
          kind: AuthFailureKind.invalidToken,
          message: status == 403
              ? '认证失败：令牌无效、已过期或权限不足'
              : '认证失败：令牌无效或已过期',
          code: 'handshake_rejected',
          statusCode: status ?? (text.contains('401') ? 401 : 403),
        );
      }
      return AuthFailure(
        kind: AuthFailureKind.network,
        message: 'WebSocket 连接失败：$text',
        code: 'ws_error',
      );
    }
    if (error is SocketException) {
      return AuthFailure(
        kind: AuthFailureKind.network,
        message: '网络不可达：${error.message}',
        code: 'network_error',
      );
    }
    return AuthFailure(
      kind: AuthFailureKind.network,
      message: error.toString(),
      code: 'transport_error',
    );
  }

  static AuthFailure? fromClose(int? code, String? reason) {
    if (code != 1008) return null;
    final text = (reason ?? '').toLowerCase();
    if (text.contains('token expired')) {
      return const AuthFailure(
        kind: AuthFailureKind.expired,
        message: '访问令牌已过期，控制连接已关闭',
        code: 'token_expired',
      );
    }
    if (text.contains('forbidden') || text.contains('scope')) {
      return const AuthFailure(
        kind: AuthFailureKind.forbidden,
        message: '当前令牌权限不足，控制连接已关闭',
        code: 'forbidden_scope',
      );
    }
    return const AuthFailure(
      kind: AuthFailureKind.invalidToken,
      message: '认证失败，控制连接已关闭',
      code: 'handshake_rejected',
    );
  }

  static AuthFailure? fromWsMessage(Map<String, dynamic> payload) {
    if (payload['ok'] == true) return null;
    final code = str(payload['code']).toLowerCase();
    final message = str(
      payload['message'] ?? payload['detail'] ?? '',
    ).toLowerCase();
    if (code == 'token_expired' || message.contains('token expired')) {
      return const AuthFailure(
        kind: AuthFailureKind.expired,
        message: '访问令牌已过期，已停止发送控制命令',
        code: 'token_expired',
      );
    }
    if (code == 'forbidden_scope' ||
        message.contains('lacks') ||
        message.contains('scope')) {
      return const AuthFailure(
        kind: AuthFailureKind.forbidden,
        message: '当前令牌权限不足，已停止发送控制命令',
        code: 'forbidden_scope',
      );
    }
    return null;
  }
}
