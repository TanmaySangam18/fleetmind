# FleetMind Android MDM Agent

A background Kotlin app deployed via MDM to employee phones. Runs a local Ollama-compatible AI inference server (port 11434) and joins the company's private FleetMind mesh network via mDNS.

---

## MDM Deployment

### 1. Upload APK to MDM Console

| MDM Platform | Steps |
|---|---|
| **Jamf Pro** | Devices → Mobile Device Apps → + → In-House App → Upload `.apk` |
| **VMware Workspace ONE** | Apps → Public/Internal → Add → Internal → Upload `.apk` |
| **Microsoft Intune** | Apps → Android → Add → Line-of-business app → Upload `.apk` |

### 2. Push License Key via Managed Configuration

All MDM platforms support Android Managed Configurations (AppConfig). Push these keys:

```json
{
  "kind": "androidenterprise#managedConfiguration",
  "productId": "app:com.fleetmind.agent",
  "managedProperty": [
    { "key": "license_key", "valueString": "FM-XXXX-XXXX-XXXX" },
    { "key": "server_url",  "valueString": "https://api.fleetmind.io" }
  ]
}
```

For zero-touch enrollment, IT can also pre-configure via ADB:
```bash
adb shell am start -n com.fleetmind.agent/.MainActivity \
  --es license_key "FM-XXXX-XXXX-XXXX" \
  --es server_url "https://api.fleetmind.io"
```

### 3. App Auto-Starts on Boot

`BootReceiver` listens for `BOOT_COMPLETED` and `LOCKED_BOOT_COMPLETED`. If a license key is saved, `FleetMindService` starts automatically — no user interaction required.

### 4. Devices Appear in FleetMind Dashboard Within 60 Seconds

Each device sends a heartbeat every 60 seconds to `{server_url}/api/device/heartbeat` containing:
- `license_key`
- `device_id` (Android ID)
- `device_model`
- `queries_processed`
- `uptime_seconds`

---

## Architecture

```
┌─────────────────────────────────────────────┐
│              FleetMindService               │
│  (Foreground Service — START_STICKY)        │
│                                             │
│  ┌─────────────┐   ┌────────────────────┐   │
│  │  Heartbeat  │   │  Local HTTP Server  │   │
│  │  (60s loop) │   │  :11434/api/generate│   │
│  └─────────────┘   └────────────────────┘   │
│                             │               │
│                    ┌────────▼────────┐      │
│                    │  runInference() │      │
│                    │  (llama.cpp JNI │      │
│                    │   stub for MVP) │      │
│                    └─────────────────┘      │
│                                             │
│  ┌──────────────────────────────────────┐   │
│  │         MeshDiscovery (NSD)          │   │
│  │  Register: _fleetmind._tcp           │   │
│  │  Discover peers → load balance       │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

## Local API (Ollama-Compatible)

```bash
curl -X POST http://<device-ip>:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Summarize this incident report: ..."}'
```

Response:
```json
{
  "model": "fleetmind-local",
  "response": "...",
  "done": true
}
```

## Battery Safety

If device battery drops below 20%, the inference server returns HTTP 503 and pauses accepting queries. The heartbeat continues so the device remains visible in the dashboard.

## Connecting llama.cpp (Production)

Replace the stub in `FleetMindService.runInference()` with JNI calls to llama.cpp:

1. Build `llama.cpp` for `arm64-v8a` / `armeabi-v7a` using the Android NDK
2. Place `.so` files in `app/src/main/jniLibs/`
3. Add a `LlamaCpp.kt` JNI wrapper object with `System.loadLibrary("llama")`
4. Swap the comment block in `runInference()` for real calls

## Minimum Requirements

- Android 8.0+ (API 26)
- Wi-Fi on the company network for mesh discovery
- ~2 GB free storage for the GGUF model file (pushed separately via MDM file distribution)
