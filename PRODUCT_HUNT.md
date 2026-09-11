# FleetMind — Product Hunt Launch

---

## Tagline

**The first enterprise AI that routes encrypted queries it cannot decrypt. Zero cloud. Your phones. Your keys.**

---

## Short Description (for the gallery card)

FleetMind turns your company's employee phones into a private AI cluster. Queries are encrypted with each device's ARM TrustZone key before leaving the user — the backend routes an opaque blob it literally cannot read. Zero egress. OpenAI-compatible API. No new hardware.

---

## Full Description

**The problem with every "private AI" product:**

Microsoft Confidential Computing, Apple Private Cloud Compute, Google Confidential GKE — they all encrypt data at rest and in transit. They all require your data to leave your building and reach their infrastructure. They can be subpoenaed. Their policy can change.

"Confidential" is doing a lot of heavy lifting.

**What FleetMind actually does:**

Every Android phone ships with ARM TrustZone — a hardware-enforced security chip the OS cannot read, even with root access. FleetMind uses this to achieve what no cloud provider can offer:

1. **Device key generation inside TrustZone.** Each phone generates an EC key pair in the hardware security chip. The private key is never exported — not to our backend, not to our dashboard, not anywhere. Android Keystore enforces this at the silicon level.

2. **Backend-blind routing.** Queries are encrypted with the target device's public key (ECDH + AES-256-GCM) before they leave the requester. Our server receives a blob and a device ID. That is all it ever has. A fully compromised backend server sees noise.

3. **Cryptographic role enforcement.** A finance query encrypted to finance-role devices cannot be decrypted by an engineering device — not because of a firewall rule, but because the engineering device has the wrong private key. The rejection is `cryptography.exceptions.InvalidTag`. Mathematics, not policy.

4. **Zero egress.** The inference mesh runs on your corporate WiFi using mDNS discovery. Queries never leave the local network. The model runs on open-weight GGUF files (Llama 3.2, Gemma 3, Phi-4-mini) your IT team distributes via MDM. No call is ever made to api.openai.com or any external endpoint.

**The reason big tech cannot offer this:**

Microsoft, Google, and Apple cannot put their AI on your hardware. Their models are proprietary IP. Their SOC 2 requires audit trails. Their liability requires centralized logging. Their business model depends on centralizing compute.

FleetMind runs open-weight models on hardware your company already owns, manages, and controls. There is no cloud dependency to protect. The trust model is not "trust FleetMind." It is "trust mathematics."

**Works with your existing stack:**

```diff
- base_url = "https://api.openai.com/v1"
+ base_url = "http://your-company.local:8080/v1"
```

One line. Every internal tool your team built on the OpenAI API works immediately.

**Open source, MIT license.** You can audit exactly what runs on your employees' phones. You can fork it. You can self-host the management layer with `docker compose up`.

---

## Maker Comment (post this as your first comment on PH launch day)

Hey Product Hunt 👋

I'm Tanmay, one of the builders of FleetMind.

The thing that bothered me about every "enterprise AI privacy" solution was that they all required you to trust someone. Trust OpenAI's policy. Trust Microsoft's SOC 2. Trust Google's legal team.

FleetMind removes the trust assumption entirely. The query is encrypted with the target device's hardware key before it leaves your device. Our backend routes a blob it cannot decrypt. If you don't believe us, run `python3 demo_blind_routing.py` from the repo — it proves the rejection is a thrown exception, not a policy check.

The hardware for this already exists in your employees' pockets. ARM TrustZone ships in every modern Android phone. Android Keystore enforces key non-exportability at the silicon level. Nobody had wired this into an enterprise inference mesh before.

Happy to answer any questions about the architecture, the trust chain, or how to deploy it in your environment. TESTING.md walks through a 4-device mesh with a Mac + Android + 2 iPhones in about 10 minutes.

---

## Topics / Tags

`privacy` `enterprise` `ai-tools` `open-source` `security` `android` `self-hosted` `developer-tools`

---

## Gallery Image Descriptions

*(For designer reference — create dark-theme images matching the terminal aesthetic)*

1. **Hero**: Split screen — left: `api.openai.com` with a red lock + "subpoena-able". Right: FleetMind mesh diagram with green lock + "cannot decrypt".

2. **Architecture**: The trust chain diagram from TRUSTCHAIN.md rendered as a dark-mode graphic with green arrows showing encrypted flow.

3. **Code swap**: The `base_url` one-line diff on a dark terminal background.

4. **Proof**: Terminal output of `demo_blind_routing.py` showing `InvalidTag` — specifically the step 4 output.

5. **Numbers**: "159 bytes of noise / $0 per query / 0 bytes egress" on a dark card.

---

## Pricing to mention

Free trial (7 days, unlimited queries). Paid tiers start at $4,000/year for up to 200 employees — less than one month of a mid-size company's OpenAI bill.

---
