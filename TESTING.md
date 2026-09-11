# Testing FleetMind with 1 Mac + 1 Android + 2 iPhones

## What you're building
- Mac = backend + AI brain (Ollama) + 1 mesh node
- Android = 1 mesh node (native app)
- iPhone 1 = 1 mesh node (browser)
- iPhone 2 = 1 mesh node (browser)

**Total: 4 nodes, live mesh**

---

## Step 1 — Start the backend and AI (Mac, ~5 min)

```bash
cd ~/fleetmind
docker compose up -d
brew install ollama
ollama pull llama3.2:1b
ollama serve &
```

**Then open http://localhost:3000 in your browser.**

You should see the FleetMind homepage. Click **Start 7-Day Free Trial**, fill in:
- Company name (anything)
- Email address
- Employee count (e.g. 10)
- Company registration number (e.g. TEST-001)

Click **Register**. Copy the `trial_token` from the confirmation screen — you'll need it for every device.

> Screenshot description: A dark screen with a green "Trial activated" banner at the top.
> Below it: a box showing your trial token (long hex string). Copy this string.

---

## Step 2 — Activate your trial and get the license key

```bash
curl -s -X POST http://localhost:8000/api/activate-trial \
  -H "Content-Type: application/json" \
  -d '{"trial_token":"YOUR_TRIAL_TOKEN"}' | python3 -m json.tool
```

The response includes `trial_token` — this doubles as your license key for all heartbeat calls during the trial period.

> Screenshot description: Terminal output showing `"trial_expiry": "2026-09-17T..."` and `"days_remaining": 7`.

---

## Step 3 — Start the Mac node (Mac, ~2 min)

```bash
cd ~/fleetmind/mac-node
pip3 install -r requirements.txt
python3 agent.py --license YOUR_TRIAL_TOKEN --backend http://localhost:8000
```

You should immediately see:

```
FleetMind Mac Node
==================
  Device ID   : mac-node-your-hostname
  Backend     : http://localhost:8000
  License     : YOUR_TRI********
  Ollama proxy: http://0.0.0.0:11435/generate
  mDNS registered: FleetMind-Mac-your-hostname._fleetmind._tcp.local.
  Local Ollama proxy listening on port 11435
  Mac node active — 0 queries processed — mesh: healthy
```

> Screenshot description: Terminal split-pane. Left pane: `docker compose up -d` output with green checkmarks. Right pane: Mac node agent printing its status line every 60 seconds.

Open the dashboard at **http://localhost:3000/dashboard/YOUR_TRIAL_TOKEN** — within 60 seconds the Mac appears as a row in the Device Fleet table with status **active** (green dot).

---

## Step 4 — Add iPhones to the mesh (2 min each)

First, find your Mac's local IP address:

- **macOS Ventura/Sonoma**: System Settings → Network → Wi-Fi → Details → IP Address
- **Terminal shortcut**:
  ```bash
  ipconfig getifaddr en0
  ```
  Example output: `192.168.1.42`

Make sure all phones are on the **same Wi-Fi network** as the Mac.

**On each iPhone, open Safari and go to:**

```
http://192.168.1.42:3000/node
```

(Replace `192.168.1.42` with your actual Mac IP.)

You will see the FleetMind Node setup screen (dark background, green accent).

1. Enter your trial token in the **License Key** field.
2. Set the Backend URL to `http://192.168.1.42:8000`.
3. Tap **Join Mesh**.

> Screenshot description: iPhone screen showing a large green pulsing circle, title "FleetMind Node Active" in white, and three stat boxes at the bottom: "Queries Served: 0", "Uptime: 0s", "Status: Active". A thin bar at the bottom reads "Keep this page open. Closing removes your device from the mesh."

Within 60 seconds the iPhone appears in the dashboard. Repeat for the second iPhone.

**Important for iPhone Safari:** the page uses a hidden silent video to prevent the screen from locking. On iOS 16+ this should work automatically. If the screen still dims, go to Settings → Display & Brightness → Auto-Lock → set to "Never" for the duration of testing.

---

## Step 5 — Add Android to the mesh

See **[android/README.md](android/README.md)** for Android Studio setup instructions.

Quick summary:
1. Install Android Studio and open `~/fleetmind/android/`
2. Run on a physical device (USB debugging enabled)
3. Enter the same trial token and backend IP when prompted
4. The app registers automatically and appears in the dashboard

---

## Step 6 — Send a real query

With all 4 nodes active, fire a query from your Mac terminal:

```bash
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"license_key":"YOUR_TRIAL_TOKEN","prompt":"Summarise our Q3 revenue"}' \
  | python3 -m json.tool
```

Expected response:

```json
{
  "response": "Based on the available data, here is my analysis...",
  "device_id": "mac-node-your-hostname",
  "latency_ms": 142
}
```

> Screenshot description: Dashboard at http://localhost:3000/dashboard/YOUR_TRIAL_TOKEN showing:
> - **Active Devices: 4** (green number, top-left stat card)
> - **Queries Today: 1** (increments with each curl call)
> - **Money Saved: $0.004** (ticking up)
> - Device Fleet table: 4 rows — mac-node-hostname (active), browser-xxxx (active), browser-yyyy (active), android-xxxx (active) — all with green dots

To watch the round-robin routing in action, run the query 8 times:

```bash
for i in {1..8}; do
  curl -s -X POST http://localhost:8000/api/query \
    -H "Content-Type: application/json" \
    -d '{"license_key":"YOUR_TRIAL_TOKEN","prompt":"Query number '"$i"'"}' \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Query {$i} → {d['device_id']}\")"
done
```

You should see each of the 4 nodes receive 2 queries each.

---

## What success looks like

| Check | Expected |
|---|---|
| Dashboard active devices | **4** (Mac + 2 iPhones + Android) |
| Mac terminal | Prints "Mac node active — X queries processed — mesh: healthy" every 60 s |
| iPhone 1 Safari | Green pulsing dot, uptime counter ticking, no screen lock |
| iPhone 2 Safari | Same |
| Query response | Real text (not empty) with a `device_id` matching one of your nodes |
| Money Saved counter | Increases by $0.004 per query |

---

## Troubleshooting

**Dashboard shows 0 active devices after 90 seconds**
- Check the backend is running: `curl http://localhost:8000/api/dashboard/YOUR_TOKEN`
- Check the heartbeat endpoint manually:
  ```bash
  curl -X POST http://localhost:8000/api/device/heartbeat \
    -H "Content-Type: application/json" \
    -d '{"license_key":"YOUR_TOKEN","device_id":"test-1","device_model":"Test","queries_processed":0,"uptime_seconds":0}'
  ```

**iPhone can't reach the backend**
- Confirm both are on the same Wi-Fi (not guest network)
- Disable Mac firewall temporarily: System Settings → Network → Firewall → turn off
- Try pinging from iPhone (Settings → check IP) using a tool like [Network Analyzer](https://apps.apple.com/app/network-analyzer/id562315041)

**Mac node: "Ollama unreachable"**
- Confirm `ollama serve` is running in a separate terminal
- Test directly: `curl http://localhost:11434/api/generate -d '{"model":"llama3.2:1b","prompt":"hi","stream":false}'`

**Mac node: mDNS registration failed**
- This is non-fatal — the node still registers via HTTP heartbeat
- mDNS is only used for local device discovery, not required for the mesh to work
