import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey, Float, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fleetmind.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    employee_count = Column(Integer, nullable=False)
    reg_number = Column(String, unique=True, nullable=False)
    trial_token = Column(String, unique=True, index=True, nullable=False)
    license_key = Column(String, unique=True, index=True, nullable=True)
    plan = Column(String, default="trial")
    trial_expiry = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    devices = relationship("Device", back_populates="company")
    queries = relationship("Query", back_populates="company")
    employees = relationship("Employee", back_populates="company")
    alerts = relationship("FleetAlert", back_populates="company")


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    device_id = Column(String, nullable=False, index=True)
    device_model = Column(String, nullable=False)
    last_seen = Column(DateTime, default=datetime.utcnow)
    queries_processed = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    operator_role = Column(String, default="engineer")
    public_key = Column(Text, nullable=True)
    hardware_attested = Column(Boolean, default=False)
    attestation_verified_at = Column(DateTime, nullable=True)

    # Power layer (replaces: Grid, Generators, UPS, PDUs)
    battery_level = Column(Integer, default=100)
    is_charging = Column(Boolean, default=False)
    estimated_runtime_mins = Column(Integer, nullable=True)

    # Thermal layer (replaces: Chillers, Cooling Towers, CRAC/CRAH, Underfloor)
    cpu_temp_celsius = Column(Float, nullable=True)
    thermal_state = Column(String, default="NONE")  # NONE/LIGHT/MODERATE/SEVERE/CRITICAL

    # Network layer (replaces: Cabling, Switches, Patch Panels, Raised Floor)
    wifi_rssi_dbm = Column(Integer, nullable=True)
    network_bandwidth_mbps = Column(Float, nullable=True)

    # Compute metrics
    cpu_usage_percent = Column(Float, nullable=True)
    ram_available_mb = Column(Integer, nullable=True)

    # Storage layer (replaces: Storage Systems)
    available_storage_mb = Column(Integer, nullable=True)
    used_storage_mb = Column(Integer, default=0)

    # Direct chunk push address (reported by device in heartbeat)
    device_ip = Column(String, nullable=True)

    # Security/Fire Suppression
    is_quarantined = Column(Boolean, default=False)
    quarantine_reason = Column(String, nullable=True)
    quarantined_at = Column(DateTime, nullable=True)

    company = relationship("Company", back_populates="devices")
    queries = relationship("Query", back_populates="device")


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    email = Column(String, nullable=False)
    role = Column(String, default="engineer")
    device_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="employees")


class Query(Base):
    __tablename__ = "queries"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=True)
    prompt_hash = Column(String, nullable=False)
    latency_ms = Column(Integer, nullable=False)
    user_role = Column(String, nullable=True)
    namespace = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="queries")
    device = relationship("Device", back_populates="queries")


class StoredFile(Base):
    __tablename__ = "stored_files"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    file_id = Column(String, unique=True, index=True)
    filename = Column(String, nullable=False)
    total_size_bytes = Column(Integer, nullable=False)
    chunk_count = Column(Integer, nullable=False)
    replication_factor = Column(Integer, default=2)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    encryption_key_b64 = Column(Text, nullable=True)

    chunks = relationship("StorageChunk", back_populates="file")


class StorageChunk(Base):
    __tablename__ = "storage_chunks"

    id = Column(Integer, primary_key=True)
    file_id = Column(String, ForeignKey("stored_files.file_id"), index=True)
    chunk_index = Column(Integer, nullable=False)
    device_id = Column(String, nullable=False)  # which phone "holds" this chunk
    storage_path = Column(String, nullable=False)  # path on backend filesystem
    chunk_size_bytes = Column(Integer, nullable=False)
    checksum = Column(String, nullable=False)  # sha256 of plaintext chunk
    on_device = Column(Boolean, default=False)  # True if chunk was pushed to device HTTP endpoint

    file = relationship("StoredFile", back_populates="chunks")


class FleetAlert(Base):
    __tablename__ = "fleet_alerts"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    severity = Column(String, nullable=False)  # info/warning/critical
    alert_type = Column(String, nullable=False)  # power/thermal/security/network/storage
    device_id = Column(String, nullable=True)
    message = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    is_resolved = Column(Boolean, default=False)

    company = relationship("Company", back_populates="alerts")


class PowerEvent(Base):
    __tablename__ = "power_events"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    device_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)  # charging_started/charging_stopped/low_battery/critical_battery/device_offline
    battery_level = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
