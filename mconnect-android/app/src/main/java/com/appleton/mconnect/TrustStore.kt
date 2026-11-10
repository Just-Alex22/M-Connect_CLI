package com.appleton.mconnect

import android.content.Context
import java.io.File

object TrustStore {

    private fun trustFile(context: Context) = File(context.filesDir, "trusted_devices.txt")

    @Synchronized
    fun isTrusted(context: Context, fingerprint: String): Boolean {
        return load(context).contains(fingerprint)
    }

    @Synchronized
    fun trust(context: Context, fingerprint: String) {
        val fingerprints = load(context)
        if (fingerprints.add(fingerprint)) {
            save(context, fingerprints)
        }
    }

    @Synchronized
    fun forget(context: Context, fingerprint: String) {
        val fingerprints = load(context)
        if (fingerprints.remove(fingerprint)) {
            save(context, fingerprints)
        }
    }

    private fun load(context: Context): MutableSet<String> {
        val file = trustFile(context)
        if (!file.exists()) {
            return linkedSetOf()
        }
        return file.readLines().map { it.trim() }.filter { it.isNotEmpty() }.toCollection(linkedSetOf())
    }

    private fun save(context: Context, fingerprints: Set<String>) {
        val file = trustFile(context)
        val temporary = File(file.parentFile, file.name + ".tmp")
        temporary.writeText(fingerprints.joinToString("\n"))
        check(temporary.renameTo(file)) { "No se pudo guardar el almacén de confianza" }
    }
}