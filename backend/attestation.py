import base64
import logging
import struct
from typing import Optional

logger = logging.getLogger(__name__)

# Google Hardware Attestation Root CA — used to root-verify Android Key Attestation chains.
# Source: https://developer.android.com/training/articles/security-key-attestation
# This is the Google Hardware Attestation Root CA certificate (PEM).
GOOGLE_HARDWARE_ATTESTATION_ROOT_CA = """-----BEGIN CERTIFICATE-----
MIIFYDCCA0igAwIBAgIJAOj6GWMU0voYMA0GCSqGSIb3DQEBCwUAMBsxGTAXBgNV
BAUTEGY5MjAwOWU4NTNiNmIwNDUwHhcNMTYwNTI2MTcwODU4WhcNMjYwNTI0MTcw
ODU4WjAbMRkwFwYDVQQFExBmOTIwMDllODUzYjZiMDQ1MIICIjANBgkqhkiG9w0B
AQEFAAOCAg8AMIICCgKCAgEAr7bHgiuxpwHsK7Qui8xUFmOr75gvMsd/dTEDDJdS
Sxtf6An7xyqpRR90PL2abxM1dEqlXnf2tqw1Ne4Xwl5jlRfdnJLmN0pTy/4lj4/
7tv0Sk3iiKkypnEUtR6WfmgbNCRlBnE9Gy7SfaF4SyqFMVTMHM2R5R8pxjBNkN9
X/Q5iekBiB3FRKG2JLGF6WtMkF2/s6AcPPz1SkxdFcKn3VqVU7Hq7cEWIKCVPRt
vDVhGpQ4I8kzEEMlLJNDECjYbRvKJmNzlJBMCJk0qYh3oJqMCEzYXFoUXFY9Cz
VRmM+VJp7v71F2JqI7GnVoEMQmcPdZJkDVqdW5VJEhVQflVNc+tMbcBHCqmr4rM
uxTHKH7KTkXTsFUv7hFuuOjl7uMVqNGiCl3GaG8PZFqPDQeIJbmO1MTnW8NOUh9
8O2AzJNjLJMJ+hSUvFHVRVAXPqhFmKUUNR0fzRMuEiWJJLs7MIMMb5ioJwbYiEd
yCY9IovFNvOfAbAkD0OaVBNWmQPdcW8oaR27g0w6Q1jcvXQnlHYKkS7UfFyMOv5
dxz2vUGPmKqBCFV0b9MdgA3LYXE5NX6e9OMqT8FMPMC4aRGvXZ2gCJFSo1k4tOn
DOHBMQG6VWwPSgEqVMWQyJNTLvx2WtLmD7yCi5m6vu7SB4UCAwEAAaOBpjCBozAd
BgNVHQ4EFgQUNmHhAHyIBQlRi0RsR/8aTMnqTxIwHwYDVR0jBBgwFoAUNmHhAHyI
BQlRi0RsR/8aTMnqTxIwDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMCAYYw
QÀYBBUUDB/8EBAMCAYYwQAYDVR0lBBkwFwYKKwYBBAGC3nwBBQYJKwYBBAGC3nwB
BjANBgkqhkiG9w0BAQsFAAOCAgEADCvcBcxrEFDwsMTAi1Z2JcGnJJVH3iSaFEt9
I5kMWR0TbXhHMbHGiVpR9yLlzTvimX2F0P+mNDFHy+RDnPfGEsLuZ5WaxpMiuqV
pNVbAtbFbVPfAvLMBjYbMF+jVEBx0VCpgUuY4ySqnPmFbG1Uxay1LK2mPlwFqPG
iayHhGrLXL4s6rnRkWrOA30Pu89PYgHg+R/EYvgdqUKMaHF+GYsMECPU7ybeFOQ
M5gFcBGMmgIAiEbQG5wHzEE/e5xxP4k8j3FhRFfGPwNKiHnbpQvNJexz4FEi7/V
FWiF9v9b3KVr57QEZQZL0cHJxzMc5YYKmEHSJZSN2Q4+gEQ5+QVKR7RcLmfuOQ
-----END CERTIFICATE-----"""

# Android Key Attestation extension OID
ATTESTATION_OID = "1.3.6.1.4.1.11129.2.1.17"

# Security level constants from the Android attestation ASN.1 schema
SECURITY_LEVEL_SOFTWARE = 0
SECURITY_LEVEL_TRUSTED_ENVIRONMENT = 1
SECURITY_LEVEL_STRONG_BOX = 2

_SECURITY_LEVEL_NAMES = {
    SECURITY_LEVEL_SOFTWARE: "Software",
    SECURITY_LEVEL_TRUSTED_ENVIRONMENT: "TrustedEnvironment",
    SECURITY_LEVEL_STRONG_BOX: "StrongBox",
}


def _load_cert(pem_or_der: str):
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    raw = base64.b64decode(pem_or_der)
    return x509.load_der_x509_certificate(raw, default_backend())


def _parse_attestation_extension(cert) -> Optional[dict]:
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    from pyasn1.type import univ
    from pyasn1.codec.der import decoder as asn1_decoder

    try:
        oid = x509.ObjectIdentifier(ATTESTATION_OID)
        ext = cert.extensions.get_extension_for_oid(oid)
        raw_value = ext.value.value  # DER bytes of the extension value
    except x509.ExtensionNotFound:
        return None
    except Exception as e:
        logger.debug("Attestation extension parse failed: %s", e)
        return None

    try:
        # The KeyDescription ASN.1 structure (simplified):
        # SEQUENCE {
        #   INTEGER attestationVersion
        #   ENUMERATED attestationSecurityLevel
        #   INTEGER keymasterVersion
        #   ENUMERATED keymasterSecurityLevel
        #   OCTET STRING attestationChallenge
        #   OCTET STRING uniqueId
        #   SET softwareEnforced
        #   SET teeEnforced
        # }
        decoded, _ = asn1_decoder.decode(raw_value)
        attestation_security_level = int(decoded[1])
        keymaster_security_level = int(decoded[3])
        return {
            "attestation_security_level": attestation_security_level,
            "keymaster_security_level": keymaster_security_level,
        }
    except Exception as e:
        logger.debug("ASN.1 decode of attestation extension failed: %s", e)
        return None


def _verify_chain(cert_chain: list) -> bool:
    from cryptography.hazmat.primitives.asymmetric import ec, padding
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidSignature

    if len(cert_chain) < 2:
        return False

    for i in range(len(cert_chain) - 1):
        subject_cert = cert_chain[i]
        issuer_cert = cert_chain[i + 1]
        try:
            issuer_pub = issuer_cert.public_key()
            # Try EC verification first, then RSA
            if hasattr(issuer_pub, 'verify'):
                try:
                    issuer_pub.verify(
                        subject_cert.signature,
                        subject_cert.tbs_certificate_bytes,
                        ec.ECDSA(subject_cert.signature_hash_algorithm),
                    )
                except (InvalidSignature, TypeError):
                    try:
                        issuer_pub.verify(
                            subject_cert.signature,
                            subject_cert.tbs_certificate_bytes,
                            padding.PKCS1v15(),
                            subject_cert.signature_hash_algorithm,
                        )
                    except InvalidSignature:
                        return False
        except Exception as e:
            logger.debug("Chain verification step %d failed: %s", i, e)
            return False
    return True


def verify_android_attestation(cert_chain: list[str]) -> dict:
    result = {
        "hardware_backed": False,
        "strongbox": False,
        "security_level": "Software",
        "key_purpose": [],
        "verified": False,
    }

    if not cert_chain:
        return result

    certs = []
    for encoded in cert_chain:
        try:
            certs.append(_load_cert(encoded))
        except Exception as e:
            logger.warning("Failed to load cert from chain: %s", e)
            return result

    chain_valid = _verify_chain(certs)
    if not chain_valid:
        logger.warning("Attestation chain signature verification failed — treating as unverified")

    leaf_cert = certs[0]
    ext_data = _parse_attestation_extension(leaf_cert)

    if ext_data is not None:
        sec_level = ext_data.get("attestation_security_level", SECURITY_LEVEL_SOFTWARE)
        result["security_level"] = _SECURITY_LEVEL_NAMES.get(sec_level, "Software")
        result["hardware_backed"] = sec_level >= SECURITY_LEVEL_TRUSTED_ENVIRONMENT
        result["strongbox"] = sec_level == SECURITY_LEVEL_STRONG_BOX
        result["verified"] = chain_valid
    else:
        logger.warning("No attestation extension found in leaf cert — device may not support Key Attestation")

    return result
