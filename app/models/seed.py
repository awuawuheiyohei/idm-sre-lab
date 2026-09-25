"""Seed: 1 OAuth client + 3 mock users (克诺尔 BU) + RSA signing key"""
import json
from datetime import datetime, timezone

from ..db import init_db, get_conn, hash_password, ensure_signing_key
from . import oauth_store  # noqa


def seed_all(verbose=False):
    init_db(verbose=verbose)
    kid = ensure_signing_key("key-2026-09")
    conn = get_conn()

    # 清空
    for t in ("oauth_audit", "tokens", "authorization_codes", "users", "oauth_clients"):
        conn.execute(f"DELETE FROM {t}")

    # 1 OAuth client
    client_secret = "tripbiz-booking-app-secret-2026"  # demo; prod should rotate
    conn.execute(
        """INSERT INTO oauth_clients
           (client_id, client_secret, client_name, redirect_uris, grant_types, scopes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("tripbiz-booking-app", hash_password(client_secret), "TripBiz Booking Web App",
         json.dumps(["http://localhost:5050/callback", "http://127.0.0.1:5050/callback"]),
         json.dumps(["authorization_code", "refresh_token"]),
         json.dumps(["openid", "profile", "email"]))
    )
    if verbose:
        print(f"[+] Seeded client: tripbiz-booking-app (secret={client_secret})")

    # 3 mock users（克诺尔 BU 场景）
    users = [
        ("USER-001", "engineer01", "engineer01@tripbiz.com", "李工 (Engineer)",
         "Engineer@2026", "platform", "employee"),
        ("USER-002", "bu-lead01", "bu.lead@tripbiz.com", "王经理 (BU Lead)",
         "BuLead@2026", "commercial-vehicle", "bu_lead"),
        ("USER-003", "admin01", "admin@tripbiz.com", "Admin (IT 主管)",
         "Admin@2026", "platform", "it_admin"),
    ]
    for uid, uname, email, name, pwd, bu, role in users:
        conn.execute(
            """INSERT INTO users (user_id, username, email, full_name, password_hash,
               business_unit, role) VALUES (?,?,?,?,?,?,?)""",
            (uid, uname, email, name, hash_password(pwd), bu, role)
        )
    if verbose:
        print(f"[+] Seeded {len(users)} users")
        for u in users:
            print(f"    {u[0]}: {u[1]} / {u[4]} ({u[5]})")

    conn.commit()

    # 2 SAML Service Providers（demo SP — TripBiz Booking 应用）
    for tbl in ("saml_sessions", "saml_audit", "saml_service_providers", "saml_identity_providers"):
        conn.execute(f"DELETE FROM {tbl}")
    conn.execute(
        """INSERT INTO saml_service_providers
           (sp_id, entity_id, acs_url, slo_url, name_id_format)
           VALUES (?, ?, ?, ?, ?)""",
        ("SP-001", "https://tripbiz-booking.local/saml/metadata",
         "http://127.0.0.1:5050/saml/acs",
         "http://127.0.0.1:5050/saml/slo",
         "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress")
    )
    conn.execute(
        """INSERT INTO saml_identity_providers
           (idp_id, entity_id, sso_url, slo_url)
           VALUES (?, ?, ?, ?)""",
        ("IDP-001", "https://idm-sre-lab.local/saml/idp-metadata",
         "http://127.0.0.1:5050/saml/idp/sso",
         "http://127.0.0.1:5050/saml/slo")
    )
    if verbose:
        print("[+] Seeded SAML SP-001 + IDP-001")

    conn.commit()
    return {
        "client_id": "tripbiz-booking-app",
        "client_secret": client_secret,
        "users": [{"user_id": u[0], "username": u[1], "password": u[4], "role": u[6]}
                  for u in users],
        "signing_kid": kid,
        "sp_entity_id": "https://tripbiz-booking.local/saml/metadata",
        "idp_entity_id": "https://idm-sre-lab.local/saml/idp-metadata",
    }


if __name__ == "__main__":
    print(seed_all(verbose=True))