#!/usr/bin/env python3
"""
FleetMind Mac Node Agent
Registers this Mac as a FleetMind mesh node and proxies Ollama locally.

Usage:
    python3 agent.py --license FM-XXXX-XXXX-XXXX --backend http://localhost:8000
"""

import argparse
import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError

import requests
from zeroconf import ServiceInfo, Zeroconf

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LOCAL_SERVER_PORT = 11435       # Mac node listens here (Android uses 11434)
OLLAMA_URL        = "http://localhost:11434/api/generate"
OLLAMA_MODEL      = "llama3.2:1b"
HEARTBEAT_INTERVAL = 60         # seconds
DEVICE_MODEL      = "Mac (Ollama Host)"


# ---------------------------------------------------------------------------
# Shared state (threadsafe via GIL for simple int increments)
# ---------------------------------------------------------------------------

class NodeState:
    def __init__(self):
        self.queries_processed = 0
        self.start_time        = time.time()
        self.license_key: str  = ""
        self.backend_url: str  = ""

    @property
    def uptime_seconds(self) -> int:
        return int(time.time() - self.start_time)

    @property
    def device_id(self) -> str:
        return f"mac-node-{socket.gethostname()}"


state = NodeState()


# ---------------------------------------------------------------------------
# Heartbeat thread
# ---------------------------------------------------------------------------

def heartbeat_loop():
    """POST a heartbeat to the backend every HEARTBEAT_INTERVAL seconds."""
    url = f"{state.backend_url.rstrip('/')}/api/device/heartbeat"
    while True:
        try:
            payload = {
                "license_key":      state.license_key,
                "device_id":        state.device_id,
                "device_model":     DEVICE_MODEL,
                "queries_processed": state.queries_processed,
                "uptime_seconds":   state.uptime_seconds,
            }
            resp = requests.post(url, json=payload, timeout=10)
            mesh_status = "healthy" if resp.ok else f"error {resp.status_code}"
        except requests.RequestException as exc:
            mesh_status = f"unreachable ({exc})"

        print(
            f"  Mac node active — {state.queries_processed} queries processed"
            f" — mesh: {mesh_status}",
            flush=True,
        )
        time.sleep(HEARTBEAT_INTERVAL)


# ---------------------------------------------------------------------------
# Local HTTP server — POST /generate proxies to Ollama
# ---------------------------------------------------------------------------

class OllamaProxyHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler: only POST /generate is supported."""

    # Silence the default per-request log lines; we print our own summary.
    def log_message(self, fmt, *args):  # noqa: D102
        pass

    def _send_json(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/generate":
            self._send_json(404, {"error": "Not found — only POST /generate is supported"})
            return

        # Read request body.
        length = int(self.headers.get("Content-Length", 0))
        raw    = self.rfile.read(length) if length > 0 else b"{}"
        try:
            incoming = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON body"})
            return

        prompt = incoming.get("prompt", "")
        if not prompt:
            self._send_json(400, {"error": "Missing 'prompt' field"})
            return

        # Forward to local Ollama.
        ollama_payload = json.dumps({
            "model":  OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
        }).encode()

        try:
            req      = Request(OLLAMA_URL, data=ollama_payload,
                               headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=120) as resp:
                ollama_resp = json.loads(resp.read())
            response_text = ollama_resp.get("response", "")
            state.queries_processed += 1
            self._send_json(200, {"response": response_text})
        except URLError as exc:
            self._send_json(502, {"error": f"Ollama unreachable: {exc}"})
        except Exception as exc:  # noqa: BLE001
            self._send_json(500, {"error": str(exc)})

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {
                "status":            "ok",
                "device_id":         state.device_id,
                "queries_processed": state.queries_processed,
                "uptime_seconds":    state.uptime_seconds,
            })
        else:
            self._send_json(404, {"error": "Not found"})


def start_local_server():
    """Start the proxy HTTP server in the current thread (blocking)."""
    server = HTTPServer(("0.0.0.0", LOCAL_SERVER_PORT), OllamaProxyHandler)
    print(f"  Local Ollama proxy listening on port {LOCAL_SERVER_PORT}", flush=True)
    server.serve_forever()


# ---------------------------------------------------------------------------
# mDNS registration via zeroconf
# ---------------------------------------------------------------------------

def register_mdns() -> Zeroconf:
    """Advertise this node on the local network as _fleetmind._tcp."""
    hostname   = socket.gethostname()
    local_ip   = socket.gethostbyname(hostname)
    # zeroconf needs bytes for addresses
    try:
        import ipaddress
        addr_bytes = ipaddress.ip_address(local_ip).packed
    except Exception:
        addr_bytes = socket.inet_aton(local_ip)

    service_name = f"FleetMind-Mac-{hostname}._fleetmind._tcp.local."
    info = ServiceInfo(
        type_="_fleetmind._tcp.local.",
        name=service_name,
        addresses=[addr_bytes],
        port=LOCAL_SERVER_PORT,
        properties={
            "device_id":    state.device_id.encode(),
            "device_model": DEVICE_MODEL.encode(),
            "version":      b"1.0",
        },
        server=f"{hostname}.local.",
    )

    zc = Zeroconf()
    zc.register_service(info)
    print(f"  mDNS registered: {service_name}", flush=True)
    return zc


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="FleetMind Mac Node Agent — turns this Mac into a mesh node."
    )
    parser.add_argument(
        "--license",
        metavar="KEY",
        help="FleetMind license key (e.g. FM-XXXX-XXXX-XXXX)",
    )
    parser.add_argument(
        "--backend",
        metavar="URL",
        default="http://localhost:8000",
        help="FleetMind backend URL (default: http://localhost:8000)",
    )
    return parser.parse_args()


def prompt_if_missing(args: argparse.Namespace):
    """Interactively ask for any missing values."""
    if not args.license:
        args.license = input("Enter your FleetMind license key: ").strip()
    if not args.backend:
        args.backend = input("Enter backend URL [http://localhost:8000]: ").strip() or "http://localhost:8000"


def main():
    args = parse_args()
    prompt_if_missing(args)

    state.license_key = args.license
    state.backend_url = args.backend

    print()
    print("FleetMind Mac Node")
    print("==================")
    print(f"  Device ID   : {state.device_id}")
    print(f"  Backend     : {state.backend_url}")
    print(f"  License     : {state.license_key[:8]}{'*' * max(0, len(state.license_key) - 8)}")
    print(f"  Ollama proxy: http://0.0.0.0:{LOCAL_SERVER_PORT}/generate")
    print()

    # 1. Register on mDNS
    try:
        zc = register_mdns()
    except Exception as exc:  # noqa: BLE001
        print(f"  Warning: mDNS registration failed ({exc}). Continuing without mDNS.", flush=True)
        zc = None

    # 2. Start heartbeat thread (daemon so it exits when main thread exits)
    hb_thread = threading.Thread(target=heartbeat_loop, name="heartbeat", daemon=True)
    hb_thread.start()

    # 3. Run local proxy server (blocking — Ctrl-C to exit)
    try:
        start_local_server()
    except KeyboardInterrupt:
        print("\n  Shutting down Mac node...", flush=True)
    finally:
        if zc:
            zc.close()
        sys.exit(0)


if __name__ == "__main__":
    main()
