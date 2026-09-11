package com.fleetmind.agent

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.os.PowerManager
import android.os.StatFs
import android.util.Log
import java.io.File
import java.io.RandomAccessFile

class TelemetryCollector(private val context: Context) {

    companion object {
        private const val TAG = "TelemetryCollector"
    }

    data class DeviceTelemetry(
        val batteryLevel: Int,
        val isCharging: Boolean,
        val estimatedRuntimeMins: Int?,
        val cpuTempCelsius: Float?,
        val thermalState: String,
        val wifiRssiDbm: Int?,
        val networkBandwidthMbps: Float?,
        val cpuUsagePercent: Float?,
        val ramAvailableMb: Int,
        val availableStorageMb: Long,
    )

    fun collect(): DeviceTelemetry {
        val batteryLevel = getBatteryLevel()
        val isCharging = isCharging()
        return DeviceTelemetry(
            batteryLevel = batteryLevel,
            isCharging = isCharging,
            estimatedRuntimeMins = estimateRuntimeMins(batteryLevel, isCharging),
            cpuTempCelsius = getCpuTempCelsius(),
            thermalState = getThermalState(),
            wifiRssiDbm = getWifiRssiDbm(),
            networkBandwidthMbps = getNetworkBandwidthMbps(),
            cpuUsagePercent = getCpuUsagePercent(),
            ramAvailableMb = getRamAvailableMb(),
            availableStorageMb = getAvailableStorageMb(),
        )
    }

    fun getBatteryLevel(): Int {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            ?: return 100
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        if (level < 0 || scale <= 0) return 100
        return ((level.toFloat() / scale.toFloat()) * 100).toInt()
    }

    fun isCharging(): Boolean {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            ?: return false
        val status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        return status == BatteryManager.BATTERY_STATUS_CHARGING ||
               status == BatteryManager.BATTERY_STATUS_FULL
    }

    private fun estimateRuntimeMins(batteryLevel: Int, isCharging: Boolean): Int? {
        if (isCharging) return null
        // Rough estimate: assume 3% battery per hour of idle inference load
        // A fully loaded inference phone burns ~5-8% per hour
        val drainPercentPerHour = 5
        return ((batteryLevel.toFloat() / drainPercentPerHour) * 60).toInt().takeIf { it > 0 }
    }

    fun getCpuTempCelsius(): Float? {
        // Try thermal zone files (available on most Android kernels)
        val thermalDirs = File("/sys/class/thermal/").listFiles()
            ?.filter { it.name.startsWith("thermal_zone") }
            ?: emptyList()

        val temps = thermalDirs.mapNotNull { dir ->
            try {
                val typeFile = File(dir, "type")
                val tempFile = File(dir, "temp")
                if (!typeFile.exists() || !tempFile.exists()) return@mapNotNull null
                val type = typeFile.readText().trim()
                // Skip non-CPU thermal zones
                if (!type.contains("cpu", ignoreCase = true) &&
                    !type.contains("soc", ignoreCase = true) &&
                    !type.contains("cpu0", ignoreCase = true)) return@mapNotNull null
                val rawTemp = tempFile.readText().trim().toLongOrNull() ?: return@mapNotNull null
                // Android reports millidegrees or degrees depending on kernel
                if (rawTemp > 1000) rawTemp / 1000.0f else rawTemp.toFloat()
            } catch (_: Exception) { null }
        }

        return if (temps.isNotEmpty()) temps.max() else null
    }

    fun getThermalState(): String {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
            return when (pm.currentThermalStatus) {
                PowerManager.THERMAL_STATUS_NONE -> "NONE"
                PowerManager.THERMAL_STATUS_LIGHT -> "LIGHT"
                PowerManager.THERMAL_STATUS_MODERATE -> "MODERATE"
                PowerManager.THERMAL_STATUS_SEVERE -> "SEVERE"
                PowerManager.THERMAL_STATUS_CRITICAL -> "CRITICAL"
                PowerManager.THERMAL_STATUS_EMERGENCY -> "CRITICAL"
                PowerManager.THERMAL_STATUS_SHUTDOWN -> "CRITICAL"
                else -> "NONE"
            }
        }
        // Pre-Q: infer from CPU temp
        val temp = getCpuTempCelsius() ?: return "NONE"
        return when {
            temp >= 50f -> "CRITICAL"
            temp >= 45f -> "SEVERE"
            temp >= 42f -> "MODERATE"
            temp >= 38f -> "LIGHT"
            else -> "NONE"
        }
    }

    fun getWifiRssiDbm(): Int? {
        val wm = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            ?: return null
        val info = wm.connectionInfo ?: return null
        val rssi = info.rssi
        return if (rssi == Int.MIN_VALUE || rssi == 0) null else rssi
    }

    fun getNetworkBandwidthMbps(): Float? {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return null
        val network = cm.activeNetwork ?: return null
        val caps = cm.getNetworkCapabilities(network) ?: return null
        val kbps = caps.linkDownstreamBandwidthKbps
        return if (kbps > 0) kbps / 1000f else null
    }

    fun getCpuUsagePercent(): Float? {
        // Read /proc/stat twice with a small gap to compute delta
        return try {
            fun readCpuStats(): Pair<Long, Long> {
                val line = File("/proc/stat").readLines().firstOrNull { it.startsWith("cpu ") }
                    ?: return 0L to 0L
                val parts = line.trim().split("\\s+".toRegex()).drop(1).mapNotNull { it.toLongOrNull() }
                val idle = parts.getOrElse(3) { 0L }
                val total = parts.sum()
                return idle to total
            }
            val (idle1, total1) = readCpuStats()
            Thread.sleep(200)
            val (idle2, total2) = readCpuStats()
            val deltaTotal = total2 - total1
            val deltaIdle = idle2 - idle1
            if (deltaTotal <= 0) return null
            ((deltaTotal - deltaIdle).toFloat() / deltaTotal.toFloat()) * 100f
        } catch (_: Exception) { null }
    }

    fun getRamAvailableMb(): Int {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val mi = ActivityManager.MemoryInfo()
        am.getMemoryInfo(mi)
        return (mi.availMem / 1024 / 1024).toInt()
    }

    fun getAvailableStorageMb(): Long {
        val stat = StatFs(context.filesDir.absolutePath)
        return stat.availableBlocksLong * stat.blockSizeLong / 1024 / 1024
    }
}
