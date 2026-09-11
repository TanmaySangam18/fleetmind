"""
Power layer — replaces Utility Grid, Generators, UPS, and PDUs.

Phones are the power source. The power layer manages:
- Battery monitoring per device (Grid equivalent: how much power do we have?)
- Reserve device pool (Generator equivalent: keep charged devices idle for failover)
- Query retry on device failure (UPS equivalent: queries never drop during power-loss events)
- Load distribution weighted by battery level (PDU equivalent)
"""

BATTERY_EXCLUDE_THRESHOLD = 20    # below this: device excluded from routing
BATTERY_RESERVE_THRESHOLD = 80    # above this: eligible for reserve pool (Generator)
BATTERY_WARN_THRESHOLD = 30       # below this: emit low_battery alert
BATTERY_CRITICAL_THRESHOLD = 15   # below this: emit critical_battery alert, force charging_needed

THERMAL_WEIGHTS = {
    "NONE":     1.0,
    "LIGHT":    0.8,
    "MODERATE": 0.5,
    "SEVERE":   0.1,
    "CRITICAL": 0.0,
}


def power_score(device) -> float:
    """
    Returns 0.0–1.0. Used by PDU-equivalent routing to weight query distribution.
    Higher battery + charging = higher score = more queries routed here.
    """
    if device.battery_level is None:
        return 0.5
    base = device.battery_level / 100.0
    if device.is_charging:
        base = min(1.0, base + 0.1)  # bonus for charging devices
    thermal_penalty = THERMAL_WEIGHTS.get(device.thermal_state or "NONE", 1.0)
    return base * thermal_penalty


def is_power_eligible(device) -> bool:
    """Device must have enough battery to accept queries."""
    if device.is_quarantined:
        return False
    if device.battery_level is not None and device.battery_level < BATTERY_EXCLUDE_THRESHOLD:
        return False
    thermal = device.thermal_state or "NONE"
    if THERMAL_WEIGHTS.get(thermal, 1.0) == 0.0:
        return False
    return True


def get_reserve_pool(devices: list) -> list:
    """
    Generator equivalent: devices above threshold held in reserve for failover.
    These are the 'generators' — full charge, ready to take load instantly.
    """
    return [d for d in devices if
            (d.battery_level or 0) >= BATTERY_RESERVE_THRESHOLD and
            not d.is_quarantined and
            (d.thermal_state or "NONE") in ("NONE", "LIGHT")]


def sort_by_power_score(devices: list) -> list:
    """PDU equivalent: distribute load proportional to available power."""
    return sorted(devices, key=lambda d: power_score(d), reverse=True)


def check_power_alerts(device, company_id: int, db) -> list:
    """
    Returns list of alerts to emit for this device's current power state.
    UPS equivalent: detect when power is failing before the device goes offline.
    """
    from database import FleetAlert, PowerEvent
    alerts = []
    level = device.battery_level if device.battery_level is not None else 100

    if level <= BATTERY_CRITICAL_THRESHOLD and not device.is_charging:
        alerts.append({
            "severity": "critical",
            "alert_type": "power",
            "device_id": device.device_id,
            "message": (
                f"CRITICAL: Device {device.device_id} battery at {level}% and discharging. "
                f"Remove from rotation immediately."
            ),
        })
        db.add(PowerEvent(
            company_id=company_id,
            device_id=device.device_id,
            event_type="critical_battery",
            battery_level=level,
        ))
    elif level <= BATTERY_WARN_THRESHOLD and not device.is_charging:
        alerts.append({
            "severity": "warning",
            "alert_type": "power",
            "device_id": device.device_id,
            "message": (
                f"WARNING: Device {device.device_id} battery at {level}%. "
                f"Recommend charging."
            ),
        })
        db.add(PowerEvent(
            company_id=company_id,
            device_id=device.device_id,
            event_type="low_battery",
            battery_level=level,
        ))

    return alerts
