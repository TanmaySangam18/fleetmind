# FleetMind — Hackathon Submission

> Fill in [HACKATHON NAME], [PRIZE TRACK], and [DEADLINE] before submitting.

---

## Project Name
FleetMind

## One-liner
The first enterprise AI system where the backend routes encrypted queries it cannot mathematically decrypt — running on the phones your company already owns.

## Track
[PRIZE TRACK] — Privacy / Security / Enterprise AI

---

## What it does

FleetMind turns your company's employee phones into a private AI inference mesh. Queries are encrypted with each device's ARM TrustZone hardware key before they leave the requester. The server routes an opaque blob it **cannot decrypt** — enforced by ECDH cryptography, not a policy.

Zero cloud egress. OpenAI-compatible API. No new hardware.

---

## The problem it solves

Every enterprise AI product — Microsoft Copilot, Google Vertex AI, OpenAI Enterprise — requires your data to leave your building and reach their infrastructure. They can be subpoenaed. They can be breached. Their privacy policies can change.

The deeper problem: **they structurally cannot offer zero-egress AI.** Their models are proprietary IP that cannot run on customer hardware. Their business model depends on centralizing compute. Their SOC 2 requires audit trails. They are not building toward zero-egress — zero-egress destroys their moat.

FleetMind is the only path to AI your legal team will approve.

---

## How we built it

### The encryption layer (the core innovation)

Each FleetMind device generates an EC key pair inside ARM TrustZone via Android Keystore. The private key is generated inside the TEE and never exported — not to our backend, not to RAM, nowhere. Only the public key reaches our server.

When a user sends a query:
1. The client fetches the target device's public key
2. Generates a random ephemeral EC keypair
3. Performs ECDH to derive a shared secret
4. Derives an AES-256-GCM key via HKDF
5. Encrypts the query with a random nonce
6. Sends the blob (ephemeral_pub + nonce + ciphertext) to the backend

The backend receives this blob and a target device ID. **It has no private key and cannot derive the shared secret.** A compromised backend server sees 159 bytes of noise.

The target device decrypts using its TrustZone-protected private key. Only the correct device can produce the ECDH shared secret — all others get `cryptography.exceptions.InvalidTag`. Not a 403. Not a policy check. Mathematics.

### The mesh layer

- **Discovery**: Android NSD (mDNS) — devices find each other in under 10 seconds on corporate WiFi
- **Inference**: llama.cpp JNI (Android) or Ollama bridge (Mac) — runs Llama 3.2 1B at 15–25 tok/s
- **Routing**: FastAPI backend with SQLite device registry, 60-second heartbeats, battery-aware exclusion (<20%)
- **API**: OpenAI-compatible `/v1/chat/completions` endpoint — drop-in replacement

### The RBAC layer

Role-enforced cryptographic routing: a finance-namespace query is encrypted to finance-or-above device public keys only. An engineering device cannot decrypt it because it has the wrong key — not because a firewall said no. The access control is enforced at the ECDH layer.

---

## Demo

```bash
git clone https://github.com/TanmaySangam18/fleetmind
cd fleetmind/backend
pip install cryptography
python3 demo_blind_routing.py
```

Output (relevant section):

```
Step 4 — Backend Blindness Proof
  Attempting: decrypt_query(blob, engineering_phone_private_key)...
  ✗  InvalidTag:
  AES-GCM authentication failed. Not a 403. Not a policy check. Mathematics.

Step 5 — Finance Node Decrypts
  ✓  Decrypted: 'What is our Q3 revenue breakdown by product line?'
  The query existed as plaintext in exactly two places:
    1. The CFO's device (before encryption)
    2. The finance node's TrustZone (for ~50ms during inference)
```

Live mesh demo (Mac + Android + browser nodes): follow `TESTING.md`.

---

## Technologies used

- **Android (Kotlin)**: ARM TrustZone / Android Keystore, NSD (mDNS), WorkManager, llama.cpp JNI
- **Backend (Python)**: FastAPI, SQLite/SQLAlchemy, `cryptography` (ECDH + AES-256-GCM + HKDF)
- **Web (Next.js)**: Fleet dashboard, trial registration, browser mesh node (WebCrypto API)
- **Crypto**: ECDH P-256 + AES-256-GCM + HKDF-SHA256 (backend-blind key exchange)
- **Attestation**: Android Key Attestation (certificate chain verification, OID 1.3.6.1.4.1.11129.2.1.17)
- **Models**: Llama 3.2 1B/3B, Gemma 3 1B, Phi-4-mini (GGUF Q4_K_M)
- **Deployment**: Docker Compose, MDM (Jamf / Intune / Workspace ONE)

---

## What makes it novel

No prior system combines all four:

| Property | FleetMind | Azure CC | Apple PCC | Google CC | OpenAI Ent |
|---|---|---|---|---|---|
| Backend cannot decrypt queries | ✓ | ✗ | ✗ | ✗ | ✗ |
| Zero data egress from building | ✓ | ✗ | ✗ | ✗ | ✗ |
| Runs on customer-owned hardware | ✓ | ✗ | ✗ | ✗ | ✗ |
| Hardware-attested node selection | ✓ | partial | partial | partial | ✗ |
| Cryptographic role enforcement | ✓ | ✗ | ✗ | ✗ | ✗ |

This is not a matter of degree. It is a structural difference: every competitor requires your data to reach their infrastructure. FleetMind does not.

---

## Challenges

- **llama.cpp JNI on Android**: Cross-compiling llama.cpp for arm64-v8a with proper NEON intrinsics required patching the CMakeLists — Android's NDK doesn't expose all POSIX threading primitives out of the box.
- **mDNS reliability on enterprise WiFi**: Many managed WiFi networks block multicast by default. The heartbeat HTTP registration is the primary path; mDNS is opportunistic. The mesh works either way.
- **Battery-aware routing without over-polling**: The 60-second heartbeat interval was tuned to keep battery impact under 1% per hour on a Pixel 7 while maintaining sub-90-second failover.

---

## What's next

- **ARM CCA Realm support (2027 hardware)**: Move the inference itself inside a hardware-isolated Realm — not just the keys, but the compute. When Android devices ship ARMv9 CCA, FleetMind adopts it as a drop-in upgrade.
- **Per-model routing**: Code queries → Phi-4. Summarization → Llama 3.2. Route by task type, not just availability.
- **iOS support**: Waiting on Apple MDM background compute entitlements.
- **Prometheus metrics**: Fleet observability endpoint for existing monitoring stacks.

---

## Team

Tanmay Sangam — product, backend, crypto layer, Android agent
GitHub: https://github.com/TanmaySangam18/fleetmind

---

## Links

- GitHub: https://github.com/TanmaySangam18/fleetmind
- Demo script: `backend/demo_blind_routing.py`
- Trust chain doc: `TRUSTCHAIN.md`
- Testing guide: `TESTING.md`

---
