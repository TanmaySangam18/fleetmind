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

from database import get_db, init_db, Company, Device, Query, Employee
from license import generate_license_key
from rbac import (
    ROLES, NAMESPACES, can_access, get_accessible_namespaces,
    get_eligible_nodes, generate_user_key, encrypt_query, decrypt_query,
)

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


# ---------- Helpers ----------

def _generate_trial_token() -> str:
    return uuid.uuid4().hex


def _resolve_company_by_license(db: Session, license_key: str) -> Company:
    company = db.query(Company).filter(Company.license_key == license_key).first()
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
    else:
        device = Device(
            company_id=company.id,
            device_id=body.device_id,
            device_model=body.device_model,
            queries_processed=body.queries_processed,
            is_active=True,
            operator_role=operator_role,
        )
        db.add(device)

    db.commit()
    return {"acknowledged": True, "server_time": datetime.utcnow().isoformat()}


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

    idx = _round_robin_index.get(company.id, 0)
    target_device = active_devices[idx % len(active_devices)]
    _round_robin_index[company.id] = (idx + 1) % len(active_devices)

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


@app.get("/api/roles")
def get_roles():
    return ROLES
