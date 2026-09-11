import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROLES = {
    "engineer": 1,
    "operations": 2,
    "hr": 3,
    "finance": 4,
    "executive": 5,
    "admin": 99,
}

NAMESPACES = {
    "technical": 1,
    "operations": 2,
    "hr": 3,
    "finance": 4,
    "executive": 5,
}


def can_access(user_role: str, namespace: str) -> bool:
    role_level = ROLES.get(user_role, 0)
    required = NAMESPACES.get(namespace, 999)
    return role_level >= required


def get_accessible_namespaces(user_role: str) -> list[str]:
    role_level = ROLES.get(user_role, 0)
    return [ns for ns, req in NAMESPACES.items() if role_level >= req]


def get_eligible_nodes(user_role: str, active_nodes: list[dict]) -> list[dict]:
    role_level = ROLES.get(user_role, 0)
    return [n for n in active_nodes if ROLES.get(n.get("operator_role", "engineer"), 1) >= role_level]


def generate_user_key(company_id: int, user_email: str, secret: str) -> str:
    payload = f"{company_id}:{user_email}".encode()
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).digest()  # type: ignore[attr-defined]
    return base64.urlsafe_b64encode(digest).decode()


def encrypt_query(query: str, user_key: str) -> str:
    key_bytes = base64.urlsafe_b64decode(user_key + "==")[:32]
    nonce = os.urandom(12)
    ct = AESGCM(key_bytes).encrypt(nonce, query.encode(), None)
    return base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt_query(encrypted: str, user_key: str) -> str:
    key_bytes = base64.urlsafe_b64decode(user_key + "==")[:32]
    raw = base64.urlsafe_b64decode(encrypted + "==")
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key_bytes).decrypt(nonce, ct, None).decode()
