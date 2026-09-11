package com.fleetmind.agent

import android.content.Context
import android.util.Base64
import android.util.Log
import com.google.gson.Gson
import com.google.gson.JsonObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

/**
 * Pipeline-parallel model sharding.
 *
 * Architecture:
 *   [Backend] ──tokens──▶ [Shard 0: layers 0..N/k] ──hidden_state──▶
 *   [Shard 1: layers N/k..2N/k] ──hidden_state──▶ ... ──▶
 *   [Shard k-1: layers ..N + lm_head] ──logits──▶ [Backend samples next token]
 *
 * Each phone only loads its assigned layer range from the GGUF model file.
 * Hidden states are raw float32 arrays, base64-encoded for HTTP transport.
 *
 * The backend (shard_coordinator.py) orchestrates the pipeline and assigns
 * shard indices to devices based on available RAM.
 */
class ShardedInference(private val context: Context) {

    companion object {
        private const val TAG = "ShardedInference"

        // JNI entry points in libfleetmind_shard.so
        // This native library implements llama.cpp with layer-range support.
        // See model-runner/shard/ for the CMakeLists and C++ source.
        @JvmStatic external fun nativeInitShard(
            modelPath: String,
            startLayer: Int,
            endLayer: Int,
            isFinalShard: Boolean,
            threads: Int,
        ): Long  // returns context handle, 0 on failure

        @JvmStatic external fun nativeForward(
            ctx: Long,
            inputData: ByteArray,   // float32 hidden states (or int32 token IDs for shard 0)
            isFirstShard: Boolean,
        ): ByteArray  // float32 hidden states (or float32 logits for final shard)

        @JvmStatic external fun nativeDestroyContext(ctx: Long)

        init {
            try {
                System.loadLibrary("fleetmind_shard")
            } catch (e: UnsatisfiedLinkError) {
                Log.w(TAG, "Native shard library not found — sharded inference unavailable: ${e.message}")
            }
        }
    }

    data class ShardConfig(
        val shardIndex: Int,           // 0-based index of this shard in the pipeline
        val totalShards: Int,          // total number of shards
        val layerStart: Int,           // first transformer layer this shard owns
        val layerEnd: Int,             // last transformer layer (exclusive)
        val isFinalShard: Boolean,     // true if this shard produces logits
        val modelPath: String,         // path to the GGUF shard file on device
        val nextShardUrl: String?,     // HTTP URL of the next shard device (null if final)
        val hiddenDim: Int = 8192,     // model hidden dimension (8192 for 70B Llama)
        val threads: Int = 4,
    )

    @Volatile private var config: ShardConfig? = null
    @Volatile private var nativeCtx: Long = 0L
    private val gson = Gson()
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    fun isConfigured(): Boolean = config != null && nativeCtx != 0L

    fun configure(newConfig: ShardConfig): Boolean {
        val prev = nativeCtx
        if (prev != 0L) nativeDestroyContext(prev)

        return try {
            val ctx = nativeInitShard(
                newConfig.modelPath,
                newConfig.layerStart,
                newConfig.layerEnd,
                newConfig.isFinalShard,
                newConfig.threads,
            )
            if (ctx == 0L) {
                Log.e(TAG, "nativeInitShard returned 0 — model load failed for ${newConfig.modelPath}")
                return false
            }
            nativeCtx = ctx
            config = newConfig
            Log.i(TAG, "Shard ${newConfig.shardIndex}/${newConfig.totalShards} configured: " +
                    "layers ${newConfig.layerStart}..${newConfig.layerEnd}, " +
                    "final=${newConfig.isFinalShard}")
            true
        } catch (e: UnsatisfiedLinkError) {
            Log.w(TAG, "Shard native library missing — using stub forward pass")
            // Install stub so the HTTP server can still respond (for integration testing)
            config = newConfig
            nativeCtx = -1L
            true
        }
    }

    /**
     * Run one forward pass through this shard's layer range.
     *
     * @param inputData Raw bytes:
     *   - Shard 0: int32 token IDs (4 bytes each, little-endian)
     *   - Shard N>0: float32 hidden states from previous shard
     * @return Raw bytes:
     *   - Non-final shards: float32 hidden states for the next shard
     *   - Final shard: float32 logits over vocabulary (typically 128K floats for Llama 3)
     */
    suspend fun forward(inputData: ByteArray): ByteArray = withContext(Dispatchers.Default) {
        val cfg = config ?: error("ShardedInference not configured")
        val ctx = nativeCtx

        if (ctx == -1L) {
            // Stub: return zero-filled float32 array of the right size
            Log.w(TAG, "Stub forward pass (no native library)")
            return@withContext ByteArray(cfg.hiddenDim * 4) // float32 zeros
        }

        nativeForward(ctx, inputData, cfg.shardIndex == 0)
    }

    /**
     * Called by the backend coordinator to run inference through the full pipeline.
     * Only shard 0 calls this — it drives the pipeline to completion.
     *
     * @param tokenIds Input token IDs as int32 little-endian bytes
     * @return Logits as float32 bytes from the final shard
     */
    suspend fun runPipeline(tokenIds: ByteArray): ByteArray = withContext(Dispatchers.IO) {
        val cfg = config ?: error("ShardedInference not configured")

        // This device runs its own layers
        var current = forward(tokenIds)

        // If there's a next shard, forward the hidden state to it
        val nextUrl = cfg.nextShardUrl
        if (!cfg.isFinalShard && nextUrl != null) {
            current = forwardToNextShard(nextUrl, current)
        }

        current
    }

    private suspend fun forwardToNextShard(url: String, hiddenState: ByteArray): ByteArray =
        withContext(Dispatchers.IO) {
            val payload = JsonObject().apply {
                addProperty("hidden_state_b64", Base64.encodeToString(hiddenState, Base64.NO_WRAP))
                addProperty("is_token_ids", false)
            }
            val body = gson.toJson(payload).toRequestBody("application/json".toMediaType())
            val request = Request.Builder()
                .url("$url/shard/forward")
                .post(body)
                .build()

            http.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    Log.e(TAG, "Next shard at $url returned ${response.code}")
                    return@use ByteArray(0)
                }
                val raw = response.body?.string() ?: return@use ByteArray(0)
                val json = gson.fromJson(raw, JsonObject::class.java)
                val b64 = json.get("output_b64")?.asString ?: return@use ByteArray(0)
                Base64.decode(b64, Base64.NO_WRAP)
            }
        }

    fun destroy() {
        val ctx = nativeCtx
        if (ctx > 0L) nativeDestroyContext(ctx)
        nativeCtx = 0L
        config = null
    }
}
