# Character Labs G7 Application — FleetMind

**Deadline:** September 23, 11:59pm PT
**Cohort start:** October 27
**Apply at:** https://contact.character.vc/labs

---

## FORM FIELDS

### Company Name
FleetMind

### Company Description
*(This is the critical field — aim for 2-3 punchy paragraphs)*

---

**Draft A — Lead with the encryption moat:**

FleetMind is the first enterprise AI system where the backend routes encrypted queries it mathematically cannot decrypt.

Every "private AI" product from Microsoft, Google, and Apple still requires your data to leave your building. They can be subpoenaed. Their infrastructure can be breached. Their policies can change. This is not a solvable problem for them — their business models require centralized compute.

FleetMind routes around this entirely. Queries are encrypted with each device's ARM TrustZone hardware key before they leave the requester. Our server sees an opaque blob and a device ID — nothing more. The inference runs on the phones your company already issues to employees, on your corporate WiFi, using open-weight models (Llama, Gemma, Phi-4). Zero cloud egress. One line of code to switch from OpenAI. The legal team finally says yes.

---

**Draft B — Lead with the business case:**

FleetMind turns your company's employee phones into a private AI cluster, replacing OpenAI for internal tools at zero ongoing cost.

The average 500-person company spends $40K/year on OpenAI API calls — mostly internal: summarize this document, draft this email, answer this HR question. None of it needed to leave the building. Every employee phone has a chip capable of running a 1–3B parameter model. FleetMind pools those chips into a mesh over your corporate WiFi and exposes an OpenAI-compatible API. One line change. No new hardware. No ongoing cloud bill.

The differentiation that closes the deal: FleetMind's queries are encrypted with ARM TrustZone hardware keys before they leave the requester — our backend routes blobs it cannot decrypt. For healthcare, legal, defense, and finance companies whose IT teams have blocked OpenAI on compliance grounds, FleetMind is the first yes.

---

**Recommended: Use Draft A** (encryption moat is the novel claim; Design Sprint people will probe whether the market is real — be ready with the HIPAA/legal use case in the interview)

---

## FOUNDER INFO

**Name:** Tanmay Sangam
**Email:** sangam.d@northeastern.edu
**LinkedIn:** linkedin.com/in/tanmaysangam *(update with your actual LinkedIn URL)*
**Technical founder checkbox:** ✓ YES — I can build the full stack without outside assistance

*(The full product is live: Android Kotlin app, FastAPI backend, Next.js dashboard, Mac node, true ECDH crypto layer — all written by me. GitHub: https://github.com/TanmaySangam18/fleetmind)*

---

## ADDITIONAL QUESTIONS (if the form has them)

### What problem are you solving?

Enterprise companies cannot use AI for their most sensitive internal work. Legal teams block OpenAI on compliance grounds — HIPAA exposure, SOC 2 obligations, subpoena risk. But employees use it anyway, on their personal accounts. The shadow AI problem is already happening; companies just can't see it.

The correct solution is not "stricter policies." It is AI infrastructure that makes compliance the default. AI that your legal team will actually approve — not because they trust the vendor's privacy policy, but because the architecture makes it mathematically impossible for the query to reach any external server.

### What's your solution?

FleetMind is an enterprise inference mesh that runs on the Android phones your IT department already manages. It has three layers:

1. **The mesh**: Phones join a private cluster over corporate WiFi via mDNS. The FleetMind backend routes queries to available devices using round-robin with battery and model-availability awareness.

2. **The encryption**: Each device generates an EC key pair inside ARM TrustZone (Android Keystore). Queries are encrypted with the target device's public key using ECDH + AES-256-GCM. Our backend receives a ciphertext blob it cannot decrypt — no private key ever touches our server. The rejection of a wrong-device decryption attempt is `cryptography.exceptions.InvalidTag`, not a policy check.

3. **The API**: OpenAI-compatible `/v1/chat/completions`. One-line switch from `api.openai.com` to your local FleetMind endpoint. Every internal tool your team built on OpenAI's API works immediately.

Deploy via MDM (Jamf, Intune, Workspace ONE) — one push, zero touch, phones join the mesh within 60 seconds.

### Who is your customer?

**Beachhead:** IT and security leads at healthcare companies (HIPAA), law firms (client privilege), and defense contractors (controlled unclassified information) — segments where OpenAI and similar products have already been blocked by legal/compliance teams.

**Expansion:** Any enterprise company with a line item for OpenAI API costs and a compliance team that has said no to AI for sensitive workflows.

**The buying decision:** CIO / IT Director. The value prop is a two-line pitch: "AI your legal team already approved, running on hardware you already own, costing $0 per query."

### Why now?

Three things collided in 2024–2025:

1. **Enterprise AI spend became visible.** OpenAI's API costs now appear as real line items in enterprise budgets. CFOs are asking questions.

2. **Shadow AI became a liability.** The OCR started investigating companies for HIPAA violations caused by employees pasting patient data into consumer AI tools. This is no longer a theoretical risk.

3. **On-device models became capable enough.** Llama 3.2 1B runs at 15–25 tok/s on a 2022 flagship Android. Phi-4-mini runs acceptably on any phone with 12 GB RAM. The hardware was not ready two years ago.

### What's your traction?

- GitHub repo live: https://github.com/TanmaySangam18/fleetmind
- Full working demo: Mac + Android + browser nodes running live inference
- Complete trust chain implemented: TrustZone key management + hardware attestation + ECDH blind routing
- Identified beachhead customer profile (IBA/proton therapy field service as first detailed pitch target)
- No revenue yet — pre-PMF, which is exactly why I'm applying

### Why me?

I built the full stack — Android Kotlin agent, FastAPI backend, Next.js dashboard, Mac node, ECDH cryptographic layer, hardware attestation verification — in under two weeks, solo. The GitHub history is public.

The trust chain architecture (TrustZone + hardware attestation + cryptographic RBAC) is novel. It took me three iterations to get the key exchange right: the first version used symmetric HMAC keys, which meant the backend could decrypt everything — defeating the claim. The second version added ECDH but the wire format was wrong. The current version is correct: an adversary who fully compromises the backend server receives noise. I can prove it runs in under 30 seconds on any laptop (`python3 demo_blind_routing.py`).

I have a master's in engineering management from Northeastern. My prior work was in operations and go-to-market — I know how to sell to enterprise IT. I understand that technical correctness and customer acquisition are different problems. That's why I want Design Sprint methodology to find the shortest path to a paying customer.

### What do you want from Character Labs?

Specifically:
- Help identifying which of the three beachhead segments (healthcare, legal, defense) has the shortest sales cycle and lowest compliance friction to close a first paid customer
- Pressure-testing whether the privacy/compliance angle or the cost-savings angle is the right lead in a 30-second pitch
- The Design Sprint process to stress-test my assumptions about who the actual buyer is — CIO, GC, or CISO

I believe the product is technically differentiated. I'm less certain about the fastest path to revenue, which is exactly the PMF question.

---

## LOGISTICS NOTES

- **US incorporation**: Solo founder, currently pre-incorporation. Will form a Delaware C-corp immediately upon acceptance. Character's investment structure requires this — I'll have it done before the cohort starts Oct 27.
- **Location**: Based in New Jersey (NYC metro). Hybrid program is fine; I can travel to the Bay for in-person sessions if needed.
- **Work authorization**: US work-authorized (EAD).
- **Solo founder**: I'm the sole founder building the technical product. Open to co-founder matching if Character has a recommendation.

---

## PRE-SUBMISSION CHECKLIST

- [ ] Update LinkedIn URL above with your actual URL
- [ ] Confirm US incorporation status / timeline
- [ ] Choose Draft A or B for the company description field
- [ ] Star your GitHub repo so it doesn't look empty on inspection
- [ ] Test `python3 backend/demo_blind_routing.py` — this is your live demo if asked

---
