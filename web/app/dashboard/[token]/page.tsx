"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

interface Device {
  device_id: string;
  model: string;
  status: "active" | "idle" | "offline";
  queries: number;
  last_seen: string;
}

interface DashboardData {
  license_status: "Trial" | "Active";
  days_remaining: number;
  active_devices: number;
  queries_today: number;
  total_queries: number;
  money_saved: number;
  devices: Device[];
  company_name?: string;
}

function StatusBadge({ status }: { status: "Trial" | "Active" }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs font-mono px-2.5 py-1 rounded-full border ${
        status === "Trial"
          ? "text-yellow-400 border-yellow-400/30 bg-yellow-400/10"
          : "text-[#00ff87] border-[#00ff87]/30 bg-[#00ff87]/10"
      }`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${
          status === "Trial" ? "bg-yellow-400" : "bg-[#00ff87]"
        }`}
      />
      {status}
    </span>
  );
}

function DeviceStatusDot({ status }: { status: Device["status"] }) {
  const colors = {
    active: "bg-[#00ff87]",
    idle: "bg-yellow-400",
    offline: "bg-white/20",
  };
  return (
    <span className={`inline-block w-2 h-2 rounded-full ${colors[status]}`} />
  );
}

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="border border-white/10 bg-white/5 rounded-xl p-5">
      <div className="text-xs text-white/40 font-mono uppercase tracking-wider mb-2">
        {label}
      </div>
      <div className="text-2xl font-bold text-white font-mono">{value}</div>
      {sub && <div className="text-xs text-white/30 mt-1">{sub}</div>}
    </div>
  );
}

export default function DashboardPage() {
  const params = useParams();
  const token = params.token as string;

  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchDashboard = useCallback(async () => {
    try {
      const res = await fetch(`http://localhost:8000/api/dashboard/${token}`);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || d.message || "Failed to load dashboard");
      }
      const json = await res.json();
      setData(json);
      setLastUpdated(new Date());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection error");
    }
  }, [token]);

  useEffect(() => {
    fetchDashboard();
    const interval = setInterval(fetchDashboard, 10_000);
    return () => clearInterval(interval);
  }, [fetchDashboard]);

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      {/* Header */}
      <nav className="border-b border-white/10 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="text-lg font-semibold tracking-tight hover:text-white/80 transition-colors"
            >
              FleetMind
            </Link>
            <span className="text-white/20">/</span>
            <span className="text-sm text-white/50">Dashboard</span>
          </div>
          <div className="flex items-center gap-3">
            {data && <StatusBadge status={data.license_status} />}
            {data && (
              <span className="text-xs text-white/40 font-mono">
                {data.days_remaining}d remaining
              </span>
            )}
          </div>
        </div>
      </nav>

      <div className="max-w-7xl mx-auto px-6 py-10">
        {/* Page title */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold">
              {data?.company_name ? `${data.company_name}` : "FleetMind Dashboard"}
            </h1>
            <p className="text-sm text-white/40 mt-1 font-mono">
              token: {token.slice(0, 16)}...
            </p>
          </div>
          {lastUpdated && (
            <div className="text-xs text-white/25 font-mono">
              Updated {lastUpdated.toLocaleTimeString()}
            </div>
          )}
        </div>

        {error && (
          <div className="mb-8 text-sm text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-5 py-4">
            {error} — retrying automatically.
          </div>
        )}

        {/* Stat cards */}
        {data && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
              <StatCard
                label="Active Devices"
                value={data.active_devices.toLocaleString()}
                sub="phones online"
              />
              <StatCard
                label="Queries Today"
                value={data.queries_today.toLocaleString()}
                sub="since midnight"
              />
              <StatCard
                label="Total Queries"
                value={data.total_queries.toLocaleString()}
                sub="all time"
              />
              <StatCard
                label="Money Saved"
                value={`$${data.money_saved.toLocaleString()}`}
                sub="vs OpenAI API"
              />
            </div>

            {/* Device table */}
            <div className="border border-white/10 bg-white/5 rounded-xl overflow-hidden mb-8">
              <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between">
                <h2 className="text-sm font-semibold">Device Fleet</h2>
                <span className="text-xs text-white/30 font-mono">
                  {data.devices.length} registered
                </span>
              </div>

              {data.devices.length === 0 ? (
                <div className="px-6 py-12 text-center text-sm text-white/30">
                  No devices connected yet. Install the FleetMind agent on employee devices.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-white/5">
                        <th className="text-left px-6 py-3 text-xs font-medium text-white/40 uppercase tracking-wider">
                          Device ID
                        </th>
                        <th className="text-left px-6 py-3 text-xs font-medium text-white/40 uppercase tracking-wider">
                          Model
                        </th>
                        <th className="text-left px-6 py-3 text-xs font-medium text-white/40 uppercase tracking-wider">
                          Status
                        </th>
                        <th className="text-right px-6 py-3 text-xs font-medium text-white/40 uppercase tracking-wider">
                          Queries
                        </th>
                        <th className="text-right px-6 py-3 text-xs font-medium text-white/40 uppercase tracking-wider">
                          Last Seen
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.devices.map((device, i) => (
                        <tr
                          key={device.device_id}
                          className={`${
                            i < data.devices.length - 1
                              ? "border-b border-white/5"
                              : ""
                          } hover:bg-white/5 transition-colors`}
                        >
                          <td className="px-6 py-3 font-mono text-xs text-white/70">
                            {device.device_id}
                          </td>
                          <td className="px-6 py-3 text-white/70">
                            {device.model}
                          </td>
                          <td className="px-6 py-3">
                            <span className="inline-flex items-center gap-2 text-xs">
                              <DeviceStatusDot status={device.status} />
                              <span className="capitalize text-white/60">
                                {device.status}
                              </span>
                            </span>
                          </td>
                          <td className="px-6 py-3 text-right font-mono text-white/70">
                            {device.queries.toLocaleString()}
                          </td>
                          <td className="px-6 py-3 text-right text-xs text-white/40 font-mono">
                            {device.last_seen}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Upgrade CTA */}
            {data.license_status === "Trial" && (
              <div className="border border-[#00ff87]/20 bg-[#00ff87]/5 rounded-xl px-6 py-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
                <div>
                  <div className="text-sm font-semibold mb-1">
                    {data.days_remaining} days left in your trial
                  </div>
                  <div className="text-xs text-white/50">
                    Upgrade to a full license and keep everything running.
                  </div>
                </div>
                <Link
                  href={`/purchase/${token}`}
                  className="shrink-0 bg-[#00ff87] text-black font-semibold px-5 py-2.5 rounded-lg text-sm hover:bg-[#00e87a] transition-colors"
                >
                  Upgrade to Full License
                </Link>
              </div>
            )}
          </>
        )}

        {!data && !error && (
          <div className="text-center py-24 text-white/30 text-sm font-mono">
            Connecting to backend...
          </div>
        )}
      </div>
    </div>
  );
}
