package com.fleetmind.agent

import android.content.Context
import android.util.Log
import java.io.File

class ChunkStorage(private val context: Context) {

    companion object {
        private const val TAG = "ChunkStorage"
        private const val CHUNK_DIR = "fleet_chunks"
    }

    private val chunkDir: File by lazy {
        File(context.filesDir, CHUNK_DIR).also { it.mkdirs() }
    }

    fun storeChunk(chunkId: String, data: ByteArray): Boolean {
        return try {
            chunkFile(chunkId).writeBytes(data)
            Log.d(TAG, "Stored chunk $chunkId (${data.size} bytes)")
            true
        } catch (e: Exception) {
            Log.e(TAG, "Failed to store chunk $chunkId: ${e.message}")
            false
        }
    }

    fun retrieveChunk(chunkId: String): ByteArray? {
        val file = chunkFile(chunkId)
        if (!file.exists()) return null
        return try {
            file.readBytes()
        } catch (e: Exception) {
            Log.e(TAG, "Failed to retrieve chunk $chunkId: ${e.message}")
            null
        }
    }

    fun deleteChunk(chunkId: String): Boolean {
        val file = chunkFile(chunkId)
        return file.exists() && file.delete()
    }

    fun listChunks(): List<String> =
        chunkDir.listFiles()?.map { it.name } ?: emptyList()

    fun getTotalUsedBytes(): Long =
        chunkDir.walkTopDown().filter { it.isFile }.sumOf { it.length() }

    fun getTotalUsedMb(): Long = getTotalUsedBytes() / 1024 / 1024

    private fun chunkFile(chunkId: String): File {
        // Sanitize to prevent path traversal
        val safe = chunkId.replace(Regex("[^a-zA-Z0-9_\\-]"), "_")
        return File(chunkDir, safe)
    }
}
