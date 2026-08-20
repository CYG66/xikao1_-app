package com.example.xline_car_app

import java.io.File
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val channelName = "xline/device_preferences"
    private val preferencesName = "xline_device_preferences"
    private val agentChatsFileName = "agent_conversations.json"

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            channelName,
        ).setMethodCallHandler { call, result ->
            val preferences = getSharedPreferences(preferencesName, MODE_PRIVATE)
            when (call.method) {
                "load" -> result.success(
                    mapOf(
                        "devices_json" to preferences.getString("devices_json", null),
                        "selected_index" to preferences.getInt("selected_index", 0),
                    ),
                )
                "save" -> {
                    val devicesJson = call.argument<String>("devices_json") ?: "[]"
                    val selectedIndex = call.argument<Int>("selected_index") ?: 0
                    preferences.edit()
                        .putString("devices_json", devicesJson)
                        .putInt("selected_index", selectedIndex)
                        .apply()
                    result.success(null)
                }
                "load_agent_chats" -> {
                    val file = File(filesDir, agentChatsFileName)
                    result.success(if (file.isFile) file.readText(Charsets.UTF_8) else null)
                }
                "save_agent_chats" -> {
                    val conversationsJson =
                        call.argument<String>("conversations_json") ?: "[]"
                    val target = File(filesDir, agentChatsFileName)
                    val temporary = File(filesDir, "$agentChatsFileName.tmp")
                    temporary.writeText(conversationsJson, Charsets.UTF_8)
                    if (target.exists()) target.delete()
                    if (!temporary.renameTo(target)) {
                        target.writeText(conversationsJson, Charsets.UTF_8)
                        temporary.delete()
                    }
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }
}
