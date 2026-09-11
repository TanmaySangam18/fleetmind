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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
