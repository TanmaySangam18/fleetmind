import hmac
import hashlib
import os


SECRET_KEY = os.getenv("SECRET_KEY", "changeme")
_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _encode_segment(data: bytes, length: int = 4) -> str:
    n = int.from_bytes(data[:4], "big")
    chars = []
    base = len(_CHARSET)
    for _ in range(length):
        chars.append(_CHARSET[n % base])
        n //= base
    return "".join(chars)


def generate_license_key(company_id: int) -> str:
    payload = f"fleetmind:company:{company_id}".encode()
    digest = hmac.new(SECRET_KEY.encode(), payload, hashlib.sha256).digest()  # type: ignore[attr-defined]
    seg1 = _encode_segment(digest[0:4])
    seg2 = _encode_segment(digest[4:8])
    seg3 = _encode_segment(digest[8:12])
    return f"FM-{seg1}-{seg2}-{seg3}"


def verify_license_key(company_id: int, key: str) -> bool:
    expected = generate_license_key(company_id)
    return hmac.compare_digest(expected, key)
