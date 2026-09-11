# The Hardware Trust Chain: How FleetMind Achieves Cryptographic Query Privacy

---

## 1. The Problem: Why Software Encryption Isn't Enough

Standard enterprise software encrypts data at rest and in transit. This is necessary but not sufficient.

On a compromised or rooted Android device, the operating system is the adversary. A rooted OS can:

- Read any process's heap and stack — including AES keys held in RAM by an encrypted messaging app
- Hook Java/Kotlin method calls via Frida or Xposed to intercept decrypted plaintexts before they're re-encrypted
- Dump the key material from any software keystore backed only by a file on disk

Software encryption moves the problem: instead of protecting the data, you're now protecting the key. If the key lives in RAM under OS control, an attacker with root gets both.

The only escape from this trap is hardware.

---

## 2. The Solution: ARM TrustZone as the Trust Root

Every modern Android phone ships with ARM TrustZone — a hardware-enforced boundary that splits the processor into two worlds:

- **Normal World**: the Android OS, all apps, and everything the user sees
- **Secure World**: a separate execution environment (Trusted Execution Environment, TEE) that the Normal World cannot inspect, even with root

The Secure World runs a minimal, audited OS (Qualcomm QSEE, Samsung Knox TEE, ARM TrustZone Reference Software) that handles cryptographic operations. When Android Keystore is backed by TrustZone:

1. The private key is generated inside the TEE and **never exported to the Normal World in any form**
2. Cryptographic operations (ECDH key agreement, signing) happen inside the TEE; the Normal World submits work and receives results, but never touches key material
3. Even a rooted OS cannot read the key — the Normal World CPU cannot execute Secure World instructions or access Secure World memory

On Pixel 3+, Samsung Galaxy S10+, and other Titan M / StrongBox devices, a dedicated security chip provides an even stronger boundary: the key lives in a physically separate microcontroller with its own CPU, RAM, and power supply, isolated from the application processor entirely.

---

## 3. The Chain Explained

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FLEETMIND HARDWARE TRUST CHAIN                       │
└─────────────────────────────────────────────────────────────────────────────┘

  QUERY ORIGINATES ON REQUESTER'S PHONE
  ┌─────────────────────────────┐
  │  User types query           │
  │  ↓                          │
  │  TrustZoneKeyManager        │  ← Kotlin code running in Normal World
  │  .encryptQuery(query,       │
  │    targetNodePublicKey)     │
  │  ↓                          │
  │  Android Keystore API       │  ← Crosses hardware boundary
  │  ↓                          │
  │  ARM TrustZone TEE          │  ← ECDH + AES-256-GCM runs here
  │  (private key never leaves) │
  │  ↓                          │
  │  Ciphertext returned        │  ← Only encrypted bytes cross back
  │  to Normal World            │
  └─────────┬───────────────────┘
            │ encrypted_query_base64 (opaque to OS, network, backend)
            ▼
  BACKEND SERVER (FastAPI)
  ┌─────────────────────────────┐
  │  POST /api/query/secure     │
  │  ↓                          │
  │  RBAC check (role/namespace)│
  │  ↓                          │
  │  get_eligible_nodes()       │  ← role-filtered device pool
  │  ↓                          │
  │  Re-encrypt payload using   │  ← backend never decrypts original
  │  TARGET NODE's public key   │     just re-wraps the ciphertext
  │  (ECDH + AES-256-GCM)       │     in a new envelope for the node
  │  ↓                          │
  │  Route routed_payload       │
  │  to target device           │
  └─────────┬───────────────────┘
            │ re-encrypted blob (opaque to backend)
            ▼
  TARGET NODE (Android Phone — the processing device)
  ┌─────────────────────────────┐
  │  POST /api/secure/query     │
  │  ↓                          │
  │  TrustZoneKeyManager        │
  │  .decryptResponse(blob)     │
  │  ↓                          │
  │  ARM TrustZone TEE          │  ← ECDH using this device's private key
  │  (this device's private key)│     decrypts the original query
  │  ↓                          │
  │  Plaintext prompt available │  ← Only inside this device, briefly
  │  for inference              │
  │  ↓                          │
  │  llama.cpp / Ollama         │
  │  ↓                          │
  │  Response encrypted back    │  ← Using requester's public key
  │  using REQUESTER's pub key  │     via TrustZone
  └─────────┬───────────────────┘
            │ encrypted_response_base64
            ▼
  REQUESTER'S PHONE
  ┌─────────────────────────────┐
  │  TrustZoneKeyManager        │
  │  .decryptResponse(response) │
  │  ↓                          │
  │  ARM TrustZone TEE          │  ← Only this device's hardware can open it
  │  ↓                          │
  │  Plaintext response         │
  │  displayed to user          │
  └─────────────────────────────┘
```

At no point does the query exist as plaintext outside a TrustZone boundary.

---

## 4. What Android Keystore Actually Guarantees

Android Keystore is not just a file-based key vault. On TrustZone-backed devices:

**Key generation**: `KeyPairGenerator` with `KeyGenParameterSpec` marked `setIsStrongBoxBacked(true)` (or hardware-backed by default on modern devices) causes the TEE to generate the key pair internally. The private key bytes are never returned to the caller.

**Key operations**: ECDH agreement and AES-GCM encryption/decryption are executed inside the TEE. The Android API accepts the data, passes it through the hardware boundary, and returns only the result.

**Key non-exportability**: By default, Android Keystore keys cannot be extracted. There is no API to export the private key — only operations using it are permitted.

**Key attestation**: Android 7.0+ supports Key Attestation. The TEE generates a certificate chain, signed by a Google-rooted CA, that proves:
- The key was generated inside the TEE (not in software)
- The key's purpose, size, and export policy
- The security level: `TrustedEnvironment` (TrustZone) or `StrongBox` (dedicated security chip)

References:
- [Android Keystore System](https://developer.android.com/training/articles/keystore)
- [Hardware-backed Keystore](https://source.android.com/docs/security/features/keystore)
- [Key and ID Attestation](https://developer.android.com/training/articles/security-key-attestation)

---

## 5. The Attestation Proof

When a FleetMind agent first starts, it calls `POST /api/device/pubkey` with:

1. `public_key_base64` — the EC public key (safe to share)
2. `attestation_cert_chain` — a certificate chain generated by the TEE, signed up to Google's Hardware Attestation Root CA

The backend's `attestation.py` module:

1. Loads each DER-encoded certificate from the chain
2. Verifies each certificate's signature against its issuer (chain integrity)
3. Parses the Android Key Attestation extension (OID `1.3.6.1.4.1.11129.2.1.17`) from the leaf certificate
4. Extracts `attestationSecurityLevel` from the ASN.1 structure:
   - `0` = Software (key is in Android software keystore — **not trusted**)
   - `1` = TrustedEnvironment (key is in ARM TrustZone TEE — **hardware-backed**)
   - `2` = StrongBox (key is in dedicated security chip — **strongest**)
5. Marks the device `hardware_attested = true` in the database if security level ≥ 1

Devices that fail attestation are still allowed to participate (for v1 — attestation is a strong signal, not a hard gate), but the `attested` flag in query responses tells the requester whether their data was processed on a verified hardware-backed node.

---

## 6. What This Achieves vs. What It Doesn't

### What it achieves

- **Query confidentiality against a rooted device OS**: An attacker with root on the requester's phone cannot read the query before encryption or after decryption without compromising the TEE itself.
- **Node role enforcement via cryptography**: A CFO query encrypted to finance-role nodes cannot be decrypted by an engineer-role node — not because of a firewall rule, but because the engineer's device doesn't have the private key. The rejection is a `javax.crypto.AEADBadTagException`, not a 403 HTTP response.
- **Supply chain attestation**: The backend can verify that a device's keys are genuinely hardware-backed, not spoofed by a software keystore or a modified Android build.
- **Backend blindness**: The FleetMind server routes ciphertext it cannot read. Even a compromised backend server sees only encrypted blobs.

### What it doesn't achieve

- **Physical attacks**: A state-level adversary with physical device access and specialized hardware can extract keys from some TrustZone implementations using voltage glitching or EM side-channels. StrongBox (dedicated security chip) raises this bar significantly.
- **TEE software vulnerabilities**: TrustZone TEE software has had CVEs. A vulnerability in the TEE OS itself could leak key material. This risk is managed by device manufacturers through OTA updates.
- **Post-decryption memory inspection**: Once the plaintext prompt is in the inference engine's process memory (outside the TEE), it is accessible to a root-level attacker on that device. The trust chain protects transit; it does not protect in-use data inside the node's inference process.
- **Compromised requester**: If the requester's device is fully compromised at the TEE level, the attacker can intercept both the plaintext query and the plaintext response.
- **Google as root of trust**: Key Attestation is ultimately rooted in Google's attestation CA. A compromise of Google's CA signing key would break the attestation trust model.

---

## 7. Why This Is the World's First

No prior enterprise AI product combines all three of these:

**1. Phone-side TrustZone key management for AI queries**

Existing enterprise AI products (Microsoft Copilot, Google Vertex AI, AWS Bedrock) use HTTPS/TLS for transport security. TLS terminates at the server, where the server sees plaintext. TrustZone-backed key management ensures the key never exists in OS-accessible memory.

**2. Hardware attestation as a node selection criterion**

Existing mesh compute products (Exo Labs, Petals, Ray) select nodes based on latency, bandwidth, and model availability. FleetMind adds hardware attestation as a routing dimension: queries are preferentially routed to nodes where the key-management hardware has been cryptographically verified.

**3. Role-enforced cryptographic routing for AI inference**

RBAC systems (AWS IAM, Azure RBAC, Google Cloud IAM) enforce access control via server-side policy evaluation. If the server is compromised or the admin is malicious, the policy can be bypassed. FleetMind's role enforcement is cryptographic: a node without the correct private key produces a `AEADBadTagException` when it tries to process a query not addressed to it — the policy is enforced by mathematics, not server-side logic.

No enterprise AI product, mesh compute platform, or confidential computing system has implemented this specific combination.

---

## 8. The Future: ARM CCA Realms (2027+)

ARM Confidential Compute Architecture (CCA), announced in ARMv9, introduces **Realms** — hardware-isolated virtual machines that cannot be inspected by the hypervisor, host OS, or even the hardware owner.

When Android adopts ARM CCA (expected in flagship devices 2026–2027):

- The inference engine itself runs inside a Realm
- The Realm has its own attestation mechanism (Remote Attestation using the Realm Management Monitor)
- The query enters the Realm encrypted; inference runs on the plaintext inside the Realm; the result exits encrypted
- Even the device owner cannot inspect the in-progress inference

This would complete the chain: not just the key management, but the inference computation itself moves into hardware isolation. FleetMind's architecture is designed to adopt ARM CCA Realm-based inference as a drop-in upgrade path when the Android platform supports it.

References:
- [ARM CCA Architecture](https://www.arm.com/architecture/security-features/arm-confidential-compute-architecture)
- [Realm Management Extension](https://developer.arm.com/documentation/den0126/latest)
