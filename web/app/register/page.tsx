"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

const EMPLOYEE_TIERS = [
  { label: "1–200 employees (Startup)", value: "startup" },
  { label: "201–1,000 employees (Growth)", value: "growth" },
  { label: "1,001–5,000 employees (Scale)", value: "scale" },
  { label: "5,001–20,000 employees (Enterprise)", value: "enterprise" },
  { label: "20,000+ employees (Global)", value: "global" },
];

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    companyName: "",
    workEmail: "",
    employeeCount: "",
    registrationNumber: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);

  function handleChange(
    e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>
  ) {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const res = await fetch("http://localhost:8000/api/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || data.message || "Registration failed");
      }

      const data = await res.json();
      const trialToken: string = data.token || data.trial_token;
      setToken(trialToken);

      setTimeout(() => {
        router.push(`/dashboard/${trialToken}`);
      }, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  if (token) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] text-white flex items-center justify-center px-6">
        <div className="max-w-md w-full text-center">
          <div className="w-12 h-12 bg-[#00ff87]/10 border border-[#00ff87]/30 rounded-full mx-auto mb-6 flex items-center justify-center">
            <span className="text-[#00ff87] text-xl font-bold">+</span>
          </div>
          <h2 className="text-2xl font-bold mb-2">Trial activated</h2>
          <p className="text-white/50 text-sm mb-6">
            Your 7-day trial is live. Save your token.
          </p>
          <div className="bg-white/5 border border-white/10 rounded-lg p-4 font-mono text-sm text-[#00ff87] break-all mb-4">
            {token}
          </div>
          <p className="text-xs text-white/30">Redirecting to dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <nav className="border-b border-white/10 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <Link href="/" className="text-lg font-semibold tracking-tight hover:text-white/80 transition-colors">
            FleetMind
          </Link>
        </div>
      </nav>

      <div className="max-w-lg mx-auto px-6 pt-20 pb-24">
        <div className="mb-10">
          <div className="text-xs font-mono text-[#00ff87] tracking-widest uppercase mb-4">
            7-Day Free Trial
          </div>
          <h1 className="text-3xl font-bold mb-3">Start your trial</h1>
          <p className="text-white/50 text-sm leading-relaxed">
            No credit card required. Full access to FleetMind for 7 days.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-white/70 mb-2">
              Company Name
            </label>
            <input
              type="text"
              name="companyName"
              value={form.companyName}
              onChange={handleChange}
              required
              placeholder="Acme Corp"
              className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-sm text-white placeholder-white/25 focus:outline-none focus:border-[#00ff87]/50 focus:bg-white/8 transition-colors"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-white/70 mb-2">
              Work Email
            </label>
            <input
              type="email"
              name="workEmail"
              value={form.workEmail}
              onChange={handleChange}
              required
              placeholder="you@acmecorp.com"
              className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-sm text-white placeholder-white/25 focus:outline-none focus:border-[#00ff87]/50 focus:bg-white/8 transition-colors"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-white/70 mb-2">
              Employee Count
            </label>
            <select
              name="employeeCount"
              value={form.employeeCount}
              onChange={handleChange}
              required
              className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-sm text-white focus:outline-none focus:border-[#00ff87]/50 transition-colors appearance-none"
            >
              <option value="" disabled className="bg-[#0a0a0a] text-white/30">
                Select your tier
              </option>
              {EMPLOYEE_TIERS.map((t) => (
                <option key={t.value} value={t.value} className="bg-[#111] text-white">
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-white/70 mb-2">
              Company Registration Number
            </label>
            <input
              type="text"
              name="registrationNumber"
              value={form.registrationNumber}
              onChange={handleChange}
              required
              placeholder="e.g. EIN, CRN, or local equivalent"
              className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-sm text-white placeholder-white/25 focus:outline-none focus:border-[#00ff87]/50 focus:bg-white/8 transition-colors"
            />
          </div>

          {error && (
            <div className="text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-3">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-[#00ff87] text-black font-semibold py-3.5 rounded-lg text-sm hover:bg-[#00e87a] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? "Activating trial..." : "Start 7-Day Free Trial"}
          </button>
        </form>

        <p className="text-xs text-white/25 text-center mt-6 leading-relaxed">
          By registering, you agree to FleetMind&apos;s Terms of Service. Your
          data stays on-premise.
        </p>
      </div>
    </div>
  );
}
