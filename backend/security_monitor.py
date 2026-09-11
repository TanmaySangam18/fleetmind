"""
Security layer — replaces Physical Security and Fire Suppression.

Physical Security: devices must be hardware-attested and recently seen.
Fire Suppression: anomaly detection → auto-quarantine rogue devices.

FM-200 fire suppression triggers instantly when fire is detected.
FleetMind quarantine triggers instantly when a device exceeds anomaly thresholds.
"""

import time
from collections import defaultdict
from datetime import datetime, timedelta

# Sliding window for anomaly detection (Fire Suppression equivalent)
_query_rate_window: dict = defaultdict(list)
ANOMALY_WINDOW_SECS = 300   # 5-minute sliding window
ANOMALY_MULTIPLIER = 10     # >10x fleet average triggers quarantine alert


def record_query(device_id: str) -> None:
    """Record a query event for rate monitoring."""
    now = time.time()
    _query_rate_window[device_id].append(now)
    # Trim events outside the sliding window
    _query_rate_window[device_id] = [
        t for t in _query_rate_window[device_id]
        if now - t < ANOMALY_WINDOW_SECS
    ]


def get_query_rate(device_id: str) -> float:
    """Queries per minute over the last 5 minutes."""
    now = time.time()
    recent = [t for t in _query_rate_window[device_id] if now - t < ANOMALY_WINDOW_SECS]
    return len(recent) / (ANOMALY_WINDOW_SECS / 60)


def check_anomaly(device_id: str, all_device_ids: list) -> dict | None:
    """
    Fire Suppression equivalent: detect and flag anomalous devices.
    Returns an alert dict if the device should be quarantined, else None.
    """
    if len(all_device_ids) < 2:
        return None

    my_rate = get_query_rate(device_id)
    other_rates = [get_query_rate(d) for d in all_device_ids if d != device_id]
    avg_rate = sum(other_rates) / len(other_rates) if other_rates else 0

    if avg_rate > 0 and my_rate > avg_rate * ANOMALY_MULTIPLIER:
        return {
            "severity": "critical",
            "alert_type": "security",
            "device_id": device_id,
            "message": (
                f"ANOMALY DETECTED: Device {device_id} processing {my_rate:.1f} q/min "
                f"vs fleet avg {avg_rate:.1f} q/min. "
                f"Auto-quarantine recommended (Fire Suppression triggered)."
            ),
        }
    return None


def check_attestation_alerts(device) -> list:
    """
    Physical Security equivalent: flag devices that lost attestation or were never attested.
    """
    alerts = []
    if not device.hardware_attested:
        alerts.append({
            "severity": "warning",
            "alert_type": "security",
            "device_id": device.device_id,
            "message": (
                f"Device {device.device_id} is NOT hardware-attested. "
                f"Treating as untrusted perimeter."
            ),
        })
    return alerts


def check_offline_alerts(device, cutoff: datetime) -> list:
    """
    Physical Security: a device that disappears without warning is a security event.
    """
    if device.last_seen and device.last_seen < cutoff:
        minutes_offline = int(
            (datetime.utcnow() - device.last_seen).total_seconds() / 60
        )
        return [{
            "severity": "warning",
            "alert_type": "security",
            "device_id": device.device_id,
            "message": (
                f"Device {device.device_id} offline for {minutes_offline} minutes. "
                f"Possible physical removal."
            ),
        }]
    return []
