# Contributing to FleetMind

Thanks for your interest. FleetMind is MIT-licensed and welcomes contributions.

---

## Running Locally

**Prerequisites:** Docker, Node.js 20+, Python 3.11+, Android Studio (for the agent)

```bash
git clone https://github.com/fleetmind/fleetmind
cd fleetmind

# Backend
cp backend/.env.example backend/.env
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# API available at http://localhost:8000

# Web (separate terminal)
cd web && npm install && npm run dev
# Dashboard at http://localhost:3000

# Or run both with Docker
docker compose up
```

**Android agent:** Open `android/` in Android Studio. Run on a physical device or emulator. Set `server_url` to your local machine's IP (not `localhost` — the device and your machine are on different network interfaces).

---

## Where to Contribute

The highest-impact areas right now:

- **`android/`** — llama.cpp JNI integration. `FleetMindService.runInference()` currently returns a stub. See the comment block for the swap-in instructions.
- **`backend/main.py`** — The `/v1/chat/completions` OpenAI-compatible endpoint is a stub. It needs to proxy to the mesh properly, handle streaming, and return the correct response shape.
- **`web/app/dashboard/`** — Real-time device map, per-device query distribution charts.
- **`model-runner/`** — Build scripts for compiling llama.cpp GGUF models for `arm64-v8a`.

---

## PR Guidelines

- Keep PRs focused. One feature or fix per PR.
- If you're adding a new endpoint, add a corresponding test in `backend/tests/` (pytest).
- Android code should be Kotlin. No Java.
- Do not commit `.env` files, `fleetmind.db`, or build artifacts (`*.apk`, `*.so`).
- Format Python with `ruff format`. Format Kotlin with `ktlint`.

---

## Reporting Issues

Use GitHub Issues. Include:

- FleetMind version (or commit hash)
- MDM platform (Jamf / Intune / Workspace ONE / ADB)
- Android version and device model
- Steps to reproduce
- Relevant logs from `adb logcat -s FleetMind`

---

## Code of Conduct

Be direct. Be technical. Be respectful. That's it.
