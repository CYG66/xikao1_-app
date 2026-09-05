package com.example.xline_car_app

import android.content.Context
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        val preferences = getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL_NAME)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "load" -> {
                        val devicesJson = preferences.getString(KEY_DEVICES_JSON, null)
                        if (devicesJson.isNullOrBlank()) {
                            result.success(null)
                        } else {
                            result.success(
                                mapOf(
                                    "devices_json" to devicesJson,
                                    "selected_index" to preferences.getInt(KEY_SELECTED_INDEX, 0),
                                ),
                            )
                        }
                    }

                    "save" -> {
                        val devicesJson = call.argument<String>("devices_json")
                        if (devicesJson.isNullOrBlank()) {
                            result.error("invalid_devices", "devices_json is required", null)
                            return@setMethodCallHandler
                        }
                        val selectedIndex = call.argument<Int>("selected_index") ?: 0
                        val saved = preferences.edit()
                            .putString(KEY_DEVICES_JSON, devicesJson)
                            .putInt(KEY_SELECTED_INDEX, selectedIndex)
                            .commit()
                        if (saved) result.success(null)
                        else result.error("save_failed", "Unable to save device preferences", null)
                    }

                    "load_agent_chats" -> {
                        result.success(preferences.getString(KEY_AGENT_CHATS, null))
                    }

                    "save_agent_chats" -> {
                        val conversationsJson = call.argument<String>("conversations_json")
                        if (conversationsJson == null) {
                            result.error("invalid_chats", "conversations_json is required", null)
                            return@setMethodCallHandler
                        }
                        val saved = preferences.edit()
                            .putString(KEY_AGENT_CHATS, conversationsJson)
                            .commit()
                        if (saved) result.success(null)
                        else result.error("save_failed", "Unable to save agent chats", null)
                    }

                    else -> result.notImplemented()
                }
            }
    }

    private companion object {
        const val CHANNEL_NAME = "xline/device_preferences"
        const val PREFERENCES_NAME = "xline_app_preferences"
        const val KEY_DEVICES_JSON = "devices_json"
        const val KEY_SELECTED_INDEX = "selected_index"
        const val KEY_AGENT_CHATS = "agent_chats"
    }
}
