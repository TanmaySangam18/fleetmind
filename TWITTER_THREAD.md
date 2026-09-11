# FleetMind Launch Thread

---

**Tweet 1 — Hook**

Your company pays $40K/year to OpenAI while 500 employee phones sit in pockets doing nothing.

We built software that turns those phones into a private AI cluster that costs $0/month to run. No new hardware. No cloud. This is how we did it 🧵

---

**Tweet 2 — The Problem**

The average 500-person company spends $3,000–$8,000/month on OpenAI API calls.

Most of that is internal tooling. Summarize this doc. Draft this email. Answer this HR question.

None of it needed to leave the building. You've been renting a data center for work you already own the hardware to do.

---

**Tweet 3 — The Insight**

Every employee phone is a computer.

A modern Android flagship has 12–16 GB RAM and an NPU that can run a 1B parameter model at 20 tok/s. It's already on the company network. It's already paid for. It sits idle 90% of the workday.

The data center was already there. Nobody connected it.

---

**Tweet 4 — How FleetMind Works**

- Install the FleetMind agent on employee phones (MDM one-click deploy)
- Phones join a private mesh over the local network — no internet required
- Queries route to whichever device has spare capacity and battery

The AI never leaves the building. You pay nothing per query. Ever.

---

**Tweet 5 — Architecture**

```
  [Laptop] → query
      ↓
  [Mesh Coordinator]
   /    |    \
[Phone] [Phone] [Phone]
  ↑       ↑       ↑
  idle   idle   charging

Each node: Ollama bridge + llama3.2:1b
Load balances by battery + availability
No single point of failure
```

---

**Tweet 6 — Why Nothing Else Does This**

Ollama: runs on one machine, not a fleet of phones.

Exo: distributed inference across owned servers, requires dedicated hardware.

RunAnywhere: cloud offload, still leaves your network.

FleetMind is the first system that treats the phones your company already issues as a unified private inference cluster.

---

**Tweet 7 — The Numbers**

500-phone fleet, 8-hour workday, 40% average idle rate:

- Available compute: ~200 phones at any moment
- Throughput: ~4,000 tok/s aggregate on llama3.2:1b
- Cost per query: $0.00
- vs. GPT-4o-mini at $0.15/1M tokens: $0 vs. ~$45K/year at enterprise volume

The hardware was already depreciated. The inference is now free.

---

**Tweet 8 — Open Source**

MIT license. No telemetry. No vendor lock-in. The mesh coordinator, Android agent, and Ollama bridge are all open.

You can audit exactly what runs on your employees' phones. You can fork it. You can self-host the management layer.

GitHub: https://github.com/TanmaySangam18/fleetmind

---

**Tweet 9 — Call to Action**

If your company has a line item for OpenAI, star this repo.

We're going commercial — enterprise support, MDM integrations, compliance tooling — when we hit 50K stars. Until then, it's free, it's MIT, and it works today.

https://github.com/TanmaySangam18/fleetmind

Build the AI infrastructure you already own.

---
