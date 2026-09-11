package com.fleetmind.agent

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.provider.Settings
import androidx.core.app.NotificationCompat
import com.google.gson.Gson
import com.google.gson.JsonObject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.PrintWriter
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

class FleetMindService : Service() {

    companion object {
        @Volatile var isRunning = false
        val queriesToday = AtomicInteger(0)
        private val uptimeStart = AtomicLong(0L)

        const val CHANNEL_ID = "fleetmind_channel"
        const val NOTIF_ID = 1001
        const val LOCAL_PORT = 11434
        const val HEARTBEAT_INTERVAL_MS = 60_000L
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val gson = Gson()
    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private lateinit var wakeLock: PowerManager.WakeLock
    private lateinit var meshDiscovery: MeshDiscovery
    private var serverSocket: ServerSocket? = null
    private var heartbeatJob: Job? = null
    private var localServerJob: Job? = null

    private val prefs by lazy { getSharedPreferences("fleetmind", Context.MODE_PRIVATE) }
    private val deviceId by lazy { Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID) }
    private val deviceModel by lazy { Build.MODEL }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        val wm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = wm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "FleetMind::InferenceWakeLock")
        meshDiscovery = MeshDiscovery(this)
        uptimeStart.set(System.currentTimeMillis())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIF_ID, buildNotification())
        isRunning = true

        meshDiscovery.start()
        startLocalHttpServer()
        startHeartbeat()

        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        isRunning = false
        scope.cancel()
        meshDiscovery.stop()
        serverSocket?.runCatching { close() }
        if (wakeLock.isHeld) wakeLock.release()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startHeartbeat() {
        heartbeatJob = scope.launch {
            while (isActive) {
                runCatching { sendHeartbeat() }
                delay(HEARTBEAT_INTERVAL_MS)
            }
        }
    }

    private suspend fun sendHeartbeat() {
        val licenseKey = prefs.getString("license_key", "") ?: return
        val serverUrl = prefs.getString("server_url", "https://api.fleetmind.io") ?: return

        val uptimeSec = (System.currentTimeMillis() - uptimeStart.get()) / 1000

        val payload = JsonObject().apply {
            addProperty("license_key", licenseKey)
            addProperty("device_id", deviceId)
            addProperty("device_model", deviceModel)
            addProperty("queries_processed", queriesToday.get())
            addProperty("uptime_seconds", uptimeSec)
        }

        val body = gson.toJson(payload)
            .toRequestBody("application/json".toMediaType())
        val request = Request.Builder()
            .url("$serverUrl/api/device/heartbeat")
            .post(body)
            .build()

        withContext(Dispatchers.IO) {
            http.newCall(request).execute().use { /* fire-and-forget; log failures silently */ }
        }
    }

    private fun startLocalHttpServer() {
        localServerJob = scope.launch(Dispatchers.IO) {
            serverSocket = ServerSocket(LOCAL_PORT)
            while (isActive) {
                val client = runCatching { serverSocket!!.accept() }.getOrNull() ?: break
                launch { handleClientConnection(client) }
            }
        }
    }

    private suspend fun handleClientConnection(socket: Socket) = withContext(Dispatchers.IO) {
        socket.use {
            if (!isBatteryOk()) {
                writeHttpResponse(socket, 503, """{"error":"device battery low, pausing inference"}""")
                return@withContext
            }

            val reader = BufferedReader(InputStreamReader(socket.getInputStream()))
            val requestLine = reader.readLine() ?: return@withContext

            // Only handle POST /api/generate (Ollama-compatible endpoint)
            if (!requestLine.startsWith("POST /api/generate")) {
                writeHttpResponse(socket, 404, """{"error":"not found"}""")
                return@withContext
            }

            // Read headers to find Content-Length
            var contentLength = 0
            var line = reader.readLine()
            while (line != null && line.isNotEmpty()) {
                if (line.lowercase().startsWith("content-length:")) {
                    contentLength = line.substringAfter(":").trim().toIntOrNull() ?: 0
                }
                line = reader.readLine()
            }

            val bodyChars = CharArray(contentLength)
            reader.read(bodyChars, 0, contentLength)
            val bodyJson = String(bodyChars)

            val prompt = runCatching {
                gson.fromJson(bodyJson, JsonObject::class.java).get("prompt").asString
            }.getOrElse { "" }

            if (prompt.isBlank()) {
                writeHttpResponse(socket, 400, """{"error":"prompt required"}""")
                return@withContext
            }

            // Check mesh peers for load balancing before inference
            val peer = meshDiscovery.getAvailablePeer()
            if (peer != null) {
                val redirectResponse = JsonObject().apply {
                    addProperty("redirect", "http://${peer.host}:${peer.port}/api/generate")
                    addProperty("reason", "load_balance")
                }
                writeHttpResponse(socket, 307, gson.toJson(redirectResponse))
                return@withContext
            }

            // Acquire wake lock during inference to prevent CPU throttle
            if (!wakeLock.isHeld) wakeLock.acquire(30_000L)

            val response = runInference(prompt)

            if (wakeLock.isHeld) wakeLock.release()

            queriesToday.incrementAndGet()

            val responseJson = JsonObject().apply {
                addProperty("model", "fleetmind-local")
                addProperty("response", response)
                addProperty("done", true)
            }
            writeHttpResponse(socket, 200, gson.toJson(responseJson))
        }
    }

    private fun runInference(prompt: String): String {
        val ollamaUrl = findOllamaServer()
            ?: return """{"error":"no_model_available","device_id":"$deviceId"}"""
        return callOllama(ollamaUrl, prompt)
    }

    /**
     * Probes the user-configured Ollama URL first, then falls back to scanning
     * common gateway IPs on port 11434. Returns the base URL of the first
     * responsive server, or null if none are reachable within the timeout.
     */
    private fun findOllamaServer(): String? {
        val configuredUrl = prefs.getString("ollama_url", "http://10.0.0.1:11434")
            ?.trimEnd('/')
            ?: "http://10.0.0.1:11434"

        val candidateUrls = linkedSetOf(
            configuredUrl,
            "http://192.168.1.1:11434",
            "http://192.168.0.1:11434",
            "http://10.0.0.1:11434"
        )

        val probeClient = OkHttpClient.Builder()
            .connectTimeout(2, TimeUnit.SECONDS)
            .readTimeout(2, TimeUnit.SECONDS)
            .build()

        for (url in candidateUrls) {
            val alive = runCatching {
                val req = Request.Builder().url("$url/api/tags").get().build()
                probeClient.newCall(req).execute().use { it.isSuccessful }
            }.getOrElse { false }
            if (alive) return url
        }
        return null
    }

    /**
     * POSTs to the Ollama /api/generate endpoint and returns the "response"
     * field from the JSON reply. Falls back to a mesh error JSON on failure.
     */
    private fun callOllama(baseUrl: String, prompt: String): String {
        val requestPayload = gson.toJson(JsonObject().apply {
            addProperty("model", "llama3.2:1b")
            addProperty("prompt", prompt)
            addProperty("stream", false)
        })
        val body = requestPayload.toRequestBody("application/json".toMediaType())
        val request = Request.Builder()
            .url("$baseUrl/api/generate")
            .post(body)
            .build()

        return runCatching {
            http.newCall(request).execute().use { response ->
                val raw = response.body?.string() ?: ""
                gson.fromJson(raw, JsonObject::class.java)
                    .get("response")
                    ?.asString
                    ?: """{"error":"no_model_available","device_id":"$deviceId"}"""
            }
        }.getOrElse { """{"error":"no_model_available","device_id":"$deviceId"}""" }
    }

    private fun writeHttpResponse(socket: Socket, statusCode: Int, body: String) {
        val statusText = when (statusCode) {
            200 -> "OK"
            307 -> "Temporary Redirect"
            400 -> "Bad Request"
            404 -> "Not Found"
            503 -> "Service Unavailable"
            else -> "Unknown"
        }
        val response = buildString {
            append("HTTP/1.1 $statusCode $statusText\r\n")
            append("Content-Type: application/json\r\n")
            append("Content-Length: ${body.toByteArray().size}\r\n")
            append("Connection: close\r\n")
            append("\r\n")
            append(body)
        }
        PrintWriter(socket.getOutputStream()).use { it.print(response); it.flush() }
    }

    private fun isBatteryOk(): Boolean {
        val intent = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return true
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        if (level < 0 || scale <= 0) return true
        return (level.toFloat() / scale.toFloat()) >= 0.20f
    }

    private fun buildNotification(): Notification {
        val openIntent = Intent(this, MainActivity::class.java)
        val pi = PendingIntent.getActivity(this, 0, openIntent, PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("FleetMind Active")
            .setContentText("Serving mesh queries")
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentIntent(pi)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "FleetMind Agent",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "FleetMind background inference service"
                setShowBadge(false)
            }
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(channel)
        }
    }
}
