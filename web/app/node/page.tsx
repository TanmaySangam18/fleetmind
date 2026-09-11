"use client";

/**
 * FleetMind Browser Node
 * ----------------------
 * Turns any phone browser (iPhone Safari, Android Chrome) into a FleetMind
 * mesh node. No dependencies beyond React and the browser's native fetch API.
 *
 * Route: /node
 */

import { useEffect, useRef, useState, useCallback } from "react";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function generateUUID(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  // Fallback for older Safari
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function parseDeviceModel(ua: string): string {
  if (/iPhone/i.test(ua)) return "iPhone";
  if (/iPad/i.test(ua)) return "iPad";
  if (/Android/i.test(ua)) return "Android";
  if (/Mac/i.test(ua)) return "Mac Browser";
  if (/Windows/i.test(ua)) return "Windows Browser";
  return "Browser";
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return `${h}h ${rem}m`;
}

// ---------------------------------------------------------------------------
// localStorage keys
// ---------------------------------------------------------------------------

const LS_LICENSE   = "fm_license_key";
const LS_DEVICE_ID = "fm_device_id";
const LS_BACKEND   = "fm_backend_url";
const LS_QUERIES   = "fm_queries_processed";

// ---------------------------------------------------------------------------
// NoSleep: keep the screen awake with a tiny looping video trick.
// Works on iOS Safari (the only way that doesn't require special permissions).
// ---------------------------------------------------------------------------

function useNoSleep(active: boolean) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (!active) return;

    // Create a tiny 1×1 mp4 encoded as a base64 data URI.
    // This is the canonical 1-frame silent mp4 used by NoSleep.js.
    const tinyMp4 =
      "data:video/mp4;base64," +
      "AAAAIGZ0eXBtcDQyAAAAAG1wNDJtcDQxaXNvbWlzbzIAAAAA" +
      "AAAADWZ0eXBtcDQyAAAA";

    const video = document.createElement("video");
    video.setAttribute("playsinline", "");
    video.setAttribute("muted", "");
    video.setAttribute("loop", "");
    video.style.position = "fixed";
    video.style.top = "-1px";
    video.style.left = "-1px";
    video.style.width = "1px";
    video.style.height = "1px";
    video.style.opacity = "0";
    video.style.pointerEvents = "none";

    const source = document.createElement("source");
    source.src  = tinyMp4;
    source.type = "video/mp4";
    video.appendChild(source);

    document.body.appendChild(video);
    videoRef.current = video;

    video.play().catch(() => {
      // Autoplay may be blocked — nothing we can do silently.
    });

    return () => {
      video.pause();
      document.body.removeChild(video);
      videoRef.current = null;
    };
  }, [active]);
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

type NodeStatus = "setup" | "active" | "error";

export default function NodePage() {
  // ---- persistent state from localStorage ----
  const [licenseKey,   setLicenseKey]   = useState("");
  const [deviceId,     setDeviceId]     = useState("");
  const [backendUrl,   setBackendUrl]   = useState("");
  const [queriesCount, setQueriesCount] = useState(0);
  const [deviceModel,  setDeviceModel]  = useState("Browser");

  // ---- runtime state ----
  const [status,       setStatus]       = useState<NodeStatus>("setup");
  const [uptimeSeconds, setUptimeSeconds] = useState(0);
  const [lastError,    setLastError]    = useState("");
  const [showSettings, setShowSettings] = useState(false);

  // ---- refs so interval callbacks always see current values ----
  const licenseRef   = useRef(licenseKey);
  const deviceIdRef  = useRef(deviceId);
  const backendRef   = useRef(backendUrl);
  const queriesRef   = useRef(queriesCount);
  const startTimeRef = useRef<number>(0);

  // Keep refs in sync
  useEffect(() => { licenseRef.current  = licenseKey;    }, [licenseKey]);
  useEffect(() => { deviceIdRef.current = deviceId;      }, [deviceId]);
  useEffect(() => { backendRef.current  = backendUrl;    }, [backendUrl]);
  useEffect(() => { queriesRef.current  = queriesCount;  }, [queriesCount]);

  // ---- load from localStorage on mount ----
  useEffect(() => {
    const savedLicense = localStorage.getItem(LS_LICENSE)   ?? "";
    const savedBackend = localStorage.getItem(LS_BACKEND)   ?? "";
    const savedQueries = parseInt(localStorage.getItem(LS_QUERIES) ?? "0", 10);
    const ua           = navigator.userAgent;

    // Get or create a stable device ID
    let savedId = localStorage.getItem(LS_DEVICE_ID);
    if (!savedId) {
      savedId = `browser-${generateUUID()}`;
      localStorage.setItem(LS_DEVICE_ID, savedId);
    }

    // Default backend: same origin as the page
    const defaultBackend =
      savedBackend ||
      (typeof window !== "undefined"
        ? `${window.location.protocol}//${window.location.hostname}:8000`
        : "http://localhost:8000");

    setLicenseKey(savedLicense);
    setDeviceId(savedId);
    setBackendUrl(defaultBackend);
    setQueriesCount(savedQueries);
    setDeviceModel(parseDeviceModel(ua));

    // If we already have a license, go straight to active
    if (savedLicense) {
      setStatus("active");
    }
  }, []);

  // ---- start tracking uptime once active ----
  useEffect(() => {
    if (status !== "active") return;
    startTimeRef.current = Date.now();

    const tick = setInterval(() => {
      setUptimeSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);
    return () => clearInterval(tick);
  }, [status]);

  // ---- keep screen awake ----
  useNoSleep(status === "active");

  // ---- heartbeat ----
  const sendHeartbeat = useCallback(async () => {
    const license = licenseRef.current;
    const id      = deviceIdRef.current;
    const backend = backendRef.current;
    const queries = queriesRef.current;

    if (!license || !id || !backend) return;

    const uptime = startTimeRef.current
      ? Math.floor((Date.now() - startTimeRef.current) / 1000)
      : 0;

    try {
      const res = await fetch(`${backend.replace(/\/$/, "")}/api/device/heartbeat`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          license_key:       license,
          device_id:         id,
          device_model:      parseDeviceModel(navigator.userAgent),
          queries_processed: queries,
          uptime_seconds:    uptime,
        }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        setLastError(detail?.detail ?? `HTTP ${res.status}`);
        setStatus("error");
      } else {
        setLastError("");
        if (status !== "active") setStatus("active");
      }
    } catch (err) {
      setLastError(err instanceof Error ? err.message : "Network error");
      setStatus("error");
    }
  }, [status]);

  useEffect(() => {
    if (status !== "active") return;
    // Send one immediately, then every 60 s
    sendHeartbeat();
    const interval = setInterval(sendHeartbeat, 60_000);
    return () => clearInterval(interval);
  }, [status, sendHeartbeat]);

  // ---- warn before tab close ----
  useEffect(() => {
    if (status !== "active") return;
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      const msg = "Closing this page removes your device from the FleetMind mesh.";
      e.preventDefault();
      e.returnValue = msg;
      return msg;
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [status]);

  // ---- handlers ----
  function handleActivate() {
    if (!licenseKey.trim()) return;
    localStorage.setItem(LS_LICENSE, licenseKey.trim());
    localStorage.setItem(LS_BACKEND, backendUrl.trim());
    setLicenseKey(licenseKey.trim());
    setBackendUrl(backendUrl.trim());
    setStatus("active");
  }

  function handleLicenseKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") handleActivate();
  }

  // ---------------------------------------------------------------------------
  // Render: Setup screen
  // ---------------------------------------------------------------------------
  if (status === "setup") {
    return (
      <main
        className="min-h-screen flex flex-col items-center justify-center px-6"
        style={{ background: "#0a0a0a", color: "#fff" }}
      >
        <div style={{ maxWidth: 400, width: "100%" }}>
          {/* Logo */}
          <div style={{ textAlign: "center", marginBottom: 40 }}>
            <div
              style={{
                display: "inline-block",
                width: 56,
                height: 56,
                borderRadius: 14,
                background: "rgba(0,255,135,0.1)",
                border: "1px solid rgba(0,255,135,0.3)",
                lineHeight: "56px",
                textAlign: "center",
                fontSize: 28,
                marginBottom: 16,
              }}
            >
              ◎
            </div>
            <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0 }}>
              FleetMind Node
            </h1>
            <p style={{ color: "rgba(255,255,255,0.4)", fontSize: 14, marginTop: 8 }}>
              Turn this browser into a mesh compute node.
            </p>
          </div>

          {/* License input */}
          <label
            style={{ display: "block", fontSize: 12, color: "rgba(255,255,255,0.5)", marginBottom: 6 }}
          >
            LICENSE KEY
          </label>
          <input
            type="text"
            placeholder="FM-XXXX-XXXX-XXXX  or  trial token"
            value={licenseKey}
            onChange={(e) => setLicenseKey(e.target.value)}
            onKeyDown={handleLicenseKeyDown}
            style={{
              width: "100%",
              padding: "12px 14px",
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.15)",
              borderRadius: 8,
              color: "#fff",
              fontSize: 14,
              outline: "none",
              boxSizing: "border-box",
              marginBottom: 16,
              fontFamily: "monospace",
            }}
          />

          {/* Backend URL */}
          <label
            style={{ display: "block", fontSize: 12, color: "rgba(255,255,255,0.5)", marginBottom: 6 }}
          >
            BACKEND URL
          </label>
          <input
            type="url"
            placeholder="http://192.168.1.x:8000"
            value={backendUrl}
            onChange={(e) => setBackendUrl(e.target.value)}
            style={{
              width: "100%",
              padding: "12px 14px",
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.15)",
              borderRadius: 8,
              color: "#fff",
              fontSize: 13,
              outline: "none",
              boxSizing: "border-box",
              marginBottom: 24,
              fontFamily: "monospace",
            }}
          />

          <button
            onClick={handleActivate}
            disabled={!licenseKey.trim()}
            style={{
              width: "100%",
              padding: "14px",
              background: licenseKey.trim() ? "#00ff87" : "rgba(0,255,135,0.2)",
              color: licenseKey.trim() ? "#000" : "rgba(0,255,135,0.4)",
              border: "none",
              borderRadius: 8,
              fontWeight: 700,
              fontSize: 15,
              cursor: licenseKey.trim() ? "pointer" : "not-allowed",
            }}
          >
            Join Mesh
          </button>

          <p style={{ textAlign: "center", marginTop: 16, fontSize: 12, color: "rgba(255,255,255,0.25)" }}>
            Device ID: {deviceId.slice(0, 20)}...
          </p>
        </div>
      </main>
    );
  }

  // ---------------------------------------------------------------------------
  // Render: Active node screen
  // ---------------------------------------------------------------------------
  const isError = status === "error";

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#0a0a0a",
        color: "#fff",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
        userSelect: "none",
        WebkitUserSelect: "none",
      }}
    >
      {/* Pulsing status dot */}
      <div style={{ position: "relative", marginBottom: 32 }}>
        {/* Outer pulse ring */}
        <div
          style={{
            position: "absolute",
            inset: -12,
            borderRadius: "50%",
            background: isError
              ? "rgba(248,113,113,0.15)"
              : "rgba(0,255,135,0.12)",
            animation: "pulse 2s ease-in-out infinite",
          }}
        />
        {/* Inner dot */}
        <div
          style={{
            width: 64,
            height: 64,
            borderRadius: "50%",
            background: isError ? "#f87171" : "#00ff87",
            boxShadow: isError
              ? "0 0 32px rgba(248,113,113,0.6)"
              : "0 0 32px rgba(0,255,135,0.6)",
          }}
        />
      </div>

      {/* Title */}
      <h1
        style={{
          fontSize: 28,
          fontWeight: 700,
          textAlign: "center",
          margin: 0,
          letterSpacing: "-0.5px",
        }}
      >
        FleetMind Node{" "}
        <span style={{ color: isError ? "#f87171" : "#00ff87" }}>
          {isError ? "Disconnected" : "Active"}
        </span>
      </h1>

      {/* Device model badge */}
      <div
        style={{
          marginTop: 12,
          fontSize: 13,
          color: "rgba(255,255,255,0.4)",
          fontFamily: "monospace",
        }}
      >
        {deviceModel}
      </div>

      {/* Error notice */}
      {isError && lastError && (
        <div
          style={{
            marginTop: 20,
            padding: "10px 16px",
            background: "rgba(248,113,113,0.1)",
            border: "1px solid rgba(248,113,113,0.3)",
            borderRadius: 8,
            fontSize: 13,
            color: "#f87171",
            textAlign: "center",
            maxWidth: 340,
          }}
        >
          {lastError} — retrying in 60s
        </div>
      )}

      {/* Live stats */}
      <div
        style={{
          marginTop: 40,
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 16,
          width: "100%",
          maxWidth: 360,
        }}
      >
        {[
          { label: "QUERIES SERVED", value: queriesCount.toLocaleString() },
          { label: "UPTIME", value: formatUptime(uptimeSeconds) },
          { label: "STATUS", value: isError ? "Error" : "Active" },
        ].map(({ label, value }) => (
          <div
            key={label}
            style={{
              background: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 10,
              padding: "14px 8px",
              textAlign: "center",
            }}
          >
            <div
              style={{
                fontSize: 10,
                color: "rgba(255,255,255,0.35)",
                letterSpacing: "0.08em",
                marginBottom: 6,
                fontFamily: "monospace",
              }}
            >
              {label}
            </div>
            <div
              style={{
                fontSize: label === "UPTIME" ? 15 : 20,
                fontWeight: 700,
                fontFamily: "monospace",
                color: label === "STATUS"
                  ? isError ? "#f87171" : "#00ff87"
                  : "#fff",
              }}
            >
              {value}
            </div>
          </div>
        ))}
      </div>

      {/* Device ID */}
      <div
        style={{
          marginTop: 32,
          fontSize: 11,
          color: "rgba(255,255,255,0.2)",
          fontFamily: "monospace",
          textAlign: "center",
        }}
      >
        {deviceId.slice(0, 32)}...
      </div>

      {/* Warning strip */}
      <div
        style={{
          position: "fixed",
          bottom: 0,
          left: 0,
          right: 0,
          background: "rgba(0,0,0,0.9)",
          borderTop: "1px solid rgba(255,255,255,0.08)",
          padding: "12px 16px",
          fontSize: 12,
          color: "rgba(255,255,255,0.35)",
          textAlign: "center",
        }}
      >
        Keep this page open. Closing removes your device from the mesh.
      </div>

      {/* Settings toggle */}
      <button
        onClick={() => setShowSettings((v) => !v)}
        style={{
          position: "fixed",
          top: 16,
          right: 16,
          background: "rgba(255,255,255,0.06)",
          border: "1px solid rgba(255,255,255,0.12)",
          borderRadius: 8,
          color: "rgba(255,255,255,0.5)",
          padding: "6px 12px",
          fontSize: 12,
          cursor: "pointer",
        }}
      >
        Settings
      </button>

      {/* Settings panel */}
      {showSettings && (
        <div
          style={{
            position: "fixed",
            top: 52,
            right: 16,
            background: "#111",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: 10,
            padding: 16,
            width: 280,
            zIndex: 100,
          }}
        >
          <p style={{ fontSize: 11, color: "rgba(255,255,255,0.4)", marginBottom: 8 }}>
            Backend URL
          </p>
          <input
            type="url"
            value={backendUrl}
            onChange={(e) => {
              setBackendUrl(e.target.value);
              localStorage.setItem(LS_BACKEND, e.target.value);
            }}
            style={{
              width: "100%",
              padding: "8px 10px",
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.15)",
              borderRadius: 6,
              color: "#fff",
              fontSize: 12,
              fontFamily: "monospace",
              boxSizing: "border-box",
              outline: "none",
            }}
          />
          <button
            onClick={() => {
              localStorage.removeItem(LS_LICENSE);
              localStorage.removeItem(LS_QUERIES);
              setStatus("setup");
              setShowSettings(false);
            }}
            style={{
              marginTop: 12,
              width: "100%",
              padding: "8px",
              background: "rgba(248,113,113,0.1)",
              border: "1px solid rgba(248,113,113,0.3)",
              borderRadius: 6,
              color: "#f87171",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            Reset &amp; Leave Mesh
          </button>
        </div>
      )}

      {/* Pulse keyframes injected via a style tag */}
      <style>{`
        @keyframes pulse {
          0%, 100% { transform: scale(1);   opacity: 0.6; }
          50%       { transform: scale(1.5); opacity: 0;   }
        }
      `}</style>
    </main>
  );
}
