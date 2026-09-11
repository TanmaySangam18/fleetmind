<div align="center">

<h1>FleetMind</h1>

[![Stars](https://img.shields.io/github/stars/fleetmind/fleetmind?style=flat-square&color=00ff87)](https://github.com/TanmaySangam18/fleetmind/stargazers)
[![License: MIT](https://img.shields.io/badge/License-MIT-00ff87.svg?style=flat-square)](LICENSE)
[![Platform: Android](https://img.shields.io/badge/Platform-Android%208.0%2B-3ddc84?style=flat-square&logo=android)](https://developer.android.com)
[![Powered by llama.cpp](https://img.shields.io/badge/Inference-llama.cpp-ff6b35?style=flat-square)](https://github.com/ggerganov/llama.cpp)

**The world's first enterprise software that turns your employee phones into a private AI data center.**

</div>

---

Your company has been renting AI infrastructure it already owns.

Every Android phone in your employee fleet has a Snapdragon or MediaTek chip capable of running a 1–3B parameter language model. FleetMind pools those chips across your corporate WiFi into a single inference mesh — then exposes a drop-in OpenAI-compatible API that your internal tools point to instead of `api.openai.com`. Nothing leaves the building.

```
[Employee Phone 1] ─┐
[Employee Phone 2] ─┤
[Employee Phone 3] ─┼─── FleetMind Mesh ─── OpenAI-Compatible API :8080 ─── Company Apps
[Employee Phone 4] ─┤        (Corporate WiFi · mDNS · round-robin)
[Employee Phone N] ─┘
```

---

## Key Numbers

| Metric | Value |
|--------|-------|
| Queries handled / month (500-device fleet) | **2.3M** |
| Cloud AI bill | **$0** |
| Setup time via MDM | **< 5 min** |
| Data that leaves your network | **0%** |
| New hardware required | **none** |

---

## How It Works

**1. IT pushes the APK via MDM — zero-touch, takes 5 minutes.**

Upload the FleetMind APK to Jamf, Intune, or Workspace ONE. Push a managed config with your license key. Phones receive the agent silently, no user interaction required.

**2. Phones form a mesh automatically — no config needed.**

The agent registers itself on the corporate WiFi using mDNS (`_fleetmind._tcp`). Devices discover each other, load balance queries via round-robin, and send heartbeats every 60 seconds. The fleet self-heals if devices go offline.

**3. Point your apps at FleetMind instead of OpenAI — one line of code.**

```diff
- base_url = "https://api.openai.com/v1"
+ base_url = "http://your-company.local:8080/v1"
```

That's it. Every internal tool, chatbot, and summarization pipeline you built on OpenAI's API works immediately.

---

## Quick Start

```bash
git clone https://github.com/TanmaySangam18/fleetmind
cd fleetmind
cp backend/.env.example backend/.env
docker compose up
# Open http://localhost:3000
# Download the Android APK from Releases
# Enter your trial key from the dashboard
# Your phone appears in the mesh within 60 seconds
```

Test the API:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.2:1b",
    "messages": [{"role": "user", "content": "Summarize this support ticket: ..."}]
  }'
```

---

## Why Not Just Use [X]?

| Tool | What it does | What it doesn't do |
|------|-------------|-------------------|
| **Exo Labs** | Pools consumer devices (Mac, Linux, iPhone) into a mesh | No MDM integration, no enterprise deployment, hobbyist tool only |
| **RunAnywhere** | Manages AI on phones | Each device runs in isolation — does **not** pool compute across devices |
| **Ollama** | Local inference on a single machine | No mesh, no multi-device, no MDM |
| **Apple Intelligence** | Per-device inference | Data routed to Apple's servers; no Android; no enterprise API |
| **FleetMind** | MDM deployment + collective compute pooling + zero egress + OpenAI-compatible API | — |

No one else has all four. That's the product.

---

## Architecture

### Mesh Layer (Android Agent)

- **Discovery:** Android NSD (`NsdManager`) registers each device as `_fleetmind._tcp` on the local network. Peers discover each other in under 10 seconds.
- **Inference:** Local HTTP server on port `11434` exposes an Ollama-compatible `/api/generate` endpoint. Inference runs via llama.cpp JNI bindings (see [`android/`](android/)).
- **Routing:** The FleetMind server maintains a live device registry updated by 60-second heartbeats. Queries are distributed round-robin across active devices.
- **Health:** Any device that misses two consecutive heartbeats is removed from the rotation. Queries in-flight are retried on the next available device.
- **Battery guard:** If a device battery drops below 20%, the local inference server returns HTTP 503. The heartbeat continues — the device stays visible in the dashboard but is excluded from query routing.

### Server Layer

```
FleetMind Server (FastAPI + SQLite)
├── POST /api/device/heartbeat     — device registration and keep-alive
├── GET  /api/dashboard/:key       — fleet status, query counts, savings
├── POST /api/query                — route a query to an active device
└── POST /v1/chat/completions      — OpenAI-compatible endpoint (proxies to mesh)
```

### Web Dashboard (Next.js)

Live fleet view — active devices, queries today, estimated cloud cost avoided.

---

## Supported Models

Models are distributed to devices as GGUF files via MDM file distribution or pulled via `adb push`.

| Model | Size | Minimum Device |
|-------|------|----------------|
| Llama 3.2 1B (Q4_K_M) | ~700 MB | Any Android 8.0+ phone |
| Gemma 3 1B (Q4_K_M) | ~700 MB | Any Android 8.0+ phone |
| Llama 3.2 3B (Q4_K_M) | ~2 GB | Flagship Android (12 GB RAM+) |
| Phi-4-mini (Q4_K_M) | ~2.5 GB | Flagship Android (12 GB RAM+) |

For mixed fleets: FleetMind automatically routes queries to devices running a compatible model. Low-end devices run 1B, high-end devices run 3B.

---

## MDM Deployment

### Jamf Pro

1. **Devices → Mobile Device Apps → + → In-House App** → upload `.apk`
2. **Scope** to All Managed Devices (or a specific group)
3. **App Configuration** → push managed config:

```json
{
  "kind": "androidenterprise#managedConfiguration",
  "productId": "app:com.fleetmind.agent",
  "managedProperty": [
    { "key": "license_key", "valueString": "FM-XXXX-XXXX-XXXX" },
    { "key": "server_url",  "valueString": "http://your-company.local:8080" }
  ]
}
```

### Microsoft Intune

1. **Apps → Android → Add → Line-of-business app** → upload `.apk`
2. **App configuration policies → Managed devices → Add** with the same JSON above under AppConfig

### VMware Workspace ONE

1. **Apps → Public / Internal → Add → Internal** → upload `.apk`
2. **Assignment → App Configuration** → push the managed config

### ADB (for testing a single device)

```bash
adb shell am start -n com.fleetmind.agent/.MainActivity \
  --es license_key "FM-XXXX-XXXX-XXXX" \
  --es server_url "http://localhost:8080"
```

---

## Self-Host vs. Cloud Dashboard

**Self-host (default):** Run `docker compose up` on any server on your corporate network. Everything stays inside your perimeter. No external connections.

**Cloud-managed dashboard:** `fleetmind.io` — coming soon. Enterprise tier with SSO, audit logs, and multi-site fleet management. The inference mesh still runs on-prem; only fleet metadata (device count, query count) touches the cloud.

---

## Repo Structure

```
fleetmind/
├── android/          # Kotlin MDM agent (FleetMindService, MeshDiscovery, HeartbeatWorker)
├── backend/          # FastAPI server (device registry, query routing, license management)
│   ├── main.py
│   ├── database.py
│   ├── license.py
│   └── requirements.txt
├── web/              # Next.js dashboard (fleet view, registration, pricing)
│   └── app/
│       ├── dashboard/
│       ├── purchase/
│       └── register/
├── model-runner/     # llama.cpp build scripts for arm64-v8a / armeabi-v7a
├── docker-compose.yml
└── README.md
```

---

## Roadmap

- [ ] iOS support — waiting on Apple MDM background compute entitlements
- [ ] llama.cpp compiled directly into APK (currently bridges to Ollama-compatible local server)
- [ ] Homomorphic encryption for cross-company mesh federation
- [ ] Windows / macOS desktop agent (for companies without MDM-managed phones)
- [ ] Automatic GGUF distribution via MDM file management
- [ ] Per-model routing — route code tasks to Phi-4, summarization to Llama 3.2
- [ ] Prometheus metrics endpoint for fleet observability

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

PRs welcome. The most valuable contributions right now are:

- llama.cpp JNI integration in [`android/app/src/main/java/com/fleetmind/agent/`](android/)
- OpenAI-compatible proxy completeness (`/v1/completions`, `/v1/embeddings`)
- iOS Simulator support for local development

---

## License

MIT — see [LICENSE](LICENSE).

---

<div align="center">

**Star History**

[![Star History Chart](https://api.star-history.com/svg?repos=fleetmind/fleetmind&type=Date)](https://star-history.com/#fleetmind/fleetmind&Date)

</div>
