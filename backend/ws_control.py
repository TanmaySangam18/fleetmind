"""
WebSocket server-mediated control plane.

Replaces NSD/mDNS peer discovery, which silently fails on enterprise WiFi
due to VLAN segmentation, AP client isolation, and multicast filtering.

Devices register here over HTTPS WebSocket on startup. The coordinator
maintains the live registry, pushes routing commands, and detects failures
via missed pings — no multicast, no VLAN dependency.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: Dict[str, object] = {}
        self._metadata: Dict[str, dict] = {}
        self._last_ping: Dict[str, datetime] = {}

    async def connect(self, device_id: str, websocket, metadata: dict):
        await websocket.accept()
        self._connections[device_id] = websocket
        self._metadata[device_id] = {
            **metadata,
            "connected_at": datetime.utcnow().isoformat(),
        }
        self._last_ping[device_id] = datetime.utcnow()
        logger.info("Device %s joined control plane (total: %d)", device_id, len(self._connections))
        await websocket.send_json({
            "type": "welcome",
            "device_id": device_id,
            "server_time": datetime.utcnow().isoformat(),
            "ping_interval_s": 30,
        })

    def disconnect(self, device_id: str):
        self._connections.pop(device_id, None)
        self._metadata.pop(device_id, None)
        self._last_ping.pop(device_id, None)
        logger.info("Device %s left control plane (remaining: %d)", device_id, len(self._connections))

    def record_ping(self, device_id: str):
        self._last_ping[device_id] = datetime.utcnow()

    async def send_command(self, device_id: str, command: dict) -> bool:
        ws = self._connections.get(device_id)
        if not ws:
            return False
        try:
            await ws.send_json(command)
            return True
        except Exception:
            self.disconnect(device_id)
            return False

    async def broadcast(self, command: dict, exclude: Optional[str] = None):
        dead = []
        for device_id, ws in list(self._connections.items()):
            if device_id == exclude:
                continue
            try:
                await ws.send_json(command)
            except Exception:
                dead.append(device_id)
        for d in dead:
            self.disconnect(d)

    async def push_model_downscale(self, device_id: str, from_model: str, to_model: str, reason: str):
        """Push adaptive thermal throttle — device should swap to smaller model."""
        await self.send_command(device_id, {
            "type": "model_downscale",
            "from_model": from_model,
            "to_model": to_model,
            "reason": reason,
            "server_time": datetime.utcnow().isoformat(),
        })

    async def push_pause(self, device_id: str, duration_s: int, reason: str):
        """Tell a device to pause accepting inference for thermal cooldown."""
        await self.send_command(device_id, {
            "type": "pause_inference",
            "duration_s": duration_s,
            "reason": reason,
            "server_time": datetime.utcnow().isoformat(),
        })

    def active_count(self) -> int:
        return len(self._connections)

    def get_connected_ids(self) -> list[str]:
        return list(self._connections.keys())

    def get_metadata(self, device_id: str) -> dict:
        return self._metadata.get(device_id, {})

    def fleet_summary(self) -> dict:
        return {
            "connected_devices": len(self._connections),
            "device_ids": self.get_connected_ids()[:20],  # cap for payload size
            "total_device_count": len(self._connections),
        }


manager = ConnectionManager()
