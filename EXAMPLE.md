# FleetMind — A Concrete Example

## The Company

**Meridian Health** — 800 employees, 12 hospitals across New Jersey. Every employee has a company-issued Samsung Galaxy S23 managed through Microsoft Intune.

Their legal team has **blocked OpenAI, Microsoft Copilot, and Google Gemini** on all work devices. The reason: HIPAA. If a nurse pastes patient notes into ChatGPT, that's a federal violation. $50K fine per incident.

But nurses are doing it anyway — on their personal phones. The shadow AI problem is already happening.

---

## Without FleetMind

Dr. Patel finishes a 3-hour surgery. She has 14 patient charts to summarize before she goes home. She opens ChatGPT on her personal iPhone and pastes in patient notes.

```
Patient: John Doe, DOB 03/14/1962, MRN 4482910
Procedure: Left knee replacement
Post-op: elevated WBC 14.2, fever 38.9°C, wound site shows...
```

That text just left the building. It hit OpenAI's servers in San Francisco. It's logged. It can be subpoenaed. Meridian Health just violated HIPAA and doesn't know it.

---

## With FleetMind

IT pushes the FleetMind APK to all 800 phones via Intune. Takes 5 minutes. Nurses don't touch anything.

From that moment, every employee phone joins a private AI mesh over the hospital's WiFi. 800 phones, collectively running Llama 3.2 on-device.

Dr. Patel opens the hospital's internal app — already built on OpenAI's API, one line changed by IT to point at `hospital.local:8080` instead of `api.openai.com`. She pastes the same patient notes.

**What happens:**

```
Dr. Patel's phone
│
│  "Summarize these post-op notes for John Doe..."
│  ← encrypted with Nurse Station 3's TrustZone key
│  ← backend sees: [blob of noise] addressed to device A7F2
│
▼
FleetMind backend (running in the server room)
│
│  Routes the encrypted blob to Nurse Station 3's Samsung S23
│  sitting idle on a charging dock at the nurses' station
│
▼
Samsung Galaxy S23 — Nurse Station 3
│
│  TrustZone decrypts the query (only this phone can)
│  Llama 3.2 3B runs locally: 18 tok/s
│  Produces the summary
│  Encrypts the response back to Dr. Patel's key
│
▼
Dr. Patel's phone decrypts and displays:

"POST-OP SUMMARY — John Doe (MRN 4482910)
 Procedure: L knee replacement, 03/11/26
 Concern: WBC 14.2 + fever 38.9°C suggests early infection.
 Wound site: mild erythema, no purulence yet.
 Recommended: Blood culture, IV cefazolin, ortho consult tomorrow.
 Action items: nursing q4h vitals, wound check 06:00."
```

**Data that left the building: 0 bytes.**
**Cost per query: $0.00.**
**Time: 44 seconds.**

The patient notes never touched a cloud server. OpenAI can't be subpoenaed for them. A data breach at Microsoft doesn't expose them. Dr. Patel's query was decrypted in exactly one place: inside the hardware security chip of a phone sitting 30 feet away.

---

## What Happened Under the Hood

| Data Center System | What It Did in This Example |
|---|---|
| **Power (PDU)** | Nurse Station 3 phone had 87% battery — highest in the eligible pool — so it got routed this query |
| **Cooling (CRAC)** | Phone's thermal state was NONE (22°C CPU) — eligible, no throttling |
| **Network (Switches)** | mDNS found the phone in 8 seconds when it joined the WiFi at shift change |
| **Security (Physical)** | Phone's TrustZone key was hardware-attested — backend confirmed before routing |
| **Fire Suppression** | No anomaly — query rate normal. If a device suddenly processed 10× the fleet average, it would be auto-quarantined |
| **Storage** | Dr. Patel's previous patient summary PDFs are chunked, AES-encrypted, and distributed across 6 phones — no cloud storage |
| **Compute (GPU Server)** | Llama 3.2 3B running via llama.cpp JNI on the phone's MediaTek chip |
| **Monitoring (NOC)** | `GET /api/fleet/health` showed 247 active devices, fleet thermal score 0.94 (optimal), 3 alerts (2 low battery, 1 unattested device) |

---

## The Number That Closes the Deal

Meridian Health was paying **$380,000/year** to OpenAI for internal tools — chart summaries, shift handover notes, insurance pre-auth letters. None of it needed to leave the building.

FleetMind: **$50,000/year** flat license. Hardware cost: $0 (phones already issued). Cloud bill going forward: $0.

The IT director's two-line pitch to the CFO:

> *"AI your legal team already approved. Running on hardware we already own. Saves $330K in year one."*

Legal says yes because the architecture makes it mathematically impossible for patient data to reach an external server — not a policy, not a privacy agreement, math. The CFO says yes because the ROI is immediate. The CISO says yes because every device is hardware-attested and every query is end-to-end encrypted.

---

## Why the Competition Can't Match This

| | Meridian + FleetMind | Meridian + OpenAI | Meridian + Microsoft Copilot |
|---|---|---|---|
| HIPAA compliant | ✓ | ✗ (data leaves building) | ✗ (data leaves building) |
| Legal approved | ✓ | ✗ (blocked) | ✗ (blocked) |
| Annual cost | $50K | $380K | $420K |
| New hardware | none | none | none |
| Data egress | 0 bytes | every query | every query |
| Can be subpoenaed | no — can't decrypt what we don't have | yes | yes |
| Shadow AI risk | eliminated | ongoing | ongoing |

---

## Try It Yourself

```bash
git clone https://github.com/TanmaySangam18/fleetmind
cd fleetmind/backend
pip install cryptography
python3 demo_blind_routing.py
```

The demo proves the core claim in 30 seconds: a fully compromised FleetMind backend cannot decrypt a query. Wrong device gets `cryptography.exceptions.InvalidTag`. Not a 403. Not a policy. Mathematics.
