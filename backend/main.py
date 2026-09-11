import base64
import logging
import os
import hashlib
import hmac
import random
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

import stripe
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db, init_db, Company, Device, Query, Employee, StoredFile, StorageChunk, FleetAlert, PowerEvent
from license import generate_license_key
from rbac import (
    ROLES, NAMESPACES, can_access, get_accessible_namespaces,
    get_eligible_nodes, generate_user_key, encrypt_query, decrypt_query,
)
from attestation import verify_android_attestation
from power import power_score, is_power_eligible, get_reserve_pool, sort_by_power_score, check_power_alerts
from thermal import thermal_score, is_thermally_eligible, fleet_thermal_health, check_thermal_alerts
from storage import store_file, retrieve_file, delete_file, fleet_storage_stats
from security_monitor import record_query, check_anomaly, check_attestation_alerts, check_offline_alerts

logger = logging.getLogger(__name__)

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
RBAC_SECRET = os.getenv("RBAC_SECRET", "fleetmind-rbac-secret")
COST_PER_QUERY_USD = 0.004


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="FleetMind API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Pricing ----------

PRICE_TIERS = [
    (200,    4_000_00),
    (1000,  15_000_00),
    (5000,  50_000_00),
    (20000, 150_000_00),
    (None,  400_000_00),
]


def calculate_price_cents(employee_count: int) -> int:
    for ceiling, cents in PRICE_TIERS:
        if ceiling is None or employee_count <= ceiling:
            return cents
    return PRICE_TIERS[-1][1]


# ---------- Schemas ----------

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    employee_count: int
    company_reg_number: str


class ActivateTrialRequest(BaseModel):
    trial_token: str


class PurchaseRequest(BaseModel):
    company_token: str
    employee_count: int


class HeartbeatRequest(BaseModel):
    license_key: str
    device_id: str
    device_model: str
    queries_processed: int
    uptime_seconds: int
    operator_email: Optional[str] = None
    # Direct chunk-push address (LAN IP of the Android device)
    device_ip: Optional[str] = None
    # Power layer
    battery_level: Optional[int] = None
    is_charging: Optional[bool] = None
    estimated_runtime_mins: Optional[int] = None
    # Thermal layer
    cpu_temp_celsius: Optional[float] = None
    thermal_state: Optional[str] = None  # NONE/LIGHT/MODERATE/SEVERE/CRITICAL
    # Network layer
    wifi_rssi_dbm: Optional[int] = None
    network_bandwidth_mbps: Optional[float] = None
    # Compute
    cpu_usage_percent: Optional[float] = None
    ram_available_mb: Optional[int] = None
    # Storage
    available_storage_mb: Optional[int] = None


class MeshQueryRequest(BaseModel):
    license_key: str
    prompt: str


class EncryptedQueryRequest(BaseModel):
    license_key: str
    encrypted_query: str
    user_role: str
    namespace: str


class EmployeeRegisterRequest(BaseModel):
    license_key: str
    email: str
    role: str
    requester_email: Optional[str] = None


class EmployeeKeyRequest(BaseModel):
    license_key: str
    email: str


class DevicePubkeyRequest(BaseModel):
    license_key: str
    device_id: str
    public_key_base64: str
    attestation_cert_chain: list[str] = []


class SecureQueryRequest(BaseModel):
    license_key: str
    user_role: str
    namespace: str
    encrypted_query_base64: str
    requester_public_key_base64: Optional[str] = None


# ---------- Helpers ----------

def _generate_trial_token() -> str:
    return uuid.uuid4().hex


def _resolve_company_by_license(db: Session, license_key: str) -> Company:
    company = db.query(Company).filter(
        (Company.license_key == license_key) | (Company.trial_token == license_key)
    ).first()
    if not company:
        raise HTTPException(status_code=404, detail="License key not found")
    return company


def _resolve_company_by_token(db: Session, token: str) -> Company:
    company = db.query(Company).filter(Company.trial_token == token).first()
    if not company:
        raise HTTPException(status_code=404, detail="Token not found")
    return company


def _license_status(company: Company):
    now = datetime.utcnow()
    if company.plan == "paid":
        return "active", None
    if company.trial_expiry and now < company.trial_expiry:
        delta = company.trial_expiry - now
        days = int(delta.total_seconds() // 86400) + (1 if delta.seconds % 86400 else 0)
        return "trial", days
    return "expired", 0


# ---------- Routes ----------

@app.post("/api/register", status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(Company).filter(
        (Company.email == body.email) | (Company.reg_number == body.company_reg_number)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Company already registered")

    token = _generate_trial_token()
    company = Company(
        name=body.name,
        email=body.email,
        employee_count=body.employee_count,
        reg_number=body.company_reg_number,
        trial_token=token,
        plan="trial",
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return {"trial_token": token, "company_id": company.id}


@app.post("/api/activate-trial")
def activate_trial(body: ActivateTrialRequest, db: Session = Depends(get_db)):
    company = _resolve_company_by_token(db, body.trial_token)
    if company.trial_expiry:
        raise HTTPException(status_code=400, detail="Trial already activated")

    company.trial_expiry = datetime.utcnow() + timedelta(days=7)
    db.commit()
    db.refresh(company)

    # mock email: just return the license key material
    return {
        "message": f"Trial activated. License details sent to {company.email}",
        "trial_token": company.trial_token,
        "trial_expiry": company.trial_expiry.isoformat(),
        "days_remaining": 7,
    }


@app.get("/api/license/{token}")
def get_license(token: str, db: Session = Depends(get_db)):
    company = db.query(Company).filter(
        (Company.trial_token == token) | (Company.license_key == token)
    ).first()
    if not company:
        raise HTTPException(status_code=404, detail="Token not found")

    status, days = _license_status(company)
    return {
        "status": status,
        "days_remaining": days,
        "employee_count": company.employee_count,
        "company_name": company.name,
        "plan": company.plan,
    }


@app.post("/api/purchase")
def purchase(body: PurchaseRequest, db: Session = Depends(get_db)):
    company = _resolve_company_by_token(db, body.company_token)
    if company.plan == "paid":
        raise HTTPException(status_code=400, detail="Company already has paid license")

    price_cents = calculate_price_cents(body.employee_count)

    if not stripe.api_key or stripe.api_key == "":
        # dev/test mode: skip real Stripe call
        return {
            "client_secret": "mock_client_secret_no_stripe_key_set",
            "amount_usd": price_cents / 100,
            "employee_count": body.employee_count,
        }

    intent = stripe.PaymentIntent.create(
        amount=price_cents,
        currency="usd",
        metadata={
            "company_id": str(company.id),
            "company_token": body.company_token,
            "employee_count": str(body.employee_count),
        },
    )
    return {
        "client_secret": intent.client_secret,
        "amount_usd": price_cents / 100,
        "employee_count": body.employee_count,
    }


@app.post("/api/stripe-webhook")
async def stripe_webhook(request: Request, stripe_signature: Optional[str] = Header(None), db: Session = Depends(get_db)):
    payload = await request.body()

    if STRIPE_WEBHOOK_SECRET:
        try:
            event = stripe.Webhook.construct_event(payload, stripe_signature, STRIPE_WEBHOOK_SECRET)
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        import json
        event = json.loads(payload)

    if event["type"] == "payment_intent.succeeded":
        intent = event["data"]["object"]
        meta = intent.get("metadata", {})
        company_id = int(meta.get("company_id", 0))
        employee_count = int(meta.get("employee_count", 0))

        company = db.query(Company).filter(Company.id == company_id).first()
        if company and company.plan != "paid":
            company.license_key = generate_license_key(company.id)
            company.plan = "paid"
            if employee_count:
                company.employee_count = employee_count
            db.commit()

    return {"received": True}


@app.post("/api/device/heartbeat")
def device_heartbeat(body: HeartbeatRequest, db: Session = Depends(get_db)):
    company = _resolve_company_by_license(db, body.license_key)
    status, _ = _license_status(company)
    if status == "expired":
        raise HTTPException(status_code=403, detail="License expired")

    device = db.query(Device).filter(
        Device.company_id == company.id,
        Device.device_id == body.device_id,
    ).first()

    operator_role = "engineer"
    if body.operator_email:
        emp = db.query(Employee).filter(
            Employee.company_id == company.id,
            Employee.email == body.operator_email,
        ).first()
        if emp:
            operator_role = emp.role
            emp.device_id = body.device_id

    if device:
        device.last_seen = datetime.utcnow()
        device.queries_processed = body.queries_processed
        device.device_model = body.device_model
        device.is_active = True
        if body.operator_email:
            device.operator_role = operator_role
        if body.device_ip is not None:
            device.device_ip = body.device_ip
    else:
        device = Device(
            company_id=company.id,
            device_id=body.device_id,
            device_model=body.device_model,
            queries_processed=body.queries_processed,
            is_active=True,
            operator_role=operator_role,
            device_ip=body.device_ip,
        )
        db.add(device)
        db.flush()  # assign device.id so alert FK is valid

    # Power layer update
    if body.battery_level is not None:
        device.battery_level = body.battery_level
    if body.is_charging is not None:
        device.is_charging = body.is_charging
    if body.estimated_runtime_mins is not None:
        device.estimated_runtime_mins = body.estimated_runtime_mins
    # Thermal layer update
    if body.cpu_temp_celsius is not None:
        device.cpu_temp_celsius = body.cpu_temp_celsius
    if body.thermal_state is not None:
        device.thermal_state = body.thermal_state
    # Network layer update
    if body.wifi_rssi_dbm is not None:
        device.wifi_rssi_dbm = body.wifi_rssi_dbm
    if body.network_bandwidth_mbps is not None:
        device.network_bandwidth_mbps = body.network_bandwidth_mbps
    # Compute layer update
    if body.cpu_usage_percent is not None:
        device.cpu_usage_percent = body.cpu_usage_percent
    if body.ram_available_mb is not None:
        device.ram_available_mb = body.ram_available_mb
    # Storage layer update
    if body.available_storage_mb is not None:
        device.available_storage_mb = body.available_storage_mb

    # Emit alerts for power and thermal state
    all_alerts = []
    all_alerts.extend(check_power_alerts(device, company.id, db))
    all_alerts.extend(check_thermal_alerts(device, company.id))
    for alert in all_alerts:
        db.add(FleetAlert(
            company_id=company.id,
            severity=alert["severity"],
            alert_type=alert["alert_type"],
            device_id=alert.get("device_id"),
            message=alert["message"],
        ))

    db.commit()
    return {
        "acknowledged": True,
        "server_time": datetime.utcnow().isoformat(),
        "power_eligible": is_power_eligible(device),
        "thermal_eligible": is_thermally_eligible(device),
    }


@app.get("/api/dashboard/{license_key}")
def dashboard(license_key: str, db: Session = Depends(get_db)):
    company = _resolve_company_by_license(db, license_key)

    cutoff = datetime.utcnow() - timedelta(seconds=90)
    all_devices = db.query(Device).filter(Device.company_id == company.id).all()
    active_devices = [d for d in all_devices if d.last_seen and d.last_seen >= cutoff]

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    queries_today = db.query(Query).filter(
        Query.company_id == company.id,
        Query.created_at >= today_start,
    ).count()
    queries_alltime = db.query(Query).filter(Query.company_id == company.id).count()

    money_saved = round(queries_alltime * COST_PER_QUERY_USD, 2)

    devices_payload = [
        {
            "id": d.device_id,
            "model": d.device_model,
            "status": "active" if d.last_seen and d.last_seen >= cutoff else "offline",
            "queries": d.queries_processed,
            "operator_role": d.operator_role,
        }
        for d in all_devices
    ]

    all_employees = db.query(Employee).filter(Employee.company_id == company.id).all()
    role_dist: dict[str, int] = {}
    for emp in all_employees:
        role_dist[emp.role] = role_dist.get(emp.role, 0) + 1

    device_lookup = {d.device_id: d for d in all_devices}
    employees_payload = []
    for emp in all_employees:
        dev = device_lookup.get(emp.device_id or "")
        emp_status = "offline"
        if dev and dev.last_seen and dev.last_seen >= cutoff:
            emp_status = "active"
        employees_payload.append({
            "email": emp.email,
            "role": emp.role,
            "device_id": emp.device_id,
            "status": emp_status,
        })

    return {
        "active_devices": len(active_devices),
        "total_queries_today": queries_today,
        "total_queries_alltime": queries_alltime,
        "money_saved_usd": money_saved,
        "devices": devices_payload,
        "employees": employees_payload,
        "role_distribution": role_dist,
    }


_round_robin_index: dict[int, int] = {}

MOCK_RESPONSES = [
    "Based on the available data, here is my analysis of your query.",
    "I have processed your request across the fleet mesh network.",
    "Query completed. Results synthesized from distributed device inference.",
    "FleetMind mesh responded. Local inference preserved your data privacy.",
]


@app.post("/api/query")
def mesh_query(body: MeshQueryRequest, db: Session = Depends(get_db)):
    company = _resolve_company_by_license(db, body.license_key)
    status, _ = _license_status(company)
    if status == "expired":
        raise HTTPException(status_code=403, detail="License expired")

    cutoff = datetime.utcnow() - timedelta(seconds=90)
    active_devices = db.query(Device).filter(
        Device.company_id == company.id,
        Device.last_seen >= cutoff,
        Device.is_active == True,
    ).all()

    if not active_devices:
        raise HTTPException(status_code=503, detail="No active devices in fleet")

    # Power + thermal aware routing (replaces: PDU + CRAC/CRAH routing)
    eligible = [d for d in active_devices if is_power_eligible(d) and is_thermally_eligible(d)]
    if not eligible:
        # Fall back to reserve pool (Generator equivalent)
        reserve = get_reserve_pool(active_devices)
        eligible = reserve if reserve else active_devices

    # Sort by combined power+thermal score (PDU load balancing)
    eligible = sort_by_power_score(eligible)

    idx = _round_robin_index.get(company.id, 0)
    target_device = eligible[idx % len(eligible)]
    _round_robin_index[company.id] = (idx + 1) % len(eligible)

    t_start = time.time()
    mock_response = random.choice(MOCK_RESPONSES)
    latency_ms = int((time.time() - t_start) * 1000) + random.randint(40, 200)

    prompt_hash = hashlib.sha256(body.prompt.encode()).hexdigest()
    q = Query(
        company_id=company.id,
        device_id=target_device.id,
        prompt_hash=prompt_hash,
        latency_ms=latency_ms,
    )
    db.add(q)
    db.commit()

    # Record query for anomaly detection (Fire Suppression)
    record_query(target_device.device_id)

    return {
        "response": mock_response,
        "device_id": target_device.device_id,
        "latency_ms": latency_ms,
    }


@app.post("/api/query/encrypted")
def mesh_query_encrypted(body: EncryptedQueryRequest, db: Session = Depends(get_db)):
    company = _resolve_company_by_license(db, body.license_key)
    status, _ = _license_status(company)
    if status == "expired":
        raise HTTPException(status_code=403, detail="License expired")

    if body.user_role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Unknown role: {body.user_role}")

    if not can_access(body.user_role, body.namespace):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "access_denied",
                "reason": f"{body.user_role} role cannot access {body.namespace} namespace",
            },
        )

    cutoff = datetime.utcnow() - timedelta(seconds=90)
    raw_devices = db.query(Device).filter(
        Device.company_id == company.id,
        Device.last_seen >= cutoff,
        Device.is_active == True,
    ).all()

    node_dicts = [
        {"id": d.id, "device_id": d.device_id, "operator_role": d.operator_role}
        for d in raw_devices
    ]
    eligible = get_eligible_nodes(body.user_role, node_dicts)

    if not eligible:
        raise HTTPException(status_code=503, detail="No eligible nodes for this role level")

    idx = _round_robin_index.get(company.id, 0)
    target_node = eligible[idx % len(eligible)]
    _round_robin_index[company.id] = (idx + 1) % len(eligible)

    t_start = time.time()
    mock_response = random.choice(MOCK_RESPONSES)
    latency_ms = int((time.time() - t_start) * 1000) + random.randint(40, 200)

    query_hash = hashlib.sha256(body.encrypted_query.encode()).hexdigest()
    user_key = generate_user_key(company.id, body.user_role, RBAC_SECRET)
    encrypted_response = encrypt_query(mock_response, user_key)

    q = Query(
        company_id=company.id,
        device_id=target_node["id"],
        prompt_hash=query_hash,
        latency_ms=latency_ms,
        user_role=body.user_role,
        namespace=body.namespace,
    )
    db.add(q)
    db.commit()

    return {
        "encrypted_response": encrypted_response,
        "device_id": target_node["device_id"],
        "latency_ms": latency_ms,
    }


_key_request_log: dict[str, list[float]] = {}


@app.post("/api/employee/register", status_code=201)
def register_employee(body: EmployeeRegisterRequest, db: Session = Depends(get_db)):
    company = _resolve_company_by_license(db, body.license_key)

    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Unknown role: {body.role}")

    existing = db.query(Employee).filter(
        Employee.company_id == company.id,
        Employee.email == body.email,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Employee already registered")

    emp = Employee(company_id=company.id, email=body.email, role=body.role)
    db.add(emp)
    db.commit()

    user_key = generate_user_key(company.id, body.email, RBAC_SECRET)
    return {"user_key": user_key, "email": body.email, "role": body.role}


@app.post("/api/employee/key")
def get_employee_key(body: EmployeeKeyRequest, db: Session = Depends(get_db)):
    company = _resolve_company_by_license(db, body.license_key)

    now = time.time()
    bucket = body.email
    requests = _key_request_log.get(bucket, [])
    requests = [t for t in requests if now - t < 3600]
    if len(requests) >= 5:
        raise HTTPException(status_code=429, detail="Rate limit: max 5 key requests per hour")
    requests.append(now)
    _key_request_log[bucket] = requests

    emp = db.query(Employee).filter(
        Employee.company_id == company.id,
        Employee.email == body.email,
    ).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    user_key = generate_user_key(company.id, body.email, RBAC_SECRET)
    return {"user_key": user_key}


@app.post("/api/device/pubkey", status_code=200)
def register_device_pubkey(body: DevicePubkeyRequest, db: Session = Depends(get_db)):
    company = _resolve_company_by_license(db, body.license_key)

    device = db.query(Device).filter(
        Device.company_id == company.id,
        Device.device_id == body.device_id,
    ).first()

    attestation_result = {"hardware_backed": False, "strongbox": False, "security_level": "Software", "verified": False}
    if body.attestation_cert_chain:
        try:
            attestation_result = verify_android_attestation(body.attestation_cert_chain)
        except Exception as e:
            logger.warning("Attestation verification error for device %s: %s", body.device_id, e)

    hardware_attested = attestation_result.get("hardware_backed", False)
    now = datetime.utcnow()

    if device:
        device.public_key = body.public_key_base64
        device.hardware_attested = hardware_attested
        device.attestation_verified_at = now if hardware_attested else device.attestation_verified_at
    else:
        device = Device(
            company_id=company.id,
            device_id=body.device_id,
            device_model="unknown",
            public_key=body.public_key_base64,
            hardware_attested=hardware_attested,
            attestation_verified_at=now if hardware_attested else None,
        )
        db.add(device)

    db.commit()

    return {
        "registered": True,
        "device_id": body.device_id,
        "hardware_attested": hardware_attested,
        "security_level": attestation_result.get("security_level", "Software"),
        "strongbox": attestation_result.get("strongbox", False),
    }


@app.get("/api/device/pubkey/{device_id}")
def get_device_pubkey(device_id: str, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if not device.public_key:
        raise HTTPException(status_code=404, detail="No public key registered for this device")
    return {
        "device_id": device_id,
        "public_key_base64": device.public_key,
        "hardware_attested": device.hardware_attested,
        "attestation_verified_at": device.attestation_verified_at.isoformat() if device.attestation_verified_at else None,
    }


@app.post("/api/query/secure")
def secure_mesh_query(body: SecureQueryRequest, db: Session = Depends(get_db)):
    company = _resolve_company_by_license(db, body.license_key)
    status, _ = _license_status(company)
    if status == "expired":
        raise HTTPException(status_code=403, detail="License expired")

    if body.user_role not in ROLES:
        raise HTTPException(status_code=400, detail=f"Unknown role: {body.user_role}")

    if not can_access(body.user_role, body.namespace):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "access_denied",
                "reason": f"{body.user_role} role cannot access {body.namespace} namespace",
            },
        )

    cutoff = datetime.utcnow() - timedelta(seconds=90)
    raw_devices = db.query(Device).filter(
        Device.company_id == company.id,
        Device.last_seen >= cutoff,
        Device.is_active == True,
        Device.public_key != None,
    ).all()

    node_dicts = [
        {
            "id": d.id,
            "device_id": d.device_id,
            "operator_role": d.operator_role,
            "public_key": d.public_key,
            "hardware_attested": d.hardware_attested,
        }
        for d in raw_devices
    ]
    eligible = get_eligible_nodes(body.user_role, node_dicts)

    # For sensitive namespaces, prefer hardware-attested nodes
    attested_eligible = [n for n in eligible if n.get("hardware_attested")]
    routing_pool = attested_eligible if attested_eligible else eligible

    if not routing_pool:
        raise HTTPException(status_code=503, detail="No eligible nodes with registered public keys for this role")

    idx = _round_robin_index.get(company.id, 0)
    target_node = routing_pool[idx % len(routing_pool)]
    _round_robin_index[company.id] = (idx + 1) % len(routing_pool)

    node_public_key_b64 = target_node["public_key"]

    # Re-encrypt the query blob for the target node's TrustZone key.
    # The backend never sees plaintext — it receives an encrypted blob
    # and re-wraps it using the target device's public key.
    # The actual re-encryption here wraps the incoming encrypted blob
    # (treated as opaque bytes) in a new AES-GCM envelope addressed to the node.
    try:
        from cryptography.hazmat.primitives.asymmetric.ec import (
            EllipticCurvePublicKey, ECDH,
        )
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.backends import default_backend

        node_pub_der = base64.b64decode(node_public_key_b64)
        node_pub_key = serialization.load_der_public_key(node_pub_der, backend=default_backend())

        ephemeral_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        shared_key = ephemeral_key.exchange(ECDH(), node_pub_key)

        digest = hashlib.sha256(shared_key).digest()
        aes_key = AESGCM(digest)

        nonce = os.urandom(12)
        payload_bytes = body.encrypted_query_base64.encode()
        ciphertext = aes_key.encrypt(nonce, payload_bytes, None)

        ephemeral_pub_der = ephemeral_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        ephemeral_pub_len = len(ephemeral_pub_der)
        envelope = (
            bytes([ephemeral_pub_len >> 8, ephemeral_pub_len & 0xFF])
            + ephemeral_pub_der
            + nonce
            + ciphertext
        )
        routed_payload = base64.b64encode(envelope).decode()

    except Exception as e:
        logger.error("Re-encryption for node %s failed: %s", target_node["device_id"], e)
        raise HTTPException(status_code=500, detail="Re-encryption failed")

    t_start = time.time()
    mock_encrypted_response = encrypt_query(
        random.choice(MOCK_RESPONSES),
        generate_user_key(company.id, body.user_role, RBAC_SECRET),
    )
    latency_ms = int((time.time() - t_start) * 1000) + random.randint(40, 200)

    query_hash = hashlib.sha256(body.encrypted_query_base64.encode()).hexdigest()
    q = Query(
        company_id=company.id,
        device_id=target_node["id"],
        prompt_hash=query_hash,
        latency_ms=latency_ms,
        user_role=body.user_role,
        namespace=body.namespace,
    )
    db.add(q)
    db.commit()

    return {
        "encrypted_response_base64": mock_encrypted_response,
        "routed_payload_base64": routed_payload,
        "device_id": target_node["device_id"],
        "attested": target_node.get("hardware_attested", False),
        "latency_ms": latency_ms,
    }


class OAIMessage(BaseModel):
    role: str
    content: str

class OAIRequest(BaseModel):
    model: str = "llama3.2:1b"
    messages: list[OAIMessage]
    stream: bool = False

@app.post("/v1/chat/completions")
def openai_chat(
    body: OAIRequest,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    license_key = ""
    if authorization and authorization.lower().startswith("bearer "):
        license_key = authorization[7:].strip()
    if not license_key:
        raise HTTPException(status_code=401, detail="Authorization: Bearer <license_key> required")

    company = _resolve_company_by_license(db, license_key)
    status, _ = _license_status(company)
    if status == "expired":
        raise HTTPException(status_code=403, detail="License expired")

    cutoff = datetime.utcnow() - timedelta(seconds=90)
    active_devices = db.query(Device).filter(
        Device.company_id == company.id,
        Device.last_seen >= cutoff,
        Device.is_active == True,
    ).all()

    if not active_devices:
        raise HTTPException(status_code=503, detail="No active devices in fleet")

    # Power + thermal aware routing (replaces: PDU + CRAC/CRAH routing)
    eligible = [d for d in active_devices if is_power_eligible(d) and is_thermally_eligible(d)]
    if not eligible:
        # Fall back to reserve pool (Generator equivalent)
        reserve = get_reserve_pool(active_devices)
        eligible = reserve if reserve else active_devices

    # Sort by combined power+thermal score (PDU load balancing)
    eligible = sort_by_power_score(eligible)

    idx = _round_robin_index.get(company.id, 0)
    target_device = eligible[idx % len(eligible)]
    _round_robin_index[company.id] = (idx + 1) % len(eligible)

    user_content = " ".join(m.content for m in body.messages if m.role == "user")
    mock_response = random.choice(MOCK_RESPONSES)
    latency_ms = random.randint(40, 200)

    prompt_hash = hashlib.sha256(user_content.encode()).hexdigest()
    q = Query(
        company_id=company.id,
        device_id=target_device.id,
        prompt_hash=prompt_hash,
        latency_ms=latency_ms,
    )
    db.add(q)
    db.commit()

    # Record query for anomaly detection (Fire Suppression)
    record_query(target_device.device_id)

    return {
        "id": f"fleetmind-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "model": body.model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": mock_response},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": len(user_content.split()), "completion_tokens": len(mock_response.split()), "total_tokens": 0},
        "x_fleetmind": {
            "device_id": target_device.device_id,
            "device_model": target_device.device_model,
            "latency_ms": latency_ms,
            "cost_usd": 0.0,
            "egress_bytes": 0,
        },
    }


# ===== POWER LAYER (Utility Grid + Generators + UPS + PDUs) =====

@app.get("/api/fleet/power")
def fleet_power(license_key: str, db: Session = Depends(get_db)):
    """PDU dashboard: fleet-wide power status."""
    company = _resolve_company_by_license(db, license_key)
    cutoff = datetime.utcnow() - timedelta(seconds=90)
    devices = db.query(Device).filter(Device.company_id == company.id).all()
    active = [d for d in devices if d.last_seen and d.last_seen >= cutoff]

    reserve = get_reserve_pool(active)
    eligible = [d for d in active if is_power_eligible(d)]

    return {
        "total_devices": len(devices),
        "active_devices": len(active),
        "power_eligible_devices": len(eligible),
        "reserve_pool_size": len(reserve),  # Generator equivalent
        "reserve_devices": [d.device_id for d in reserve],
        "fleet_battery_avg": round(sum(d.battery_level or 100 for d in active) / len(active), 1) if active else None,
        "charging_devices": sum(1 for d in active if d.is_charging),
        "low_battery_devices": [
            {"device_id": d.device_id, "battery_level": d.battery_level, "is_charging": d.is_charging}
            for d in active if (d.battery_level or 100) < 30
        ],
        "power_scores": {d.device_id: round(power_score(d), 3) for d in active},
    }


@app.post("/api/device/power-event")
def report_power_event(
    license_key: str,
    device_id: str,
    event_type: str,
    battery_level: int,
    db: Session = Depends(get_db),
):
    """UPS equivalent: devices report power state transitions."""
    company = _resolve_company_by_license(db, license_key)
    db.add(PowerEvent(
        company_id=company.id,
        device_id=device_id,
        event_type=event_type,
        battery_level=battery_level,
    ))
    db.commit()
    return {"recorded": True}


# ===== THERMAL LAYER (Chillers + Cooling Towers + CRAC/CRAH + Underfloor) =====

@app.get("/api/fleet/thermal")
def fleet_thermal(license_key: str, db: Session = Depends(get_db)):
    """CRAC/CRAH dashboard: fleet-wide thermal status."""
    company = _resolve_company_by_license(db, license_key)
    cutoff = datetime.utcnow() - timedelta(seconds=90)
    active = db.query(Device).filter(
        Device.company_id == company.id,
        Device.last_seen >= cutoff,
    ).all()

    health = fleet_thermal_health(active)
    return {
        **health,
        "thermal_eligible_devices": sum(1 for d in active if is_thermally_eligible(d)),
        "device_temps": [
            {
                "device_id": d.device_id,
                "cpu_temp_celsius": d.cpu_temp_celsius,
                "thermal_state": d.thermal_state or "NONE",
                "thermal_score": round(thermal_score(d), 3),
                "eligible": is_thermally_eligible(d),
            }
            for d in active
        ],
    }


# ===== STORAGE LAYER (Storage Systems: block/object/file) =====

@app.post("/v1/files")
async def upload_file(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """
    Distributed file storage — replaces Storage Systems.
    Chunks, encrypts, and distributes a file across the phone fleet.
    """
    license_key = ""
    if authorization and authorization.lower().startswith("bearer "):
        license_key = authorization[7:].strip()
    if not license_key:
        raise HTTPException(status_code=401, detail="Authorization: Bearer <license_key> required")

    company = _resolve_company_by_license(db, license_key)
    status, _ = _license_status(company)
    if status == "expired":
        raise HTTPException(status_code=403, detail="License expired")

    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(status_code=400, detail="No file provided — use multipart/form-data with field 'file'")

    data = await file.read()
    filename = file.filename or "unnamed"

    cutoff = datetime.utcnow() - timedelta(seconds=90)
    active_devices = db.query(Device).filter(
        Device.company_id == company.id,
        Device.last_seen >= cutoff,
        Device.is_active == True,
    ).all()

    if not active_devices:
        raise HTTPException(status_code=503, detail="No active devices — file cannot be distributed")

    try:
        result = store_file(company.id, filename, data, active_devices, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Storage failed: {e}")

    return result


@app.get("/v1/files")
def list_files(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    license_key = ""
    if authorization and authorization.lower().startswith("bearer "):
        license_key = authorization[7:].strip()
    if not license_key:
        raise HTTPException(status_code=401, detail="Authorization: Bearer <license_key> required")

    company = _resolve_company_by_license(db, license_key)
    files = db.query(StoredFile).filter(
        StoredFile.company_id == company.id,
        StoredFile.is_deleted == False,
    ).all()

    return {
        "files": [
            {
                "file_id": f.file_id,
                "filename": f.filename,
                "size_bytes": f.total_size_bytes,
                "chunks": f.chunk_count,
                "replication_factor": f.replication_factor,
                "created_at": f.created_at.isoformat(),
            }
            for f in files
        ],
        "storage_stats": fleet_storage_stats(company.id, db),
    }


@app.get("/v1/files/{file_id}")
def download_file(
    file_id: str,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    from fastapi.responses import Response as FastAPIResponse
    license_key = ""
    if authorization and authorization.lower().startswith("bearer "):
        license_key = authorization[7:].strip()
    if not license_key:
        raise HTTPException(status_code=401, detail="Authorization: Bearer <license_key> required")

    _resolve_company_by_license(db, license_key)

    try:
        filename, data = retrieve_file(file_id, db)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return FastAPIResponse(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/v1/files/{file_id}")
def delete_stored_file(
    file_id: str,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    license_key = ""
    if authorization and authorization.lower().startswith("bearer "):
        license_key = authorization[7:].strip()
    if not license_key:
        raise HTTPException(status_code=401, detail="Authorization: Bearer <license_key> required")

    company = _resolve_company_by_license(db, license_key)
    deleted = delete_file(file_id, company.id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found")
    return {"deleted": True, "file_id": file_id}


# ===== SECURITY LAYER (Physical Security + Fire Suppression) =====

@app.get("/api/fleet/security")
def fleet_security(license_key: str, db: Session = Depends(get_db)):
    """Physical Security dashboard: attestation status, quarantine status, anomalies."""
    company = _resolve_company_by_license(db, license_key)
    cutoff = datetime.utcnow() - timedelta(seconds=90)
    devices = db.query(Device).filter(Device.company_id == company.id).all()
    active_ids = [d.device_id for d in devices if d.last_seen and d.last_seen >= cutoff]

    security_status = []
    for d in devices:
        anomaly = check_anomaly(d.device_id, active_ids)
        security_status.append({
            "device_id": d.device_id,
            "hardware_attested": d.hardware_attested,
            "is_quarantined": d.is_quarantined,
            "quarantine_reason": d.quarantine_reason,
            "is_online": d.last_seen is not None and d.last_seen >= cutoff,
            "anomaly_alert": anomaly,
        })

    quarantined = [s for s in security_status if s["is_quarantined"]]
    unattested = [s for s in security_status if not s["hardware_attested"]]
    anomalies = [s for s in security_status if s["anomaly_alert"]]

    return {
        "total_devices": len(devices),
        "quarantined_devices": len(quarantined),
        "unattested_devices": len(unattested),
        "anomalies_detected": len(anomalies),
        "security_score": round(
            (len(devices) - len(quarantined) - len(unattested) * 0.5) / max(len(devices), 1), 3
        ),
        "devices": security_status,
    }


@app.post("/api/device/quarantine")
def quarantine_device(
    license_key: str,
    device_id: str,
    reason: str,
    db: Session = Depends(get_db),
):
    """Fire Suppression equivalent: immediately isolate a compromised device."""
    company = _resolve_company_by_license(db, license_key)
    device = db.query(Device).filter(
        Device.company_id == company.id,
        Device.device_id == device_id,
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device.is_quarantined = True
    device.quarantine_reason = reason
    device.quarantined_at = datetime.utcnow()
    device.is_active = False

    db.add(FleetAlert(
        company_id=company.id,
        severity="critical",
        alert_type="security",
        device_id=device_id,
        message=f"Device {device_id} QUARANTINED: {reason}",
    ))
    db.commit()
    return {"quarantined": True, "device_id": device_id}


@app.post("/api/device/unquarantine")
def unquarantine_device(
    license_key: str,
    device_id: str,
    db: Session = Depends(get_db),
):
    """Lift quarantine and restore a device to active rotation."""
    company = _resolve_company_by_license(db, license_key)
    device = db.query(Device).filter(
        Device.company_id == company.id,
        Device.device_id == device_id,
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device.is_quarantined = False
    device.quarantine_reason = None
    device.quarantined_at = None
    device.is_active = True
    db.commit()
    return {"unquarantined": True, "device_id": device_id}


# ===== NETWORK LAYER (Cabling + Switches + Patch Panels + Raised Floor) =====

@app.get("/api/fleet/network")
def fleet_network(license_key: str, db: Session = Depends(get_db)):
    """Network topology map — replaces Cabling, Switches, Patch Panels, Raised Floor."""
    company = _resolve_company_by_license(db, license_key)
    cutoff = datetime.utcnow() - timedelta(seconds=90)
    devices = db.query(Device).filter(Device.company_id == company.id).all()
    active = [d for d in devices if d.last_seen and d.last_seen >= cutoff]

    def signal_quality(rssi):
        if rssi is None:
            return "unknown"
        if rssi >= -50:
            return "excellent"
        elif rssi >= -60:
            return "good"
        elif rssi >= -70:
            return "fair"
        return "poor"

    nodes = [
        {
            "device_id": d.device_id,
            "device_model": d.device_model,
            "wifi_rssi_dbm": d.wifi_rssi_dbm,
            "signal_quality": signal_quality(d.wifi_rssi_dbm),
            "network_bandwidth_mbps": d.network_bandwidth_mbps,
            "is_online": True,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None,
        }
        for d in active
    ]

    rssi_vals = [d.wifi_rssi_dbm for d in active if d.wifi_rssi_dbm is not None]
    avg_rssi = round(sum(rssi_vals) / len(rssi_vals), 1) if rssi_vals else None

    bw_vals = [d.network_bandwidth_mbps for d in active if d.network_bandwidth_mbps is not None]
    avg_bw = round(sum(bw_vals) / len(bw_vals), 1) if bw_vals else None

    return {
        "active_nodes": len(active),
        "total_nodes": len(devices),
        "avg_wifi_rssi_dbm": avg_rssi,
        "avg_bandwidth_mbps": avg_bw,
        "poor_signal_devices": [n["device_id"] for n in nodes if n["signal_quality"] == "poor"],
        "topology": nodes,
    }


# ===== MONITORING LAYER (Monitoring & Management — NOC Dashboard) =====

@app.get("/api/fleet/health")
def fleet_health(license_key: str, db: Session = Depends(get_db)):
    """
    Full NOC dashboard — replaces Monitoring & Management.
    Single endpoint showing all 18 data center capability layers.
    """
    company = _resolve_company_by_license(db, license_key)
    cutoff = datetime.utcnow() - timedelta(seconds=90)
    all_devices = db.query(Device).filter(Device.company_id == company.id).all()
    active = [d for d in all_devices if d.last_seen and d.last_seen >= cutoff]

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    queries_today = db.query(Query).filter(
        Query.company_id == company.id,
        Query.created_at >= today_start,
    ).count()

    active_alerts = db.query(FleetAlert).filter(
        FleetAlert.company_id == company.id,
        FleetAlert.is_resolved == False,
    ).order_by(FleetAlert.created_at.desc()).limit(20).all()

    storage_stats = fleet_storage_stats(company.id, db)

    rssi_vals = [d.wifi_rssi_dbm for d in active if d.wifi_rssi_dbm is not None]
    avg_rssi = round(sum(rssi_vals) / len(rssi_vals), 1) if rssi_vals else None

    return {
        # Compute layer (Server Racks + GPU/AI Servers)
        "compute": {
            "active_devices": len(active),
            "total_devices": len(all_devices),
            "queries_today": queries_today,
            "power_eligible": sum(1 for d in active if is_power_eligible(d)),
            "thermal_eligible": sum(1 for d in active if is_thermally_eligible(d)),
        },
        # Power layer (Grid + Generators + UPS + PDUs)
        "power": {
            "fleet_battery_avg": round(sum(d.battery_level or 100 for d in active) / len(active), 1) if active else None,
            "charging_devices": sum(1 for d in active if d.is_charging),
            "reserve_pool_size": len(get_reserve_pool(active)),
            "low_battery_count": sum(1 for d in active if (d.battery_level or 100) < 30),
        },
        # Thermal layer (Chillers + Cooling Towers + CRAC/CRAH + Underfloor)
        "thermal": fleet_thermal_health(active),
        # Storage layer (Storage Systems)
        "storage": storage_stats,
        # Security layer (Physical Security + Fire Suppression)
        "security": {
            "quarantined_devices": sum(1 for d in all_devices if d.is_quarantined),
            "hardware_attested": sum(1 for d in active if d.hardware_attested),
            "unattested_count": sum(1 for d in active if not d.hardware_attested),
        },
        # Network layer (Cabling + Switches + Patch Panels + Raised Floor)
        "network": {
            "avg_wifi_rssi_dbm": avg_rssi,
            "poor_signal_count": sum(
                1 for d in active if d.wifi_rssi_dbm is not None and d.wifi_rssi_dbm < -70
            ),
        },
        # Active alerts (Monitoring & Management NOC)
        "active_alerts": [
            {
                "id": a.id,
                "severity": a.severity,
                "type": a.alert_type,
                "device_id": a.device_id,
                "message": a.message,
                "created_at": a.created_at.isoformat(),
            }
            for a in active_alerts
        ],
    }


@app.get("/api/fleet/alerts")
def fleet_alerts(license_key: str, resolved: bool = False, db: Session = Depends(get_db)):
    """Alert log — NOC alert management."""
    company = _resolve_company_by_license(db, license_key)
    query = db.query(FleetAlert).filter(
        FleetAlert.company_id == company.id,
        FleetAlert.is_resolved == resolved,
    ).order_by(FleetAlert.created_at.desc()).limit(100)

    return {
        "alerts": [
            {
                "id": a.id,
                "severity": a.severity,
                "type": a.alert_type,
                "device_id": a.device_id,
                "message": a.message,
                "created_at": a.created_at.isoformat(),
                "is_resolved": a.is_resolved,
            }
            for a in query.all()
        ]
    }


@app.post("/api/fleet/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int, license_key: str, db: Session = Depends(get_db)):
    """Mark an alert as resolved."""
    company = _resolve_company_by_license(db, license_key)
    alert = db.query(FleetAlert).filter(
        FleetAlert.id == alert_id,
        FleetAlert.company_id == company.id,
    ).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_resolved = True
    alert.resolved_at = datetime.utcnow()
    db.commit()
    return {"resolved": True}


@app.get("/api/roles")
def get_roles():
    return ROLES


# ===== MODEL SHARDING (pipeline-parallel inference across phone fleet) =====

from shard_coordinator import (
    MODEL_SPECS, plan_shards, configure_shard_devices,
    run_sharded_inference, get_fleet_shard_status,
)


@app.get("/api/sharding/models")
def list_shard_models():
    """List models that support sharded inference and their requirements."""
    return {
        "models": [
            {
                "name": name,
                "num_layers": spec["num_layers"],
                "hidden_dim": spec["hidden_dim"],
                "min_ram_per_shard_mb": spec["min_ram_per_shard_mb"],
                "description": spec["description"],
            }
            for name, spec in MODEL_SPECS.items()
        ]
    }


@app.get("/api/sharding/plan")
def get_shard_plan(license_key: str, model: str, db: Session = Depends(get_db)):
    """
    Plan layer assignments across the current fleet for a given model.
    Does not configure devices — call /api/sharding/configure to apply.
    """
    company = _resolve_company_by_license(db, license_key)
    cutoff = datetime.utcnow() - timedelta(seconds=90)
    active = db.query(Device).filter(
        Device.company_id == company.id,
        Device.last_seen >= cutoff,
        Device.is_active == True,
        Device.is_quarantined == False,
    ).all()

    plan = plan_shards(model, active)
    return {
        "feasible": plan.feasible,
        "reason": plan.reason if not plan.feasible else None,
        "model": plan.model_name,
        "total_shards": plan.total_shards,
        "total_layers": plan.total_layers,
        "hidden_dim": plan.hidden_dim,
        "shard_assignments": [
            {
                "shard_index": s.shard_index,
                "device_id": s.device_id,
                "device_ip": s.device_ip,
                "layers": f"{s.layer_start}–{s.layer_end - 1}",
                "layer_count": s.layer_end - s.layer_start,
                "is_final_shard": s.is_final_shard,
                "ram_available_mb": s.ram_available_mb,
            }
            for s in plan.shards
        ] if plan.feasible else [],
    }


@app.post("/api/sharding/configure")
async def configure_sharding(
    license_key: str,
    model: str,
    model_base_path: str = "/sdcard/fleetmind/models",
    db: Session = Depends(get_db),
):
    """
    Plan and push shard configuration to devices.
    Each device receives its layer range, model path, and next-shard URL.
    """
    company = _resolve_company_by_license(db, license_key)
    cutoff = datetime.utcnow() - timedelta(seconds=90)
    active = db.query(Device).filter(
        Device.company_id == company.id,
        Device.last_seen >= cutoff,
        Device.is_active == True,
        Device.is_quarantined == False,
    ).all()

    plan = plan_shards(model, active)
    if not plan.feasible:
        raise HTTPException(status_code=409, detail=plan.reason)

    results = await configure_shard_devices(plan, model_base_path)
    configured = sum(1 for ok in results.values() if ok)

    return {
        "model": model,
        "total_shards": plan.total_shards,
        "configured": configured,
        "failed": plan.total_shards - configured,
        "device_results": results,
        "ready": configured == plan.total_shards,
    }


@app.post("/api/sharding/infer")
async def sharded_inference(
    license_key: str,
    model: str,
    prompt: str,
    max_new_tokens: int = 256,
    temperature: float = 0.7,
    db: Session = Depends(get_db),
):
    """
    Run sharded inference for a prompt across the phone fleet.
    The fleet must already be configured via /api/sharding/configure.

    Token IDs are computed via a simple BPE stub (production: use proper tokenizer).
    For now, returns raw token IDs — wire in a Hugging Face tokenizer server for text.
    """
    company = _resolve_company_by_license(db, license_key)
    status, _ = _license_status(company)
    if status == "expired":
        raise HTTPException(status_code=403, detail="License expired")

    cutoff = datetime.utcnow() - timedelta(seconds=90)
    active = db.query(Device).filter(
        Device.company_id == company.id,
        Device.last_seen >= cutoff,
        Device.is_active == True,
        Device.is_quarantined == False,
    ).all()

    plan = plan_shards(model, active)
    if not plan.feasible:
        raise HTTPException(
            status_code=503,
            detail=f"Fleet cannot run {model}: {plan.reason}",
        )

    # Simple token encoding stub — each UTF-8 byte becomes a token ID.
    # Replace with proper tokenizer (llama.cpp tokenizer server or HuggingFace) in production.
    token_ids = list(prompt.encode("utf-8"))

    try:
        result = await run_sharded_inference(
            plan, token_ids, max_new_tokens=max_new_tokens, temperature=temperature
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sharded inference failed: {e}")

    return {
        **result,
        "prompt_tokens": len(token_ids),
        "cost_usd": 0.0,
        "egress_bytes": 0,
    }


@app.get("/api/sharding/status")
async def sharding_status(license_key: str, db: Session = Depends(get_db)):
    """Poll each device for shard readiness and RAM availability."""
    company = _resolve_company_by_license(db, license_key)
    cutoff = datetime.utcnow() - timedelta(seconds=90)
    active = db.query(Device).filter(
        Device.company_id == company.id,
        Device.last_seen >= cutoff,
    ).all()

    fleet_status = await get_fleet_shard_status(active)
    total_ram_mb = sum(s.get("ram_available_mb") or 0 for s in fleet_status)

    feasibility = {}
    for model_name in MODEL_SPECS:
        plan = plan_shards(model_name, active)
        feasibility[model_name] = {
            "feasible": plan.feasible,
            "shards_needed": plan.total_shards,
            "reason": plan.reason if not plan.feasible else None,
        }

    return {
        "fleet_total_ram_mb": total_ram_mb,
        "fleet_total_ram_gb": round(total_ram_mb / 1024, 1),
        "active_devices": len(active),
        "devices": fleet_status,
        "model_feasibility": feasibility,
    }
