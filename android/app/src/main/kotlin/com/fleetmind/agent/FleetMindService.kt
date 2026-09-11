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
import android.util.Base64
import android.util.Log
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
        private const val TAG = "FleetMindService"
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val gson = Gson()
    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private lateinit var wakeLock: PowerManager.WakeLock
    private lateinit var meshDiscovery: MeshDiscovery
    private lateinit var trustZoneKeyManager: TrustZoneKeyManager
    private var serverSocket: ServerSocket? = null
    private var heartbeatJob: Job? = null
    private var localServerJob: Job? = null
    private lateinit var telemetry: TelemetryCollector
    private lateinit var chunkStorage: ChunkStorage
    private lateinit var shardedInference: ShardedInference

    private val prefs by lazy { getSharedPreferences("fleetmind", Context.MODE_PRIVATE) }
    private val deviceId by lazy { Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID) }
    private val deviceModel by lazy { Build.MODEL }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        val wm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = wm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "FleetMind::InferenceWakeLock")
        meshDiscovery = MeshDiscovery(this)
        trustZoneKeyManager = TrustZoneKeyManager(this)
        telemetry = TelemetryCollector(this)
        chunkStorage = ChunkStorage(this)
        shardedInference = ShardedInference(this)
        uptimeStart.set(System.currentTimeMillis())
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIF_ID, buildNotification())
        isRunning = true

        meshDiscovery.start()
        initTrustChain()
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
        shardedInference.destroy()
        if (wakeLock.isHeld) wakeLock.release()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun initTrustChain() {
        scope.launch {
            val operatorEmail = prefs.getString("operator_email", null) ?: run {
                Log.w(TAG, "TrustChain: no operator_email configured, skipping key registration")
                return@launch
            }
            val serverUrl = prefs.getString("server_url", "https://api.fleetmind.io") ?: return@launch
            val licenseKey = prefs.getString("license_key", "") ?: return@launch
            if (licenseKey.isBlank()) return@launch

            runCatching {
                trustZoneKeyManager.generateUserKeyPair(operatorEmail)
                val pubKeyB64 = trustZoneKeyManager.getPublicKeyBase64(operatorEmail)
                val certChain = trustZoneKeyManager.getAttestationCertificateChain(operatorEmail)
                    .map { Base64.encodeToString(it.encoded, Base64.NO_WRAP) }

                val payload = JsonObject().apply {
                    addProperty("license_key", licenseKey)
                    addProperty("device_id", deviceId)
                    addProperty("public_key_base64", pubKeyB64)
                    val arr = com.google.gson.JsonArray()
                    certChain.forEach { arr.add(it) }
                    add("attestation_cert_chain", arr)
                }
                val body = gson.toJson(payload).toRequestBody("application/json".toMediaType())
                val request = Request.Builder()
                    .url("$serverUrl/api/device/pubkey")
                    .post(body)
                    .build()

                withContext(Dispatchers.IO) {
                    http.newCall(request).execute().use { resp ->
                        Log.i(TAG, "TrustChain: pubkey registered, hardware_attested=${resp.isSuccessful}")
                    }
                }
            }.onFailure { e ->
                Log.e(TAG, "TrustChain: key registration failed: ${e.message}")
            }
        }
    }

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
        val t = telemetry.collect()

        val payload = JsonObject().apply {
            addProperty("license_key", licenseKey)
            addProperty("device_id", deviceId)
            addProperty("device_model", deviceModel)
            addProperty("queries_processed", queriesToday.get())
            addProperty("uptime_seconds", uptimeSec)
            // Power layer
            addProperty("battery_level", t.batteryLevel)
            addProperty("is_charging", t.isCharging)
            t.estimatedRuntimeMins?.let { addProperty("estimated_runtime_mins", it) }
            // Thermal layer
            t.cpuTempCelsius?.let { addProperty("cpu_temp_celsius", it) }
            addProperty("thermal_state", t.thermalState)
            // Network layer
            t.wifiRssiDbm?.let { addProperty("wifi_rssi_dbm", it) }
            t.networkBandwidthMbps?.let { addProperty("network_bandwidth_mbps", it) }
            // Compute
            t.cpuUsagePercent?.let { addProperty("cpu_usage_percent", it) }
            addProperty("ram_available_mb", t.ramAvailableMb)
            // Storage
            addProperty("available_storage_mb", t.availableStorageMb - chunkStorage.getTotalUsedMb())
        }

        val body = gson.toJson(payload).toRequestBody("application/json".toMediaType())
        val request = Request.Builder()
            .url("$serverUrl/api/device/heartbeat")
            .post(body)
            .build()

        withContext(Dispatchers.IO) {
            http.newCall(request).execute().use { /* fire-and-forget */ }
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
            val reader = BufferedReader(InputStreamReader(socket.getInputStream()))
            val requestLine = reader.readLine() ?: return@withContext

            var contentLength = 0
            var line = reader.readLine()
            while (line != null && line.isNotEmpty()) {
                if (line.lowercase().startsWith("content-length:")) {
                    contentLength = line.substringAfter(":").trim().toIntOrNull() ?: 0
                }
                line = reader.readLine()
            }

            when {
                // ── Inference ──────────────────────────────────────────────────
                requestLine.startsWith("POST /api/secure/query") ->
                    handleSecureQuery(socket, reader, contentLength)

                requestLine.startsWith("POST /api/generate") ->
                    handleGenerate(socket, reader, contentLength)

                // ── Model sharding pipeline ────────────────────────────────────
                requestLine.startsWith("POST /shard/forward") ->
                    handleShardForward(socket, reader, contentLength)

                requestLine.startsWith("POST /shard/configure") ->
                    handleShardConfigure(socket, reader, contentLength)

                requestLine.startsWith("GET /shard/status") ->
                    handleShardStatus(socket)

                // ── Chunk storage ──────────────────────────────────────────────
                requestLine.startsWith("POST /chunk/store") ->
                    handleChunkStore(socket, reader, contentLength)

                requestLine.startsWith("GET /chunk/") ->
                    handleChunkRetrieve(socket, requestLine)

                requestLine.startsWith("DELETE /chunk/") ->
                    handleChunkDelete(socket, requestLine)

                requestLine.startsWith("GET /chunk") ->
                    handleChunkList(socket)

                else ->
                    writeHttpResponse(socket, 404, """{"error":"not found"}""")
            }
        }
    }

    // ── Inference ────────────────────────────────────────────────────────────────

    private suspend fun handleGenerate(
        socket: Socket,
        reader: BufferedReader,
        contentLength: Int,
    ) = withContext(Dispatchers.IO) {
        if (!isBatteryOk()) {
            writeHttpResponse(socket, 503, """{"error":"device battery low, pausing inference"}""")
            return@withContext
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

        val peer = meshDiscovery.getAvailablePeer()
        if (peer != null) {
            val redirectResponse = JsonObject().apply {
                addProperty("redirect", "http://${peer.host}:${peer.port}/api/generate")
                addProperty("reason", "load_balance")
            }
            writeHttpResponse(socket, 307, gson.toJson(redirectResponse))
            return@withContext
        }

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

    // ── Model sharding ────────────────────────────────────────────────────────────

    private suspend fun handleShardForward(
        socket: Socket,
        reader: BufferedReader,
        contentLength: Int,
    ) = withContext(Dispatchers.IO) {
        if (!shardedInference.isConfigured()) {
            writeHttpResponse(socket, 503, """{"error":"shard not configured"}""")
            return@withContext
        }

        val bodyChars = CharArray(contentLength)
        reader.read(bodyChars, 0, contentLength)
        val json = runCatching {
            gson.fromJson(String(bodyChars), JsonObject::class.java)
        }.getOrElse {
            writeHttpResponse(socket, 400, """{"error":"invalid json"}""")
            return@withContext
        }

        val inputB64 = json.get("hidden_state_b64")?.asString
            ?: json.get("token_ids_b64")?.asString
            ?: run {
                writeHttpResponse(socket, 400, """{"error":"hidden_state_b64 or token_ids_b64 required"}""")
                return@withContext
            }
        val inputData = runCatching { Base64.decode(inputB64, Base64.NO_WRAP) }.getOrElse {
            writeHttpResponse(socket, 400, """{"error":"base64 decode failed"}""")
            return@withContext
        }

        if (!wakeLock.isHeld) wakeLock.acquire(120_000L)
        val output = runCatching { shardedInference.forward(inputData) }.getOrElse {
            if (wakeLock.isHeld) wakeLock.release()
            writeHttpResponse(socket, 500, """{"error":"shard forward failed: ${it.message}"}""")
            return@withContext
        }
        if (wakeLock.isHeld) wakeLock.release()

        val responseJson = JsonObject().apply {
            addProperty("output_b64", Base64.encodeToString(output, Base64.NO_WRAP))
            addProperty("device_id", deviceId)
            addProperty("output_bytes", output.size)
        }
        writeHttpResponse(socket, 200, gson.toJson(responseJson))
    }

    private suspend fun handleShardConfigure(
        socket: Socket,
        reader: BufferedReader,
        contentLength: Int,
    ) = withContext(Dispatchers.IO) {
        val bodyChars = CharArray(contentLength)
        reader.read(bodyChars, 0, contentLength)
        val json = runCatching {
            gson.fromJson(String(bodyChars), JsonObject::class.java)
        }.getOrElse {
            writeHttpResponse(socket, 400, """{"error":"invalid json"}""")
            return@withContext
        }

        val config = ShardedInference.ShardConfig(
            shardIndex   = json.get("shard_index")?.asInt ?: 0,
            totalShards  = json.get("total_shards")?.asInt ?: 1,
            layerStart   = json.get("layer_start")?.asInt ?: 0,
            layerEnd     = json.get("layer_end")?.asInt ?: 32,
            isFinalShard = json.get("is_final_shard")?.asBoolean ?: true,
            modelPath    = json.get("model_path")?.asString ?: "",
            nextShardUrl = json.get("next_shard_url")?.asString,
            hiddenDim    = json.get("hidden_dim")?.asInt ?: 8192,
            threads      = json.get("threads")?.asInt ?: 4,
        )

        if (config.modelPath.isBlank()) {
            writeHttpResponse(socket, 400, """{"error":"model_path required"}""")
            return@withContext
        }

        val ok = shardedInference.configure(config)
        val response = JsonObject().apply {
            addProperty("configured", ok)
            addProperty("shard_index", config.shardIndex)
            addProperty("layer_start", config.layerStart)
            addProperty("layer_end", config.layerEnd)
            addProperty("is_final_shard", config.isFinalShard)
        }
        writeHttpResponse(socket, if (ok) 200 else 500, gson.toJson(response))
    }

    private fun handleShardStatus(socket: Socket) {
        val cfg = shardedInference.isConfigured()
        val response = JsonObject().apply {
            addProperty("shard_ready", cfg)
            addProperty("device_id", deviceId)
            addProperty("ram_available_mb", telemetry.getRamAvailableMb())
        }
        writeHttpResponse(socket, 200, gson.toJson(response))
    }

    // ── Chunk storage ─────────────────────────────────────────────────────────────

    private suspend fun handleChunkStore(
        socket: Socket,
        reader: BufferedReader,
        contentLength: Int,
    ) = withContext(Dispatchers.IO) {
        val bodyChars = CharArray(contentLength)
        reader.read(bodyChars, 0, contentLength)
        val json = runCatching {
            gson.fromJson(String(bodyChars), JsonObject::class.java)
        }.getOrElse {
            writeHttpResponse(socket, 400, """{"error":"invalid json"}""")
            return@withContext
        }

        val chunkId = json.get("chunk_id")?.asString ?: run {
            writeHttpResponse(socket, 400, """{"error":"chunk_id required"}""")
            return@withContext
        }
        val dataB64 = json.get("data_b64")?.asString ?: run {
            writeHttpResponse(socket, 400, """{"error":"data_b64 required"}""")
            return@withContext
        }

        val data = runCatching { Base64.decode(dataB64, Base64.NO_WRAP) }.getOrElse {
            writeHttpResponse(socket, 400, """{"error":"base64 decode failed"}""")
            return@withContext
        }

        val ok = chunkStorage.storeChunk(chunkId, data)
        val resp = JsonObject().apply {
            addProperty("stored", ok)
            addProperty("chunk_id", chunkId)
            addProperty("size_bytes", data.size)
        }
        writeHttpResponse(socket, if (ok) 200 else 500, gson.toJson(resp))
    }

    private fun handleChunkRetrieve(socket: Socket, requestLine: String) {
        // GET /chunk/{chunkId}
        val chunkId = requestLine.removePrefix("GET /chunk/").substringBefore(" ")
        val data = chunkStorage.retrieveChunk(chunkId)
        if (data == null) {
            writeHttpResponse(socket, 404, """{"error":"chunk not found"}""")
            return
        }
        val resp = JsonObject().apply {
            addProperty("chunk_id", chunkId)
            addProperty("data_b64", Base64.encodeToString(data, Base64.NO_WRAP))
            addProperty("size_bytes", data.size)
        }
        writeHttpResponse(socket, 200, gson.toJson(resp))
    }

    private fun handleChunkDelete(socket: Socket, requestLine: String) {
        val chunkId = requestLine.removePrefix("DELETE /chunk/").substringBefore(" ")
        val ok = chunkStorage.deleteChunk(chunkId)
        writeHttpResponse(socket, if (ok) 200 else 404,
            if (ok) """{"deleted":true,"chunk_id":"$chunkId"}""" else """{"error":"chunk not found"}""")
    }

    private fun handleChunkList(socket: Socket) {
        val chunks = chunkStorage.listChunks()
        val usedMb = chunkStorage.getTotalUsedMb()
        val resp = JsonObject().apply {
            addProperty("chunk_count", chunks.size)
            addProperty("used_mb", usedMb)
            val arr = com.google.gson.JsonArray()
            chunks.forEach { arr.add(it) }
            add("chunks", arr)
        }
        writeHttpResponse(socket, 200, gson.toJson(resp))
    }

    private suspend fun handleSecureQuery(
        socket: Socket,
        reader: BufferedReader,
        contentLength: Int
    ) = withContext(Dispatchers.IO) {
        val bodyChars = CharArray(contentLength)
        reader.read(bodyChars, 0, contentLength)
        val bodyJson = String(bodyChars)

        val json = runCatching {
            gson.fromJson(bodyJson, JsonObject::class.java)
        }.getOrElse {
            writeHttpResponse(socket, 400, """{"error":"invalid json"}""")
            return@withContext
        }

        val encryptedQueryB64 = json.get("encrypted_query_base64")?.asString ?: run {
            writeHttpResponse(socket, 400, """{"error":"encrypted_query_base64 required"}""")
            return@withContext
        }

        val decryptedPrompt = runCatching {
            trustZoneKeyManager.decryptResponse(encryptedQueryB64)
        }.getOrElse {
            // Cryptographic rejection: this query was not encrypted for this device's key.
            // This is not a routing error — it is a cryptographic proof of role mismatch.
            Log.w(TAG, "SecureQuery: rejected — not addressable by this device's TrustZone key")
            writeHttpResponse(socket, 403, """{"error":"cryptographic_rejection","reason":"query not addressed to this device key"}""")
            return@withContext
        }

        if (!wakeLock.isHeld) wakeLock.acquire(30_000L)
        val plainResponse = runInference(decryptedPrompt)
        if (wakeLock.isHeld) wakeLock.release()

        queriesToday.incrementAndGet()

        val operatorEmail = prefs.getString("operator_email", "") ?: ""
        val requesterPubKeyB64 = json.get("requester_public_key_base64")?.asString

        val responsePayload = if (!requesterPubKeyB64.isNullOrBlank()) {
            runCatching {
                trustZoneKeyManager.encryptQuery(plainResponse, requesterPubKeyB64)
            }.getOrElse { plainResponse }
        } else {
            plainResponse
        }

        val responseJson = JsonObject().apply {
            addProperty("encrypted_response_base64", responsePayload)
            addProperty("device_id", deviceId)
            addProperty("hardware_backed", trustZoneKeyManager.isHardwareBacked(operatorEmail))
        }
        writeHttpResponse(socket, 200, gson.toJson(responseJson))
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
            403 -> "Forbidden"
            404 -> "Not Found"
            500 -> "Internal Server Error"
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
