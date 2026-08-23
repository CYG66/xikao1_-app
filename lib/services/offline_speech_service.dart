import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

bool _sherpaBindingsInitialized = false;

class OfflineSpeechException implements Exception {
  const OfflineSpeechException(this.message);

  final String message;

  @override
  String toString() => message;
}

/// Records a mono WAV and transcribes it locally with Zipformer CTC.
class OfflineSpeechService {
  static const int _recordingSampleRate = 48000;
  static const String _assetRoot = 'assets/asr/paraformer-zh-en';

  final AudioRecorder _recorder = AudioRecorder();
  sherpa.OfflineRecognizer? _recognizer;
  bool _recording = false;
  String? _recordingPath;

  bool get isRecording => _recording;

  Future<void> initialize() async {
    if (_recognizer != null) return;

    if (!_sherpaBindingsInitialized) {
      sherpa.initBindings();
      _sherpaBindingsInitialized = true;
    }

    final supportDirectory = await getApplicationSupportDirectory();
    final modelDirectory = Directory(
      '${supportDirectory.path}${Platform.pathSeparator}offline_asr',
    );
    await modelDirectory.create(recursive: true);

    final modelPath = await _copyAssetIfNeeded(
      '$_assetRoot/model.int8.onnx',
      '${modelDirectory.path}${Platform.pathSeparator}model.int8.onnx',
    );
    final tokensPath = await _copyAssetIfNeeded(
      '$_assetRoot/tokens.txt',
      '${modelDirectory.path}${Platform.pathSeparator}tokens.txt',
    );

    try {
      final config = sherpa.OfflineRecognizerConfig(
        model: sherpa.OfflineModelConfig(
          zipformerCtc: sherpa.OfflineZipformerCtcModelConfig(model: modelPath),
          tokens: tokensPath,
          numThreads: 2,
          debug: false,
          provider: 'cpu',
          modelingUnit: 'cjkchar',
        ),
        decodingMethod: 'greedy_search',
      );
      _recognizer = sherpa.OfflineRecognizer(config);
    } catch (error) {
      throw OfflineSpeechException('离线语音模型加载失败：$error');
    }
  }

  Future<void> start() async {
    if (_recording) return;
    await initialize();

    if (!await _recorder.hasPermission()) {
      throw const OfflineSpeechException('麦克风权限未开启，请在系统设置中允许 X-LINE2 使用麦克风');
    }

    try {
      final supportDirectory = await getApplicationSupportDirectory();
      _recordingPath =
          '${supportDirectory.path}${Platform.pathSeparator}last_voice_input.wav';
      final previousRecording = File(_recordingPath!);
      if (await previousRecording.exists()) await previousRecording.delete();
      await _recorder.start(
        const RecordConfig(
          encoder: AudioEncoder.wav,
          sampleRate: _recordingSampleRate,
          numChannels: 1,
          autoGain: false,
          echoCancel: false,
          noiseSuppress: false,
        ),
        path: _recordingPath!,
      );
      _recording = true;
    } catch (error) {
      throw OfflineSpeechException('无法启动麦克风录音：$error');
    }
  }

  Future<String> stopAndRecognize() async {
    if (!_recording) return '';

    final stoppedPath = await _recorder.stop();
    _recording = false;
    final recordingPath = stoppedPath ?? _recordingPath;
    if (recordingPath == null || !await File(recordingPath).exists()) {
      throw const OfflineSpeechException('没有取得录音文件，请重新录制');
    }

    final recognizer = _recognizer;
    if (recognizer == null) {
      throw const OfflineSpeechException('离线语音模型尚未就绪');
    }

    final wave = sherpa.readWave(recordingPath);
    if (wave.sampleRate <= 0 || wave.samples.isEmpty) {
      throw const OfflineSpeechException('平板生成的录音文件无法读取，请重新录制');
    }
    if (wave.samples.length / wave.sampleRate < 0.5) {
      throw const OfflineSpeechException('录音时间太短，请重新点击麦克风并完整说出内容');
    }
    final samples = _prepareSamples(wave.samples);

    final stream = recognizer.createStream();
    try {
      stream.acceptWaveform(samples: samples, sampleRate: wave.sampleRate);
      recognizer.decode(stream);
      return _normalizeProjectTerms(recognizer.getResult(stream).text);
    } catch (error) {
      throw OfflineSpeechException('本地语音转写失败：$error');
    } finally {
      stream.free();
    }
  }

  Future<void> cancel() async {
    if (_recording) await _recorder.cancel();
    _recording = false;
  }

  Future<void> dispose() async {
    await cancel();
    await _recorder.dispose();
    _recognizer?.free();
    _recognizer = null;
  }

  Future<String> _copyAssetIfNeeded(String assetPath, String targetPath) async {
    final asset = await rootBundle.load(assetPath);
    final file = File(targetPath);
    if (!await file.exists() || await file.length() != asset.lengthInBytes) {
      await file.writeAsBytes(
        asset.buffer.asUint8List(asset.offsetInBytes, asset.lengthInBytes),
        flush: true,
      );
    }
    return file.path;
  }

  Float32List _prepareSamples(Float32List raw) {
    final sampleCount = raw.length;
    var mean = 0.0;
    for (final value in raw) {
      mean += value;
    }
    mean /= sampleCount;

    var squareSum = 0.0;
    for (final value in raw) {
      final centered = value - mean;
      squareSum += centered * centered;
    }
    final rms = math.sqrt(squareSum / sampleCount);
    if (rms < 0.0015) {
      throw const OfflineSpeechException('录音音量过低，请靠近平板麦克风并重新说一遍');
    }

    // Preserve natural dynamics, but lift recordings captured quietly by the
    // tablet without relying on vendor-specific Android audio effects.
    final gain = rms < 0.045 ? math.min(4.0, 0.06 / rms) : 1.0;
    final samples = Float32List(sampleCount);
    for (var i = 0; i < sampleCount; i++) {
      samples[i] = ((raw[i] - mean) * gain).clamp(-1.0, 1.0).toDouble();
    }
    return samples;
  }

  String _normalizeProjectTerms(String text) {
    var result = text.replaceAll(RegExp(r'\s+'), ' ').trim();
    const replacements = <String, String>{
      '校车': '小车',
      '小扯': '小车',
      '喷马机': '喷码机',
      '喷墨基': '喷墨机',
      '全站一': '全站仪',
      '正方型': '正方形',
      '规划路经': '规划路径',
      '画线小车': '划线小车',
      '罗斯二': 'ROS2',
    };
    for (final entry in replacements.entries) {
      result = result.replaceAll(entry.key, entry.value);
    }
    return result;
  }
}
