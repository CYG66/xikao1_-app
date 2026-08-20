import 'package:flutter/services.dart';

class SavedDevicePreferences {
  const SavedDevicePreferences({
    required this.devicesJson,
    required this.selectedIndex,
  });

  final String devicesJson;
  final int selectedIndex;
}

class DevicePreferences {
  static const MethodChannel _channel = MethodChannel(
    'xline/device_preferences',
  );

  static Future<SavedDevicePreferences?> load() async {
    try {
      final result = await _channel.invokeMapMethod<String, dynamic>('load');
      final devicesJson = result?['devices_json']?.toString();
      if (devicesJson == null || devicesJson.isEmpty) return null;
      return SavedDevicePreferences(
        devicesJson: devicesJson,
        selectedIndex: (result?['selected_index'] as num?)?.toInt() ?? 0,
      );
    } on MissingPluginException {
      return null;
    }
  }

  static Future<void> save({
    required String devicesJson,
    required int selectedIndex,
  }) async {
    try {
      await _channel.invokeMethod<void>('save', {
        'devices_json': devicesJson,
        'selected_index': selectedIndex,
      });
    } on MissingPluginException {
      // Widget tests and non-Android hosts do not register the native channel.
    }
  }
}
