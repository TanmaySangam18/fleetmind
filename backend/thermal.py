"""
Thermal layer — replaces Chillers, Cooling Towers, CRAC/CRAH Units, Underfloor cooling.

Phones generate heat during inference. The thermal layer:
- Monitors CPU temperature per device (Chiller sensors)
- Tracks Android thermal states (CRAC/CRAH: temperature + humidity control → here: temp + load)
- Routes away from hot devices (Cooling Tower: remove heat from the system)
- Triggers cooldown scheduling when fleet aggregate temp rises (Underfloor: system-wide cooling)
"""

THERMAL_STATE_RANK = {
    "NONE":     0,
    "LIGHT":    1,
    "MODERATE": 2,
    "SEVERE":   3,
    "CRITICAL": 4,
}

# Degrees Celsius thresholds for alert generation
TEMP_WARN_C = 42.0
TEMP_CRITICAL_C = 50.0


def thermal_score(device) -> float:
    """
    1.0 = cool, 0.0 = too hot to route.
    CRAC/CRAH equivalent: how well is this device being 'cooled'?
    """
    state = device.thermal_state or "NONE"
    weights = {"NONE": 1.0, "LIGHT": 0.75, "MODERATE": 0.4, "SEVERE": 0.1, "CRITICAL": 0.0}
    base = weights.get(state, 0.5)
    if device.cpu_temp_celsius:
        if device.cpu_temp_celsius >= TEMP_CRITICAL_C:
            base = 0.0
        elif device.cpu_temp_celsius >= TEMP_WARN_C:
            base = min(base, 0.3)
    return base


def is_thermally_eligible(device) -> bool:
    """
    Chiller equivalent: is there enough cooling capacity to route a query here?
    CRITICAL or SEVERE thermal → route elsewhere (equivalent to a chiller failing).
    """
    state = device.thermal_state or "NONE"
    if state in ("CRITICAL", "SEVERE"):
        return False
    if device.cpu_temp_celsius and device.cpu_temp_celsius >= TEMP_CRITICAL_C:
        return False
    return True


def fleet_thermal_health(devices: list) -> dict:
    """
    Cooling Tower equivalent: aggregate heat rejection status for the fleet.
    Returns fleet-wide thermal summary.
    """
    if not devices:
        return {"status": "no_devices", "avg_temp_celsius": None, "hot_devices": 0}

    temps = [d.cpu_temp_celsius for d in devices if d.cpu_temp_celsius is not None]
    avg_temp = sum(temps) / len(temps) if temps else None
    hot = [d for d in devices if (d.thermal_state or "NONE") in ("SEVERE", "CRITICAL")]
    scores = [thermal_score(d) for d in devices]
    fleet_score = sum(scores) / len(scores) if scores else 1.0

    if fleet_score >= 0.8:
        status = "optimal"
    elif fleet_score >= 0.5:
        status = "warm"
    elif fleet_score >= 0.2:
        status = "hot"
    else:
        status = "critical"

    return {
        "status": status,
        "fleet_thermal_score": round(fleet_score, 3),
        "avg_temp_celsius": round(avg_temp, 1) if avg_temp is not None else None,
        "hot_devices": len(hot),
        "total_devices": len(devices),
        "hot_device_ids": [d.device_id for d in hot],
    }


def check_thermal_alerts(device, company_id: int) -> list:
    """
    CRAC/CRAH equivalent: detect when device needs 'air conditioning' (throttling).
    """
    alerts = []
    state = device.thermal_state or "NONE"
    temp = device.cpu_temp_celsius

    if state == "CRITICAL" or (temp and temp >= TEMP_CRITICAL_C):
        alerts.append({
            "severity": "critical",
            "alert_type": "thermal",
            "device_id": device.device_id,
            "message": (
                f"CRITICAL OVERHEAT: Device {device.device_id} at {temp}°C / state={state}. "
                f"Excluded from routing."
            ),
        })
    elif state == "SEVERE" or (temp and temp >= TEMP_WARN_C):
        alerts.append({
            "severity": "warning",
            "alert_type": "thermal",
            "device_id": device.device_id,
            "message": (
                f"Thermal warning: Device {device.device_id} at {temp}°C / state={state}. "
                f"Routing reduced."
            ),
        })
    return alerts
