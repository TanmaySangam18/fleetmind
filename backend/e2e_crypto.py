"""
FleetMind True End-to-End Encryption — ECDH-based, Backend-Blind Routing

The server routes encrypted queries it CANNOT decrypt.
No private key ever touches the backend.
Not a policy. Mathematics.

Key flow:
  Device starts → generates EC key pair via TrustZone (Android Keystore)
  Device posts public key to backend
  Backend stores public key only — has zero knowledge of private key

  Requester sends query → encrypts with target device's public key (ECDH + AES-256-GCM)
  Backend receives ciphertext → RBAC checks role/namespace → routes blob to device
  Backend cannot decrypt — it never had the private key

  Target device decrypts using its TrustZone-protected private key
  Device encrypts response back using requester's ephemeral public key
  Requester decrypts response
"""

import base64
import os

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDH,
    SECP256R1,
    EllipticCurvePublicNumbers,
    generate_private_key,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key

_CURVE = SECP256R1()
_INFO_QUERY = b"fleetmind-query-v1"
_INFO_RESPONSE = b"fleetmind-response-v1"
_EPHEMERAL_PUB_LEN = 65  # uncompressed P-256 point: 0x04 + 32-byte X + 32-byte Y
_NONCE_LEN = 12


def generate_device_keypair() -> tuple[str, str]:
    """
    Generate an EC key pair for a FleetMind node.

    On a real Android device this happens inside ARM TrustZone via Android Keystore.
    The private key is generated inside the TEE and never exported — only operations
    using it are permitted (ECDH exchange, signing). This Python implementation
    simulates that flow for Mac nodes, CI, and demos.

    Returns:
        (private_key_pem, public_key_pem)
        Only public_key_pem is ever shared with the backend.
    """
    private_key = generate_private_key(_CURVE)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def encrypt_to_device(plaintext: str, device_public_key_pem: str) -> str:
    """
    Encrypt a query for a specific device using its public key.

    Uses an ephemeral ECDH keypair — the shared secret is derived once and
    discarded. The backend cannot decrypt this because it holds no private key.
    An attacker who compromises the backend server sees only an opaque blob.

    Wire format (base64url):
        [65 bytes] ephemeral requester public key (X9.62 uncompressed)
        [12 bytes] AES-GCM nonce
        [N  bytes] AES-256-GCM ciphertext + 16-byte tag

    Args:
        plaintext: The query string to encrypt.
        device_public_key_pem: The target device's EC public key (PEM).

    Returns:
        base64url-encoded ciphertext blob.
    """
    device_pub = load_pem_public_key(device_public_key_pem.encode())

    ephemeral_private = generate_private_key(_CURVE)
    shared_secret = ephemeral_private.exchange(ECDH(), device_pub)

    aes_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_INFO_QUERY,
    ).derive(shared_secret)

    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(aes_key).encrypt(nonce, plaintext.encode(), None)

    ephemeral_pub_bytes = ephemeral_private.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )

    return base64.urlsafe_b64encode(ephemeral_pub_bytes + nonce + ciphertext).decode()


def decrypt_query(ciphertext_b64: str, device_private_key_pem: str) -> str:
    """
    Decrypt a query using the device's private key.

    On Android this is a call into ARM TrustZone via Android Keystore —
    the private key bytes are never returned to the Normal World.

    Raises cryptography.exceptions.InvalidTag if the ciphertext was not
    encrypted for this device. The rejection is a hardware-level AES-GCM
    authentication failure — not an HTTP 403 or a policy check.
    """
    device_priv = load_pem_private_key(device_private_key_pem.encode(), password=None)

    blob = base64.urlsafe_b64decode(_pad(ciphertext_b64))
    ephemeral_pub_bytes = blob[:_EPHEMERAL_PUB_LEN]
    nonce = blob[_EPHEMERAL_PUB_LEN : _EPHEMERAL_PUB_LEN + _NONCE_LEN]
    ciphertext = blob[_EPHEMERAL_PUB_LEN + _NONCE_LEN :]

    x = int.from_bytes(ephemeral_pub_bytes[1:33], "big")
    y = int.from_bytes(ephemeral_pub_bytes[33:65], "big")
    ephemeral_pub = EllipticCurvePublicNumbers(x, y, _CURVE).public_key(default_backend())

    shared_secret = device_priv.exchange(ECDH(), ephemeral_pub)

    aes_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_INFO_QUERY,
    ).derive(shared_secret)

    return AESGCM(aes_key).decrypt(nonce, ciphertext, None).decode()


def encrypt_response(response: str, requester_ephemeral_pub_bytes: bytes) -> str:
    """
    Encrypt a response back to the requester using their ephemeral public key.

    The processing device encrypts the response so only the requester's
    TrustZone can open it. The backend cannot read responses in transit.

    Args:
        response: The inference result to send back.
        requester_ephemeral_pub_bytes: 65-byte X9.62 uncompressed public key
            (extracted from the incoming ciphertext blob).

    Returns:
        base64url-encoded response blob.
    """
    x = int.from_bytes(requester_ephemeral_pub_bytes[1:33], "big")
    y = int.from_bytes(requester_ephemeral_pub_bytes[33:65], "big")
    requester_pub = EllipticCurvePublicNumbers(x, y, _CURVE).public_key(default_backend())

    responder_private = generate_private_key(_CURVE)
    shared_secret = responder_private.exchange(ECDH(), requester_pub)

    aes_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_INFO_RESPONSE,
    ).derive(shared_secret)

    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(aes_key).encrypt(nonce, response.encode(), None)

    responder_pub_bytes = responder_private.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )

    return base64.urlsafe_b64encode(responder_pub_bytes + nonce + ciphertext).decode()


def get_ephemeral_pub_bytes(ciphertext_b64: str) -> bytes:
    """Extract the requester's ephemeral public key from a ciphertext blob."""
    blob = base64.urlsafe_b64decode(_pad(ciphertext_b64))
    return blob[:_EPHEMERAL_PUB_LEN]


def _pad(s: str) -> str:
    return s + "==" * ((-len(s)) % 4 == 0) + "=" * ((-len(s)) % 4)
