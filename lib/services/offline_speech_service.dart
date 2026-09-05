class OfflineSpeechException implements Exception {
  const OfflineSpeechException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// Lightweight test-build placeholder used while the offline ASR model is absent.
class OfflineSpeechService {
  bool get isRecording => false;

  Future<void> initialize() async {
    throw const OfflineSpeechException('测试版未内置离线语音模型，请使用文字输入');
  }

  Future<void> start() => initialize();

  Future<String> stopAndRecognize() async => '';

  Future<void> cancel() async {}

  Future<void> dispose() async {}
}
