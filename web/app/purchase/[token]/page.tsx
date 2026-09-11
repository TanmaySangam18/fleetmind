"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

const TIER_MAP: Record<
  string,
  { name: string; range: string; price: number }
> = {
  startup: { name: "Startup", range: "1–200 employees", price: 4_000 },
  growth: { name: "Growth", range: "201–1,000 employees", price: 15_000 },
  scale: { name: "Scale", range: "1,001–5,000 employees", price: 50_000 },
  enterprise: {
    name: "Enterprise",
    range: "5,001–20,000 employees",
    price: 150_000,
  },
  global: { name: "Global", range: "20,000+ employees", price: 400_000 },
};

interface PurchaseInfo {
  tier: string;
  company_name: string;
  price?: number;
}

export default function PurchasePage() {
  const params = useParams();
  const token = params.token as string;

  const [info, setInfo] = useState<PurchaseInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [paying, setPaying] = useState(false);
  const [licenseKey, setLicenseKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchInfo() {
      setLoading(true);
      try {
        const res = await fetch(`http://localhost:8000/api/dashboard/${token}`);
        if (res.ok) {
          const data = await res.json();
          setInfo({
            tier: data.tier || "growth",
            company_name: data.company_name || "Your Company",
            price: data.price,
          });
        }
      } catch {
        // Use defaults if backend unavailable
        setInfo({ tier: "growth", company_name: "Your Company" });
      } finally {
        setLoading(false);
      }
    }
    fetchInfo();
  }, [token]);

  const tier =
    info?.tier && TIER_MAP[info.tier]
      ? TIER_MAP[info.tier]
      : TIER_MAP["growth"];

  const finalPrice = info?.price || tier.price;

  async function handlePurchase() {
    setPaying(true);
    setError(null);
    try {
      const res = await fetch("http://localhost:8000/api/purchase", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });

      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || d.message || "Payment failed");
      }

      const data = await res.json();
      setLicenseKey(data.license_key || data.permanent_key || token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment error");
    } finally {
      setPaying(false);
    }
  }

  if (licenseKey) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] text-white flex items-center justify-center px-6">
        <div className="max-w-lg w-full">
          <div className="border border-[#00ff87]/30 bg-[#00ff87]/5 rounded-xl p-8 text-center">
            <div className="text-xs font-mono text-[#00ff87] tracking-widest uppercase mb-6">
              License Activated
            </div>
            <h2 className="text-2xl font-bold mb-2">Welcome to FleetMind</h2>
            <p className="text-white/50 text-sm mb-8">
              Your permanent license key is below. Store it securely — it
              activates FleetMind across your entire fleet.
            </p>

            <div className="bg-[#0a0a0a] border border-white/10 rounded-lg p-5 mb-6 text-left">
              <div className="text-xs text-white/30 font-mono mb-2 uppercase tracking-wider">
                Permanent License Key
              </div>
              <code className="text-[#00ff87] font-mono text-sm break-all leading-relaxed">
                {licenseKey}
              </code>
            </div>

            <div className="flex flex-col sm:flex-row gap-3">
              <Link
                href={`/dashboard/${token}`}
                className="flex-1 bg-white/10 border border-white/10 text-white font-medium px-4 py-3 rounded-lg text-sm text-center hover:bg-white/15 transition-colors"
              >
                Go to Dashboard
              </Link>
              <button
                onClick={() => navigator.clipboard.writeText(licenseKey)}
                className="flex-1 bg-[#00ff87] text-black font-semibold px-4 py-3 rounded-lg text-sm hover:bg-[#00e87a] transition-colors"
              >
                Copy License Key
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <nav className="border-b border-white/10 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/" className="text-lg font-semibold tracking-tight hover:text-white/80 transition-colors">
              FleetMind
            </Link>
            <span className="text-white/20">/</span>
            <Link
              href={`/dashboard/${token}`}
              className="text-sm text-white/50 hover:text-white/80 transition-colors"
            >
              Dashboard
            </Link>
            <span className="text-white/20">/</span>
            <span className="text-sm text-white/50">Purchase</span>
          </div>
        </div>
      </nav>

      <div className="max-w-2xl mx-auto px-6 pt-20 pb-24">
        <div className="mb-10">
          <div className="text-xs font-mono text-[#00ff87] tracking-widest uppercase mb-4">
            One-Time Purchase
          </div>
          <h1 className="text-3xl font-bold mb-3">Complete your license</h1>
          <p className="text-white/50 text-sm">
            Pay once. Own FleetMind forever. No recurring charges.
          </p>
        </div>

        {loading ? (
          <div className="text-sm text-white/30 font-mono">Loading order details...</div>
        ) : (
          <div className="space-y-5">
            {/* Order summary */}
            <div className="border border-white/10 bg-white/5 rounded-xl p-6">
              <h2 className="text-sm font-semibold mb-5 text-white/70 uppercase tracking-wider">
                Order Summary
              </h2>

              <div className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-white/60">Company</span>
                  <span className="font-medium">{info?.company_name || "—"}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-white/60">Plan</span>
                  <span className="font-medium">{tier.name}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-white/60">Fleet size</span>
                  <span className="font-medium">{tier.range}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-white/60">License type</span>
                  <span className="font-medium text-[#00ff87]">Perpetual</span>
                </div>
              </div>

              <div className="border-t border-white/10 mt-5 pt-5 flex justify-between items-center">
                <span className="text-sm text-white/60">Total due today</span>
                <div className="text-right">
                  <div className="text-2xl font-bold font-mono">
                    ${finalPrice.toLocaleString()}
                  </div>
                  <div className="text-xs text-white/30">one-time payment</div>
                </div>
              </div>
            </div>

            {/* Payment form */}
            <div className="border border-white/10 bg-white/5 rounded-xl p-6">
              <h2 className="text-sm font-semibold mb-5 text-white/70 uppercase tracking-wider">
                Payment
              </h2>

              {/* Mock card fields */}
              <div className="space-y-4 mb-6">
                <div>
                  <label className="block text-xs text-white/50 mb-2">Card Number</label>
                  <input
                    type="text"
                    placeholder="4242 4242 4242 4242"
                    disabled
                    className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-sm text-white/30 placeholder-white/20 cursor-not-allowed"
                  />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-white/50 mb-2">Expiry</label>
                    <input
                      type="text"
                      placeholder="MM / YY"
                      disabled
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-sm text-white/30 placeholder-white/20 cursor-not-allowed"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-white/50 mb-2">CVC</label>
                    <input
                      type="text"
                      placeholder="123"
                      disabled
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-sm text-white/30 placeholder-white/20 cursor-not-allowed"
                    />
                  </div>
                </div>
              </div>

              <div className="text-xs text-white/30 bg-white/5 border border-white/10 rounded-lg px-4 py-3 mb-5 font-mono">
                Stripe integration — sandbox mode. No real charge.
              </div>

              {error && (
                <div className="text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-3 mb-4">
                  {error}
                </div>
              )}

              <button
                onClick={handlePurchase}
                disabled={paying}
                className="w-full bg-[#00ff87] text-black font-semibold py-3.5 rounded-lg text-sm hover:bg-[#00e87a] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {paying
                  ? "Processing..."
                  : `Pay Now — $${finalPrice.toLocaleString()}`}
              </button>

              <div className="flex items-center justify-center gap-4 mt-4">
                <span className="text-xs text-white/25 flex items-center gap-1">
                  <span className="w-3 h-3 border border-white/20 rounded-sm inline-block" />
                  Secured by Stripe
                </span>
                <span className="text-xs text-white/25">256-bit TLS</span>
                <span className="text-xs text-white/25">SOC 2 Type II</span>
              </div>
            </div>

            <p className="text-xs text-white/25 text-center leading-relaxed">
              By completing your purchase, you receive a perpetual license. No
              subscriptions. No renewals. Data never leaves your infrastructure.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
