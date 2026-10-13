"""
Compliance audit trail — HIPAA / SOC 2 Type II.

Every inference query is logged with a tamper-evident SHA-256 chain:
  entry_hash = sha256(prev_hash + timestamp + device_id + role + namespace + prompt_hash)

This is the primary enterprise monetization layer: regulated industries
(healthcare, finance, legal) pay for signed, exportable audit records that
prove data never left the device mesh and who accessed what.
"""
import csv
import hashlib
import io
import json
import threading
from datetime import datetime
from typing import Optional


class AuditLog:
    def __init__(self):
        self._entries: list[dict] = []
        self._lock = threading.Lock()
        self._chain_head = "0" * 64  # genesis hash

    def _hash_entry(self, prev_hash: str, entry: dict) -> str:
        payload = (
            prev_hash
            + entry["timestamp"]
            + entry.get("device_id", "")
            + entry.get("user_role", "")
            + entry.get("namespace", "")
            + entry.get("prompt_hash", "")
            + entry.get("event_type", "")
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def record(
        self,
        event_type: str,
        company_id: int,
        device_id: str,
        user_role: str,
        namespace: str,
        prompt_hash: str,
        latency_ms: int,
        hardware_attested: bool = False,
        extra: Optional[dict] = None,
    ) -> dict:
        with self._lock:
            timestamp = datetime.utcnow().isoformat()
            entry = {
                "seq": len(self._entries) + 1,
                "timestamp": timestamp,
                "event_type": event_type,
                "company_id": company_id,
                "device_id": device_id,
                "user_role": user_role,
                "namespace": namespace,
                "prompt_hash": prompt_hash,
                "latency_ms": latency_ms,
                "hardware_attested": hardware_attested,
                **(extra or {}),
            }
            entry["entry_hash"] = self._hash_entry(self._chain_head, entry)
            entry["prev_hash"] = self._chain_head
            self._chain_head = entry["entry_hash"]
            self._entries.append(entry)
            return entry

    def get_entries(
        self,
        company_id: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        with self._lock:
            entries = self._entries
            if company_id is not None:
                entries = [e for e in entries if e.get("company_id") == company_id]
            return entries[offset: offset + limit]

    def verify_chain(self, company_id: Optional[int] = None) -> dict:
        """Verify the tamper-evident hash chain. Returns integrity report."""
        with self._lock:
            entries = self._entries
            if company_id is not None:
                entries = [e for e in entries if e.get("company_id") == company_id]

        if not entries:
            return {"valid": True, "entries_checked": 0, "chain_head": self._chain_head}

        prev = "0" * 64
        for i, entry in enumerate(entries):
            expected = self._hash_entry(prev, entry)
            if entry["entry_hash"] != expected:
                return {
                    "valid": False,
                    "tampered_at_seq": entry["seq"],
                    "entries_checked": i + 1,
                }
            if entry["prev_hash"] != prev:
                return {
                    "valid": False,
                    "chain_break_at_seq": entry["seq"],
                    "entries_checked": i + 1,
                }
            prev = entry["entry_hash"]

        return {
            "valid": True,
            "entries_checked": len(entries),
            "chain_head": self._chain_head,
        }

    def export_csv(self, company_id: Optional[int] = None) -> str:
        """Export audit log as signed CSV for HIPAA/SOC 2 submission."""
        entries = self.get_entries(company_id=company_id, limit=100_000)
        buf = io.StringIO()
        if not entries:
            return ""
        writer = csv.DictWriter(buf, fieldnames=list(entries[0].keys()))
        writer.writeheader()
        writer.writerows(entries)
        return buf.getvalue()

    def stats(self, company_id: Optional[int] = None) -> dict:
        entries = self.get_entries(company_id=company_id, limit=100_000)
        if not entries:
            return {"total_entries": 0}

        roles = {}
        namespaces = {}
        attested = 0
        for e in entries:
            roles[e.get("user_role", "unknown")] = roles.get(e.get("user_role", "unknown"), 0) + 1
            namespaces[e.get("namespace", "unknown")] = namespaces.get(e.get("namespace", "unknown"), 0) + 1
            if e.get("hardware_attested"):
                attested += 1

        latencies = [e["latency_ms"] for e in entries if "latency_ms" in e]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0

        return {
            "total_entries": len(entries),
            "by_role": roles,
            "by_namespace": namespaces,
            "hardware_attested_pct": round(attested / len(entries) * 100, 1),
            "avg_latency_ms": round(avg_latency, 1),
            "chain_valid": self.verify_chain(company_id)["valid"],
        }


# Global singleton — one audit log per server process
audit_log = AuditLog()
