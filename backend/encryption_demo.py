import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from rbac import (
    ROLES, NAMESPACES, can_access, get_accessible_namespaces,
    get_eligible_nodes, generate_user_key, encrypt_query, decrypt_query,
)

DEMO_SECRET = "fleetmind-demo-secret"
COMPANY_ID = 1

USERS = {
    "cfo@acme.com": "finance",
    "engineer@acme.com": "engineer",
}

NODES = [
    {"device_id": "exec-phone-1", "operator_role": "executive"},
    {"device_id": "finance-phone-1", "operator_role": "finance"},
    {"device_id": "ops-phone-1", "operator_role": "operations"},
    {"device_id": "eng-phone-1", "operator_role": "engineer"},
]

def demo_user(email: str, role: str, query_text: str, namespace: str):
    print(f"\n{'='*60}")
    print(f"  User : {email}  (role: {role})")
    print(f"  Query: {query_text!r}")
    print(f"  Namespace: {namespace}")
    print(f"{'='*60}")

    key = generate_user_key(COMPANY_ID, email, DEMO_SECRET)
    print(f"  User key (HMAC-derived, never stored): {key[:20]}...")

    encrypted = encrypt_query(query_text, key)
    print(f"  Encrypted query: {encrypted[:32]}...")

    if not can_access(role, namespace):
        print(f"\n  ACCESS DENIED — {role} cannot access '{namespace}' namespace")
        print(f"  Query never reaches any device.")
        return

    eligible = get_eligible_nodes(role, NODES)
    eligible_ids = [n["device_id"] for n in eligible]
    blocked_ids = [n["device_id"] for n in NODES if n not in eligible]

    print(f"\n  ACCESS GRANTED")
    print(f"  Eligible nodes  : {eligible_ids}")
    print(f"  Blocked nodes   : {[n['device_id'] for n in NODES if n['device_id'] not in eligible_ids]}")

    if not eligible:
        print("  No eligible nodes available.")
        return

    target = eligible[0]
    print(f"  Routed to       : {target['device_id']} (operator_role={target['operator_role']})")

    mock_response = f"Q3 revenue was $2.3M, up 18% YoY" if "revenue" in query_text.lower() else "Processed: " + query_text
    encrypted_response = encrypt_query(mock_response, key)
    print(f"  Encrypted resp  : {encrypted_response[:32]}...")

    decrypted = decrypt_query(encrypted_response, key)
    print(f"  Decrypted by {email.split('@')[0]}: {decrypted!r}")


def main():
    print("\nFleetMind End-to-End Encryption + RBAC Demo")
    print("=============================================\n")

    print("Active mesh nodes:")
    for n in NODES:
        level = ROLES.get(n["operator_role"], 0)
        print(f"  {n['device_id']:25s}  operator_role={n['operator_role']} (level {level})")

    demo_user(
        "cfo@acme.com", "finance",
        "What is our Q3 revenue?",
        "finance",
    )

    demo_user(
        "engineer@acme.com", "engineer",
        "What is our Q3 revenue?",
        "finance",
    )

    demo_user(
        "engineer@acme.com", "engineer",
        "Show me the API server logs",
        "technical",
    )

    print(f"\n{'='*60}")
    print("  Summary")
    print(f"{'='*60}")
    print("  CFO query   → encrypted → routed ONLY to finance/exec nodes")
    print("  Engineer tried finance namespace → REJECTED before routing")
    print("  Engineer technical query → routed ONLY to engineer+ nodes")
    print("  All ciphertext is AES-256-GCM. Keys are never stored in DB.")
    print()


if __name__ == "__main__":
    main()
