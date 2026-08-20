import 'package:flutter/services.dart';

class AgentChatPreferences {
  static const MethodChannel _channel = MethodChannel(
    'xline/device_preferences',
  );

  static Future<String?> load() async {
    try {
      return await _channel.invokeMethod<String>('load_agent_chats');
    } on MissingPluginException {
      return null;
    }
  }

  static Future<void> save(String conversationsJson) async {
    try {
      await _channel.invokeMethod<void>('save_agent_chats', {
        'conversations_json': conversationsJson,
      });
    } on MissingPluginException {
      // Widget tests and non-Android hosts do not register the native channel.
    }
  }
}
