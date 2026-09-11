# FleetMind × IBA Proton Therapy

**Account:** IBA (Ion Beam Applications)
**Segment:** Medical device / field service — proton therapy systems
**US employees:** ~484 (field service engineers, predominantly hospital-embedded)
**Deal size:** $50,000 one-time license (201–1000 employee tier)
**Regulatory exposure:** HIPAA Business Associate, FDA 21 CFR Part 820
**Status:** No cloud AI deployed internally

---

## Why This Pitch Exists

IBA's field service engineers work physically inside cancer treatment centers — Mass General Hospital, Mayo Clinic, MD Anderson — maintaining the cyclotrons and gantries that deliver radiation to cancer patients. That proximity makes them HIPAA Business Associates by definition: they have incidental exposure to patient treatment plans, beam delivery logs, and CBCT imaging data. The problem is not that IBA is reckless. The problem is that AI tools are now the reflex response to any documentation task, and IBA has deployed none of them. That vacuum does not mean their engineers are not using AI — it means they are using whatever is on their personal phones or whatever ChatGPT tab is open in their browser. Every time an IBA engineer voice-dictates a service note near a treatment console, every time they paste a session fault log into a public LLM to debug it at 2am, they create a potential HIPAA breach that IBA's legal team does not know about and cannot audit. FleetMind closes that gap: it gives IBA engineers a sanctioned, on-device AI tool that works inside RF-shielded treatment vaults with zero internet required and zero data leaving the device — so the productivity they are already reaching for is captured without the regulatory exposure they are currently ignoring.

---

## The Specific Problem

- **Engineer at MGH voice-dictates a service report using Siri.** "Patient Session #4872 — beam instability during treatment, log attached." Apple processes that audio on remote servers. IBA has no BAA with Apple. That is a HIPAA breach.
- **Engineer troubleshoots a cyclotron fault at 2am and pastes the fault log into ChatGPT.** The fault log includes session timestamps, room identifiers, and treatment plan references tied to an active patient. OpenAI has no BAA with IBA. That data is now in a commercial model training pipeline.
- **Service report referencing "Patient Session #4872 beam instability" is pasted into Microsoft Copilot** to auto-format the FDA adverse event report. Even if IBA has an Azure HIPAA BAA, the individual engineer is using consumer Copilot — not the enterprise tier. The data crossed the boundary. OCR does not care about intent.

---

## What FleetMind Does For IBA

**1. Field service documentation — draft reports from voice notes, on-device.**
Engineers dictate fault descriptions, corrective actions, and parts replaced. FleetMind structures the dictation into IBA's service report format locally, on the phone, before the engineer leaves the vault. No cloud. No clipboard. No risk.

**2. Offline troubleshooting — query technical manuals in RF-shielded vaults.**
Treatment vaults are RF-shielded by design. Internet connectivity is zero or unreliable. FleetMind's inference runs fully on-device — the engineer can query the cyclotron service manual, escalation procedures, or historical fault trees without needing any network connection.

**3. Incident reporting — structure FDA adverse event reports per 21 CFR Part 820.**
FleetMind can be loaded with the specific field map for 21 CFR Part 820 MDR reporting. Engineers fill out the incident, FleetMind checks required fields, flags missing data, and formats the output for submission — all without the report ever touching a third-party server.

**4. Training — on-device quiz bot for Oral Board certification exams.**
IBA engineers maintain certifications for cyclotron operation and radiation safety. FleetMind can serve as a closed-loop study tool: engineers query it, it surfaces practice questions and explanations from IBA's own training materials, all offline. No data about which questions were asked leaves the device.

**5. Regulatory compliance — enforce maintenance record format, flag missing fields.**
IBA's SAP S/4HANA implementation standardized their back-office workflows. FleetMind extends that discipline to the field: before an engineer submits a maintenance record, FleetMind reviews it for format compliance and completeness against the IBA standard — without that record leaving the device.

**6. HIPAA-safe patient context — reference session metadata without cloud egress.**
Engineers sometimes need to understand the patient context of a fault event (beam instability during session, timing of calibration relative to treatment schedule). FleetMind lets them query that metadata and get structured answers on-device. The session data never moves.

---

## The HIPAA Math

| Item | Number |
|---|---|
| HIPAA fine per violation | $100 – $50,000 |
| Maximum per violation category per year | $1,900,000 |
| Typical OCR settlement for a mid-size Business Associate | $500,000 – $5,000,000 |
| Reputational cost of an MGH-linked HIPAA breach (IBA's flagship site) | Incalculable |
| **FleetMind license for all 484 US employees** | **$50,000 one-time** |
| **Cost of one HIPAA enforcement action** | **$500,000 – $5,000,000+** |

One field engineer. One ChatGPT session. One patient session ID in the paste buffer. That is the exposure. FleetMind costs less than the legal fees for the first discovery call with OCR. The license pays for itself by avoiding a single incident. There is no amortization calculation that does not favor acting now.

---

## Why Not Azure OpenAI with HIPAA BAA?

This objection will come up. Here is the pre-emption:

**"We use Azure with the Microsoft HIPAA BAA — we're covered."**

No. Azure OpenAI with a HIPAA BAA means the data is encrypted in transit and Microsoft signs the agreement. The data still leaves the device. It still travels to Microsoft's data centers. It is still processed on remote infrastructure. "Encrypted in transit" is not zero egress — it is managed egress with a contract.

More practically:

- **Azure OpenAI requires internet.** IBA engineers work inside RF-shielded treatment vaults. There is no outbound internet from inside a vault. Azure does not run on airplane mode.
- **Hospital networks block outbound AI traffic.** MGH, Dana-Farber, and similar cancer centers control their own network egress. An IBA engineer on the hospital internal network cannot reach an Azure endpoint even if they wanted to. The tool simply does not function in the environment where the engineer needs it most.
- **Enterprise tier compliance requires IT provisioning.** The actual risk is not the enterprise-tier Azure deployment — it is the engineer on a personal phone using consumer ChatGPT or consumer Copilot. FleetMind is MDM-deployable: IT pushes it silently to all 484 corporate phones and the shadow AI problem is solved at the device layer.

FleetMind: inference runs entirely on the phone. Works with airplane mode on. Works inside a Faraday cage. Works on a hospital network with zero outbound access. No BAA required because no data leaves the device.

---

## Pilot Proposal

**Target cohort:** 50 Boston-area field service engineers based at or regularly servicing Mass General Hospital — IBA's most historically significant North American site and the location of the world's first hospital-based proton therapy center.

**Duration:** 30 days

**Cost:** Waived for pilot

**Deployment:** IT pushes via MDM to 50 corporate phones. No engineer action required. No new login. No new app store download.

**Success metrics:**
- Engineers complete service reports 40% faster (measured via SAP S/4HANA submission timestamps vs. baseline)
- Zero HIPAA exposure incidents during pilot period (auditable — FleetMind logs show all queries stayed on-device)
- Engineer NPS ≥ 7 at day 30

**Expansion trigger:** Pilot success → full 484 US employee license → $50,000 one-time fee

**Timeline:** Pilot can begin within 2 weeks of IT approval. MDM profile takes 4 hours to deploy.

---

## Contact

| Role | Person | Email |
|---|---|---|
| Primary | CIDO (Chief Information and Digital Officer) | CIDO contact via Brussels HQ |
| Secondary | Frédéric Genin, President North America | frederic.genin@iba-group.com |
| Internal champion | Boston-area field service engineers at MGH | Bottom-up — warm intro via Genin |
| Executive sponsor | Henri de Romrée, Deputy CEO | henri.de.romree@iba-group.com |

**Approach:** Lead with CIDO (owns digital stack and SAP decision). Genin is the NA business head — useful if CIDO is slow to respond. The real champion is the service engineer who is currently using ChatGPT at 2am and knows it is wrong.

---

## Outreach Email

**To:** CIDO, IBA Group (Brussels)
**CC:** frederic.genin@iba-group.com
**Subject:** Your SAP rollout is done. What happens when your engineers at MGH ask to use AI?

---

Your team completed the SAP S/4HANA migration in Q2 2026. That closes the back-office gap. It does not close the field gap.

IBA's engineers are HIPAA Business Associates. They work inside cancer treatment centers at MGH and 30+ other sites. Right now, when one of them needs to structure a service report or debug a cyclotron fault at 2am, the reflex is to open ChatGPT — and that is a HIPAA breach on the first paste.

FleetMind is enterprise software that turns corporate phones into a private AI inference mesh. Queries never leave the device. It works inside RF-shielded treatment vaults with no internet required. IT deploys it silently via MDM — no engineer setup.

For IBA's 484 US employees, the license is $50,000 one-time. One HIPAA enforcement action costs more than that before the first settlement offer.

I'd like 30 minutes to show you how a pilot at MGH would run and what the audit trail looks like for your compliance team.

Tanmay Sangam
sangam.d@northeastern.edu

---

## Why Now

**SAP S/4HANA live Q2 2026.** IBA's IT organization just completed a major platform migration. The natural next question in every post-ERP conversation is: "What do we enable on top of this?" FleetMind is the field layer answer — the tool that extends digital discipline from back-office to the service vault. The CIDO's team is already in build mode. This is the right moment.

**EU AI Act enforcement 2025–2026.** IBA is a Belgian company. The EU AI Act classifies AI systems used in medical device contexts as high-risk, requiring documented data governance, audit logs, and conformity assessments. A cloud AI deployment would require IBA to map every data flow and file a conformity assessment. FleetMind's on-device architecture eliminates the data flow problem entirely — there is nothing to govern that leaves the device.

**PhantomX acquisition.** IBA acquired PhantomX to add AI-driven QA capabilities to their platform. That acquisition signals that IBA's leadership is actively thinking about where AI fits in their product and operations stack. The internal appetite for AI is there. The safe deployment path for field operations is not.

**Zero competitor has pitched them.** IBA has no cloud AI deployed internally. That is not an oversight — it is a compliance constraint that every AI vendor has either missed or avoided. There is no incumbent. No existing relationship to displace. The field is clear.

---

*This document is a FleetMind internal sales brief. Not for external distribution.*
*Prepared: September 2026*
