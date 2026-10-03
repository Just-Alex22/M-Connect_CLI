package com.appleton.mconnect

import android.content.ComponentName
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.media.RingtoneManager
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.os.StatFs
import android.os.VibrationEffect
import android.os.Vibrator
import android.provider.MediaStore
import android.provider.Settings
import android.util.Base64
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.PrintWriter
import java.net.ServerSocket
import java.net.Socket

class DeviceServer(private val context: Context) {

    fun start(port: Int) {
        CoroutineScope(Dispatchers.IO).launch {
            val serverSocket = ServerSocket(port)
            while (isActive) {
                try {
                    val client = serverSocket.accept()
                    launch { handleClient(client) }
                } catch (e: Exception) {
                }
            }
        }
    }

    private suspend fun handleClient(socket: Socket) {
        withContext(Dispatchers.IO) {
            try {
                val reader = BufferedReader(InputStreamReader(socket.getInputStream()))
                val writer = PrintWriter(socket.getOutputStream(), true)

                val line = reader.readLine() ?: return@withContext
                val request = JSONObject(line)

                if (request.optString("type") == "watch") {
                    handleWatch(request.optString("category"), writer)
                } else {
                    val response = handleRequest(request)
                    writer.println(response.toString())
                }
            } catch (e: Exception) {
            } finally {
                socket.close()
            }
        }
    }

    private fun handleRequest(request: JSONObject): JSONObject {
        val type = request.optString("type")
        val category = request.optString("category")

        return when (type) {
            "get" -> handleGet(category, request)
            "set" -> handleSet(category, request)
            "file" -> handleFile(request)
            else -> errorResult("get_result", "unknown request type")
        }
    }

    private fun handleGet(category: String, request: JSONObject): JSONObject {
        return when (category) {
            "battery" -> getBattery()
            "volume" -> getVolume()
            "multimedia" -> getMultimedia()
            "device" -> getDeviceInfo()
            "storage" -> getStorage()
            "notifications" -> getNotifications()
            else -> errorResult("get_result", "unknown category: $category")
        }
    }

    private fun handleSet(category: String, request: JSONObject): JSONObject {
        val value = request.optString("value")
        return when (category) {
            "volume" -> setVolume(value)
            "multimedia" -> setMultimedia(value)
            "find" -> setFind()
            else -> errorResult("set_result", "unknown category: $category")
        }
    }

    private suspend fun handleWatch(category: String, writer: PrintWriter) {
        when (category) {
            "notifications" -> watchNotifications(writer)
            else -> writer.println(errorResult("watch_result", "unknown watch category: $category").toString())
        }
    }

    private suspend fun watchNotifications(writer: PrintWriter) {
        if (!isNotificationAccessEnabled()) {
            writer.println(
                errorResult(
                    "watch_result",
                    "Notification access not granted. Enable it in Settings > Apps > M-Connect > Notification access"
                ).toString()
            )
            return
        }

        val channel = Channel<JSONObject>(capacity = Channel.UNLIMITED)
        val callback: (String, String, String) -> Unit = { source, title, text ->
            val event = JSONObject()
            event.put("type", "notification_event")
            event.put("source", source)
            event.put("title", title)
            event.put("text", text)
            channel.trySend(event)
        }

        NotificationListener.addCallback(callback)
        try {
            while (true) {
                val event = channel.receive()
                writer.println(event.toString())
                if (writer.checkError()) {
                    break
                }
            }
        } finally {
            NotificationListener.removeCallback(callback)
        }
    }

    private fun errorResult(type: String, message: String): JSONObject {
        val result = JSONObject()
        result.put("type", type)
        result.put("ok", false)
        result.put("error", message)
        return result
    }

    private fun okResult(type: String): JSONObject {
        val result = JSONObject()
        result.put("type", type)
        result.put("ok", true)
        return result
    }

    private fun getBattery(): JSONObject {
        val batteryManager = context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager
        val percentage = batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)

        val result = okResult("get_result")
        result.put("value", percentage)
        return result
    }

    private fun getVolume(): JSONObject {
        val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val current = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC)
        val max = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val percentage = if (max > 0) (current * 100) / max else 0

        val result = okResult("get_result")
        result.put("value", percentage)
        return result
    }

    private fun setVolume(value: String): JSONObject {
        val percentage = value.toIntOrNull()
        if (percentage == null || percentage !in 0..100) {
            return errorResult("set_result", "value must be a number 0-100")
        }

        val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val max = audioManager.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val target = (max * percentage) / 100
        audioManager.setStreamVolume(AudioManager.STREAM_MUSIC, target, 0)

        return okResult("set_result")
    }

    private fun getDeviceInfo(): JSONObject {
        val result = okResult("get_result")
        result.put("model", Build.MODEL)
        result.put("manufacturer", Build.MANUFACTURER)
        result.put("android_version", Build.VERSION.RELEASE)
        return result
    }

    private fun getStorage(): JSONObject {
        val stat = StatFs(Environment.getDataDirectory().path)
        val freeMb = stat.availableBytes / (1024 * 1024)

        val result = okResult("get_result")
        result.put("free_mb", freeMb)
        return result
    }

    private fun setFind(): JSONObject {
        val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val maxVolume = audioManager.getStreamMaxVolume(AudioManager.STREAM_ALARM)
        audioManager.setStreamVolume(AudioManager.STREAM_ALARM, maxVolume, 0)

        val uri = RingtoneManager.getActualDefaultRingtoneUri(context, RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getValidRingtoneUri(context)
        val ringtone = RingtoneManager.getRingtone(context, uri)
        ringtone.audioAttributes = android.media.AudioAttributes.Builder()
            .setUsage(android.media.AudioAttributes.USAGE_ALARM)
            .build()
        ringtone.play()

        val vibrator = context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        if (vibrator.hasVibrator()) {
            vibrator.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 500, 200, 500, 200, 500), -1))
        }

        CoroutineScope(Dispatchers.IO).launch {
            delay(10000)
            ringtone.stop()
        }

        return okResult("set_result")
    }

    private fun isNotificationAccessEnabled(): Boolean {
        val enabled = Settings.Secure.getString(
            context.contentResolver,
            "enabled_notification_listeners"
        ) ?: ""
        return enabled.contains(context.packageName)
    }

    private fun activeMediaController(): android.media.session.MediaController? {
        val manager = context.getSystemService(Context.MEDIA_SESSION_SERVICE) as MediaSessionManager
        val component = ComponentName(context, NotificationListener::class.java)
        val sessions = manager.getActiveSessions(component)
        return sessions.firstOrNull()
    }

    private fun getMultimedia(): JSONObject {
        if (!isNotificationAccessEnabled()) {
            return errorResult(
                "get_result",
                "Notification access not granted. Enable it in Settings > Apps > M-Connect > Notification access"
            )
        }

        val controller = activeMediaController()
        if (controller == null) {
            val result = okResult("get_result")
            result.put("status", "none")
            return result
        }

        val metadata = controller.metadata
        val title = metadata?.getString(android.media.MediaMetadata.METADATA_KEY_TITLE) ?: ""
        val artist = metadata?.getString(android.media.MediaMetadata.METADATA_KEY_ARTIST) ?: ""
        val state = controller.playbackState?.state
        val status = when (state) {
            PlaybackState.STATE_PLAYING -> "playing"
            PlaybackState.STATE_PAUSED -> "paused"
            else -> "stopped"
        }

        val result = okResult("get_result")
        result.put("title", title)
        result.put("artist", artist)
        result.put("status", status)
        result.put("source", controller.packageName)
        return result
    }

    private fun setMultimedia(value: String): JSONObject {
        if (!isNotificationAccessEnabled()) {
            return errorResult(
                "set_result",
                "Notification access not granted. Enable it in Settings > Apps > M-Connect > Notification access"
            )
        }

        val controller = activeMediaController()
        if (controller == null) {
            return errorResult("set_result", "no active media session")
        }

        when (value) {
            "play" -> controller.transportControls.play()
            "pause" -> controller.transportControls.pause()
            "next" -> controller.transportControls.skipToNext()
            "previous" -> controller.transportControls.skipToPrevious()
            else -> return errorResult("set_result", "unknown multimedia command: $value")
        }

        return okResult("set_result")
    }

    private fun getNotifications(): JSONObject {
        if (!isNotificationAccessEnabled()) {
            return errorResult(
                "get_result",
                "Notification access not granted. Enable it in Settings > Apps > M-Connect > Notification access"
            )
        }

        val result = okResult("get_result")
        val array = JSONArray()
        NotificationListener.currentNotifications().forEach { (source, title, text) ->
            val item = JSONObject()
            item.put("source", source)
            item.put("title", title)
            item.put("text", text)
            array.put(item)
        }
        result.put("notifications", array)
        return result
    }

    private fun handleFile(request: JSONObject): JSONObject {
        val name = request.optString("name")
        val subdir = request.optString("subdir", "")
        val dataBase64 = request.optString("data_base64")

        if (name.isEmpty() || dataBase64.isEmpty()) {
            return errorResult("file_result", "missing name or data")
        }

        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return errorResult("file_result", "file transfer requires Android 10 (API 29) or newer")
        }

        return try {
            val bytes = Base64.decode(dataBase64, Base64.DEFAULT)
            val relativePath = if (subdir.isNotEmpty()) {
                "Download/M-Connect/$subdir/"
            } else {
                "Download/M-Connect/"
            }

            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, name)
                put(MediaStore.Downloads.RELATIVE_PATH, relativePath)
            }

            val uri = context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: return errorResult("file_result", "could not create file entry")

            context.contentResolver.openOutputStream(uri)?.use { it.write(bytes) }
                ?: return errorResult("file_result", "could not open output stream")

            okResult("file_result")
        } catch (e: Exception) {
            errorResult("file_result", "failed to save file: ${e.message}")
        }
    }
}

fun notificationAccessSettingsIntent(): Intent {
    return Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS")
}
