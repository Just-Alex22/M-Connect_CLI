package com.appleton.mconnect

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

class NotificationListener : NotificationListenerService() {

    companion object {
        var instance: NotificationListener? = null
            private set

        private val callbacks = mutableListOf<(String, String, String) -> Unit>()

        fun addCallback(callback: (String, String, String) -> Unit) {
            synchronized(callbacks) { callbacks.add(callback) }
        }

        fun removeCallback(callback: (String, String, String) -> Unit) {
            synchronized(callbacks) { callbacks.remove(callback) }
        }

        fun currentNotifications(): List<Triple<String, String, String>> {
            val active = instance?.activeNotifications ?: return emptyList()
            return active.map { extractInfo(it) }
        }

        private fun extractInfo(sbn: StatusBarNotification): Triple<String, String, String> {
            val extras = sbn.notification.extras
            val title = extras.getCharSequence("android.title")?.toString() ?: ""
            val text = extras.getCharSequence("android.text")?.toString() ?: ""
            return Triple(sbn.packageName, title, text)
        }
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        instance = this
    }

    override fun onListenerDisconnected() {
        super.onListenerDisconnected()
        instance = null
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val (source, title, text) = extractInfo(sbn)
        val listeners = synchronized(callbacks) { callbacks.toList() }
        listeners.forEach { it(source, title, text) }
    }
}
