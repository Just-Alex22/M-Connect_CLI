package com.appleton.mconnect

import android.os.Build
import android.os.Bundle
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.ListView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.PrintWriter
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.Socket
import java.net.SocketException
import java.util.UUID

data class Device(val id: String, val name: String, val address: String)

class MainActivity : AppCompatActivity() {

    private val discoveryPort = 17160
    private val execPort = 17161
    private val phoneServerPort = 17162
    private val discoveryDurationMs = 5000L

    private lateinit var btnDiscover: Button
    private lateinit var btnNotificationAccess: Button
    private lateinit var lvDevices: ListView
    private lateinit var tvConnected: TextView
    private lateinit var etCommand: EditText
    private lateinit var btnRun: Button
    private lateinit var tvOutput: TextView

    companion object {
        private val deviceId = UUID.randomUUID().toString()
    }

    private var devices = listOf<Device>()
    private var connectedAddress: String? = null
    private val announceIntervalMs = 2000L
    private var announceJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        btnDiscover = findViewById(R.id.btnDiscover)
        btnNotificationAccess = findViewById(R.id.btnNotificationAccess)
        lvDevices = findViewById(R.id.lvDevices)
        tvConnected = findViewById(R.id.tvConnected)
        etCommand = findViewById(R.id.etCommand)
        btnRun = findViewById(R.id.btnRun)
        tvOutput = findViewById(R.id.tvOutput)

        btnDiscover.setOnClickListener { runDiscovery() }
        btnRun.setOnClickListener { runCommand() }
        btnNotificationAccess.setOnClickListener {
            startActivity(notificationAccessSettingsIntent())
        }

        lvDevices.setOnItemClickListener { _, _, position, _ ->
            val device = devices[position]
            connectedAddress = device.address
            tvConnected.text = "Connected to: ${device.name} (${device.address})"
        }

        startAnnouncing()
        DeviceServer(applicationContext).start(phoneServerPort)
    }

    override fun onDestroy() {
        super.onDestroy()
        announceJob?.cancel()
    }

    private fun startAnnouncing() {
        announceJob = CoroutineScope(Dispatchers.IO).launch {
            val socket = DatagramSocket()
            socket.broadcast = true

            val payload = JSONObject()
            payload.put("type", "identity")
            payload.put("deviceId", deviceId)
            payload.put("deviceName", Build.MODEL)
            payload.put("port", phoneServerPort)
            val bytes = payload.toString().toByteArray(Charsets.UTF_8)
            val broadcastAddress = InetAddress.getByName("255.255.255.255")

            while (isActive) {
                try {
                    val packet = DatagramPacket(bytes, bytes.size, broadcastAddress, discoveryPort)
                    socket.send(packet)
                } catch (e: Exception) {
                }
                delay(announceIntervalMs)
            }

            socket.close()
        }
    }

    private fun runDiscovery() {
        tvOutput.text = "Discovering..."
        CoroutineScope(Dispatchers.Main).launch {
            val found = withContext(Dispatchers.IO) { discoverDevices() }
            devices = found
            val labels = found.map { "${it.name} (${it.address})" }
            lvDevices.adapter = ArrayAdapter(
                this@MainActivity,
                android.R.layout.simple_list_item_1,
                labels
            )
            tvOutput.text = "Found ${found.size} device(s)"
        }
    }

    private fun discoverDevices(): List<Device> {
        val found = linkedMapOf<String, Device>()

        val socket = DatagramSocket(null)
        socket.reuseAddress = true
        socket.bind(java.net.InetSocketAddress(discoveryPort))
        socket.soTimeout = 500

        val endTime = System.currentTimeMillis() + discoveryDurationMs
        val buffer = ByteArray(4096)

        while (System.currentTimeMillis() < endTime) {
            try {
                val packet = DatagramPacket(buffer, buffer.size)
                socket.receive(packet)
                val text = String(packet.data, 0, packet.length, Charsets.UTF_8)
                val json = JSONObject(text)

                if (json.optString("type") != "identity") {
                    continue
                }

                val deviceId = json.optString("deviceId")
                if (deviceId.isEmpty()) {
                    continue
                }

                found[deviceId] = Device(
                    id = deviceId,
                    name = json.optString("deviceName", "unknown"),
                    address = packet.address.hostAddress ?: "unknown"
                )
            } catch (e: SocketException) {
                break
            } catch (e: Exception) {
                continue
            }
        }

        socket.close()
        return found.values.toList()
    }

    private fun runCommand() {
        val ip = connectedAddress
        if (ip == null) {
            tvOutput.text = "Not connected to any device"
            return
        }

        val command = etCommand.text.toString()
        if (command.isBlank()) {
            tvOutput.text = "Usage: enter a command first"
            return
        }

        tvOutput.text = "Running..."
        CoroutineScope(Dispatchers.Main).launch {
            val result = withContext(Dispatchers.IO) { execCommand(ip, command) }
            tvOutput.text = result
        }
    }

    private fun execCommand(ip: String, command: String): String {
        return try {
            val socket = Socket(ip, execPort)
            val writer = PrintWriter(socket.getOutputStream(), true)
            val reader = BufferedReader(InputStreamReader(socket.getInputStream()))

            val request = JSONObject()
            request.put("type", "exec")
            request.put("command", command)
            writer.println(request.toString())

            val responseLine = reader.readLine()
            socket.close()

            if (responseLine == null) {
                return "No response from device"
            }

            val response = JSONObject(responseLine)
            val exitCode = response.optInt("exit_code", -1)
            val stdout = response.optString("stdout", "")
            val stderr = response.optString("stderr", "")

            "exit_code: $exitCode\n\nstdout:\n$stdout\nstderr:\n$stderr"
        } catch (e: Exception) {
            "Error: ${e.message}"
        }
    }
}
