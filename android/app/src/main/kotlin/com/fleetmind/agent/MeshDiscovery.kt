package com.fleetmind.agent

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import java.util.concurrent.ConcurrentHashMap

data class MeshPeer(val host: String, val port: Int, val name: String)

class MeshDiscovery(private val context: Context) {

    companion object {
        const val SERVICE_TYPE = "_fleetmind._tcp."
        const val SERVICE_NAME_PREFIX = "FleetMind-"
    }

    private val nsdManager by lazy { context.getSystemService(Context.NSD_SERVICE) as NsdManager }
    private val peers = ConcurrentHashMap<String, MeshPeer>()

    @Volatile private var registered = false
    @Volatile private var discovering = false
    private var registrationListener: NsdManager.RegistrationListener? = null
    private var discoveryListener: NsdManager.DiscoveryListener? = null

    fun start() {
        registerService()
        startDiscovery()
    }

    fun stop() {
        runCatching { if (registered) nsdManager.unregisterService(registrationListener) }
        runCatching { if (discovering) nsdManager.stopServiceDiscovery(discoveryListener) }
        peers.clear()
        registered = false
        discovering = false
    }

    fun getAvailablePeer(): MeshPeer? = peers.values.firstOrNull()

    fun getPeers(): List<MeshPeer> = peers.values.toList()

    private fun registerService() {
        val deviceId = android.provider.Settings.Secure.getString(
            context.contentResolver,
            android.provider.Settings.Secure.ANDROID_ID
        )
        val info = NsdServiceInfo().apply {
            serviceName = "$SERVICE_NAME_PREFIX${deviceId.take(8)}"
            serviceType = SERVICE_TYPE
            port = FleetMindService.LOCAL_PORT
        }

        registrationListener = object : NsdManager.RegistrationListener {
            override fun onRegistrationFailed(info: NsdServiceInfo, code: Int) {
                registered = false
            }
            override fun onUnregistrationFailed(info: NsdServiceInfo, code: Int) {}
            override fun onServiceRegistered(info: NsdServiceInfo) {
                registered = true
            }
            override fun onServiceUnregistered(info: NsdServiceInfo) {
                registered = false
            }
        }

        nsdManager.registerService(info, NsdManager.PROTOCOL_DNS_SD, registrationListener)
    }

    private fun startDiscovery() {
        discoveryListener = object : NsdManager.DiscoveryListener {
            override fun onStartDiscoveryFailed(type: String, code: Int) {
                discovering = false
            }
            override fun onStopDiscoveryFailed(type: String, code: Int) {}
            override fun onDiscoveryStarted(type: String) {
                discovering = true
            }
            override fun onDiscoveryStopped(type: String) {
                discovering = false
            }
            override fun onServiceFound(info: NsdServiceInfo) {
                if (info.serviceType.trimEnd('.') == SERVICE_TYPE.trimEnd('.')) {
                    resolveService(info)
                }
            }
            override fun onServiceLost(info: NsdServiceInfo) {
                peers.remove(info.serviceName)
            }
        }

        nsdManager.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, discoveryListener)
    }

    private fun resolveService(info: NsdServiceInfo) {
        nsdManager.resolveService(info, object : NsdManager.ResolveListener {
            override fun onResolveFailed(info: NsdServiceInfo, code: Int) {}
            override fun onServiceResolved(info: NsdServiceInfo) {
                val host = info.host?.hostAddress ?: return
                val peer = MeshPeer(
                    host = host,
                    port = info.port,
                    name = info.serviceName
                )
                peers[info.serviceName] = peer
            }
        })
    }
}
