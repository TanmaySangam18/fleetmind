package com.fleetmind.agent

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.fleetmind.agent.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val prefs by lazy { getSharedPreferences("fleetmind", MODE_PRIVATE) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        // MDM zero-touch: adb shell am start -n com.fleetmind.agent/.MainActivity
        //   --es license_key "FM-XXXX-XXXX-XXXX" --es server_url "https://api.fleetmind.io"
        intent.getStringExtra("license_key")?.let { key ->
            if (key.isNotBlank()) {
                binding.licenseKeyInput.setText(key)
                prefs.edit().putString("license_key", key).apply()
            }
        }
        intent.getStringExtra("server_url")?.let { url ->
            if (url.isNotBlank()) {
                binding.serverUrlInput.setText(url)
                prefs.edit().putString("server_url", url).apply()
            }
        }

        val savedKey = prefs.getString("license_key", "") ?: ""
        val savedUrl = prefs.getString("server_url", "https://api.fleetmind.io") ?: "https://api.fleetmind.io"
        val savedOllamaUrl = prefs.getString("ollama_url", "http://10.0.0.1:11434") ?: "http://10.0.0.1:11434"

        binding.licenseKeyInput.setText(savedKey)
        binding.serverUrlInput.setText(savedUrl)
        binding.ollamaBridgeUrlInput.setText(savedOllamaUrl)

        refreshStatus()

        binding.activateButton.setOnClickListener {
            val key = binding.licenseKeyInput.text.toString().trim()
            val url = binding.serverUrlInput.text.toString().trim()
            val ollamaUrl = binding.ollamaBridgeUrlInput.text.toString().trim()

            if (!isValidLicenseKey(key)) {
                Toast.makeText(this, "Invalid key format. Expected: FM-XXXX-XXXX-XXXX", Toast.LENGTH_LONG).show()
                return@setOnClickListener
            }
            if (url.isBlank()) {
                Toast.makeText(this, "Server URL cannot be empty", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            prefs.edit()
                .putString("license_key", key)
                .putString("server_url", url)
                .putString("ollama_url", ollamaUrl.ifBlank { "http://10.0.0.1:11434" })
                .apply()

            startFleetMindService()
            refreshStatus()
            Toast.makeText(this, "FleetMind Agent activated", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onResume() {
        super.onResume()
        refreshStatus()

        // Auto-activate if MDM pre-configured and service not running
        val key = prefs.getString("license_key", "") ?: ""
        if (key.isNotBlank() && !FleetMindService.isRunning) {
            startFleetMindService()
        }
    }

    private fun isValidLicenseKey(key: String): Boolean {
        return key.matches(Regex("FM-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}"))
    }

    private fun startFleetMindService() {
        val intent = Intent(this, FleetMindService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            ContextCompat.startForegroundService(this, intent)
        } else {
            startService(intent)
        }
    }

    private fun refreshStatus() {
        if (FleetMindService.isRunning) {
            binding.statusText.text = "Agent Active — ${FleetMindService.queriesToday} queries processed today"
            binding.activateButton.text = "Restart Agent"
        } else {
            binding.statusText.text = "Agent Inactive"
            binding.activateButton.text = "Activate & Start"
        }
        binding.queriesCounter.text = "Total queries: ${FleetMindService.queriesToday}"
    }
}
