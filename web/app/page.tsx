import Link from "next/link";

const TIERS = [
  {
    name: "Startup",
    range: "1–200 employees",
    employees: 200,
    price: 4_000,
  },
  {
    name: "Growth",
    range: "201–1,000 employees",
    employees: 1_000,
    price: 15_000,
  },
  {
    name: "Scale",
    range: "1,001–5,000 employees",
    employees: 5_000,
    price: 50_000,
  },
  {
    name: "Enterprise",
    range: "5,001–20,000 employees",
    employees: 20_000,
    price: 150_000,
  },
  {
    name: "Global",
    range: "20,000+ employees",
    employees: 20_000,
    price: 400_000,
  },
];

function openAiCost(employees: number): number {
  return employees * 500 * 0.004 * 260;
}

function fmt(n: number): string {
  return n >= 1_000_000
    ? `$${(n / 1_000_000).toFixed(1)}M`
    : `$${n.toLocaleString()}`;
}

export default function HomePage() {
  return (
    <main className="min-h-screen bg-[#0a0a0a] text-white">
      {/* Nav */}
      <nav className="border-b border-white/10 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <span className="text-lg font-semibold tracking-tight">FleetMind</span>
          <Link
            href="/register"
            className="text-sm text-[#00ff87] border border-[#00ff87]/40 px-4 py-2 rounded hover:bg-[#00ff87]/10 transition-colors"
          >
            Start Free Trial
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="max-w-5xl mx-auto px-6 pt-24 pb-20 text-center">
        <div className="inline-block text-xs font-mono text-[#00ff87] border border-[#00ff87]/30 bg-[#00ff87]/5 px-3 py-1 rounded-full mb-8 tracking-widest uppercase">
          Private AI Infrastructure
        </div>

        <h1 className="text-4xl sm:text-5xl md:text-6xl font-bold leading-tight tracking-tight mb-6">
          Your company already owns
          <br />
          <span className="text-[#00ff87]">the AI infrastructure.</span>
          <br />
          You just don&apos;t know it yet.
        </h1>

        <p className="text-lg text-white/60 max-w-2xl mx-auto mb-10 leading-relaxed">
          FleetMind turns your employee phone fleet into a private AI compute
          cluster. No new hardware. No cloud subscriptions. One-time fee.
        </p>

        {/* Stat boxes */}
        <div className="flex flex-wrap gap-4 justify-center mb-10">
          <div className="border border-white/10 bg-white/5 rounded-xl px-8 py-5 text-left">
            <div className="text-3xl font-bold text-[#00ff87] font-mono">2.3M</div>
            <div className="text-sm text-white/50 mt-1">queries / month</div>
          </div>
          <div className="border border-white/10 bg-white/5 rounded-xl px-8 py-5 text-left">
            <div className="text-3xl font-bold text-[#00ff87] font-mono">$0</div>
            <div className="text-sm text-white/50 mt-1">cloud bill</div>
          </div>
        </div>

        <Link
          href="/register"
          className="inline-block bg-[#00ff87] text-black font-semibold px-8 py-4 rounded-lg text-base hover:bg-[#00e87a] transition-colors"
        >
          Start 7-Day Free Trial
        </Link>
        <p className="text-xs text-white/30 mt-4">
          No credit card required. Cancel anytime.
        </p>
      </section>

      {/* Feature cards */}
      <section className="max-w-5xl mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="border border-white/10 bg-white/5 rounded-xl p-6">
            <div className="w-8 h-8 bg-[#00ff87]/10 border border-[#00ff87]/30 rounded-lg mb-4 flex items-center justify-center">
              <span className="text-[#00ff87] text-xs font-mono font-bold">01</span>
            </div>
            <h3 className="font-semibold text-base mb-2">Zero New Hardware</h3>
            <p className="text-sm text-white/50 leading-relaxed">
              Every idle phone in your fleet is a compute node. FleetMind
              orchestrates them silently during off-hours. You bought the
              hardware — now it works for you.
            </p>
          </div>

          <div className="border border-white/10 bg-white/5 rounded-xl p-6">
            <div className="w-8 h-8 bg-[#00ff87]/10 border border-[#00ff87]/30 rounded-lg mb-4 flex items-center justify-center">
              <span className="text-[#00ff87] text-xs font-mono font-bold">02</span>
            </div>
            <h3 className="font-semibold text-base mb-2">Data Never Leaves</h3>
            <p className="text-sm text-white/50 leading-relaxed">
              Fully air-gapped by design. No prompts, completions, or embeddings
              touch external servers. Compliance-ready for HIPAA, SOC 2, and
              GDPR with zero configuration.
            </p>
          </div>

          <div className="border border-white/10 bg-white/5 rounded-xl p-6">
            <div className="w-8 h-8 bg-[#00ff87]/10 border border-[#00ff87]/30 rounded-lg mb-4 flex items-center justify-center">
              <span className="text-[#00ff87] text-xs font-mono font-bold">03</span>
            </div>
            <h3 className="font-semibold text-base mb-2">Own It Forever</h3>
            <p className="text-sm text-white/50 leading-relaxed">
              One-time purchase. No per-seat fees. No API rate limits. No
              renewal reminders. The license is yours indefinitely — including
              all future model upgrades.
            </p>
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="border-t border-white/10 py-24 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl font-bold mb-3">One-time pricing. No surprises.</h2>
            <p className="text-white/50 text-base">
              Pay once. Run forever. Compare to what you&apos;d spend on OpenAI every year.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            {TIERS.map((tier) => {
              const cloud = openAiCost(tier.employees);
              const isPopular = tier.name === "Growth";
              return (
                <div
                  key={tier.name}
                  className={`rounded-xl p-5 border flex flex-col ${
                    isPopular
                      ? "border-[#00ff87]/60 bg-[#00ff87]/5"
                      : "border-white/10 bg-white/5"
                  }`}
                >
                  {isPopular && (
                    <span className="text-[10px] font-mono font-bold text-[#00ff87] tracking-widest uppercase mb-3">
                      Most Popular
                    </span>
                  )}
                  <div className="text-xs text-white/40 font-mono uppercase tracking-wider mb-1">
                    {tier.name}
                  </div>
                  <div className="text-[10px] text-white/30 mb-4">{tier.range}</div>
                  <div className="text-2xl font-bold text-white mb-1">{fmt(tier.price)}</div>
                  <div className="text-[11px] text-white/40 mb-4">one-time payment</div>
                  <div className="mt-auto pt-4 border-t border-white/10">
                    <div className="text-[11px] text-white/30">
                      vs{" "}
                      <span className="text-red-400 font-medium">{fmt(cloud)}/year</span>{" "}
                      with OpenAI
                    </div>
                    <div className="text-[11px] text-[#00ff87] font-medium mt-1">
                      Saves {fmt(cloud)} yr 1
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="text-center mt-10">
            <Link
              href="/register"
              className="inline-block bg-[#00ff87] text-black font-semibold px-8 py-4 rounded-lg text-base hover:bg-[#00e87a] transition-colors"
            >
              Start 7-Day Free Trial
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/10 py-8 px-6 text-center text-sm text-white/30">
        FleetMind — Private AI Infrastructure for the Enterprise
      </footer>
    </main>
  );
}
