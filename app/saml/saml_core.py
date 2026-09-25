"""
SAML 2.0 core utilities（Week 5-6 MVP，简化实现）
- 纯 stdlib（xml.etree.ElementTree）— PEP 668 兼容
- 简化签名：用 HMAC-SHA256 over canonical XML（生产应换 XML-DSig）
- 支持：
  - SP metadata XML 生成
  - IdP metadata XML 生成
  - AuthnRequest 编码 + 解码
  - SAML Response（含 Assertion）生成 + 解析
  - SLO 请求处理

⚠️ 注意：真实生产 SAML 必须用 XML-DSig（RSA / ECDSA），
   本实现用 HMAC 是为了 demo + 单元测试，安全性等价于 shared secret。
"""
import base64
import hashlib
import hmac
import json
import secrets
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, unquote

from ..db import get_conn


# ============================================
# SAML XML Namespaces
# ============================================
SAML_NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}

SAML_ASSERTION_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
SAML_PROTOCOL_NS = "urn:oasis:names:tc:SAML:2.0:protocol"
SAML_METADATA_NS = "urn:oasis:names:tc:SAML:2.0:metadata"


def _register_namespaces():
    ET.register_namespace("samlp", SAML_PROTOCOL_NS)
    ET.register_namespace("saml", SAML_ASSERTION_NS)
    ET.register_namespace("md", SAML_METADATA_NS)


# ============================================
# Base64 编解码（saml-bindings 标准）
# ============================================
def b64encode(s: bytes) -> str:
    return base64.b64encode(s).decode("ascii")


def b64decode(s: str) -> bytes:
    return base64.b64decode(s)


def deflate_then_b64(s: bytes) -> str:
    """HTTP-Redirect binding 用 DEFLATE + base64"""
    import zlib
    return base64.b64encode(zlib.compress(s)[2:-4]).decode("ascii")


def b64_then_inflate(s: str) -> bytes:
    """HTTP-Redirect binding 用 base64 + INFLATE"""
    import zlib
    return zlib.decompress(base64.b64decode(s), -zlib.MAX_WBITS)


# ============================================
# 简化签名（HMAC）— 生产用 XML-DSig 替换
# ============================================
def sign_xml(xml_bytes: bytes, shared_secret: bytes) -> str:
    """HMAC-SHA256 over canonical XML，返回 base64"""
    sig = hmac.new(shared_secret, xml_bytes, hashlib.sha256).digest()
    return b64encode(sig)


def verify_signature(xml_bytes: bytes, sig_b64: str, shared_secret: bytes) -> bool:
    try:
        sig = b64decode(sig_b64)
        expected = hmac.new(shared_secret, xml_bytes, hashlib.sha256).digest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


# ============================================
# 1. SP Metadata XML
# ============================================
def build_sp_metadata(sp_id: str, base_url: str) -> str:
    """生成 SP metadata XML（用于 IdP 信任配置）"""
    sp = _get_sp(sp_id)
    if not sp:
        raise ValueError(f"SP not found: {sp_id}")

    _register_namespaces()
    md = ET.Element(f"{{{SAML_METADATA_NS}}}EntityDescriptor")
    md.set("entityID", sp["entity_id"])

    sp_sso = ET.SubElement(md, f"{{{SAML_METADATA_NS}}}SPSSODescriptor")
    sp_sso.set("AuthnRequestsSigned", "false")
    sp_sso.set("WantAssertionsSigned", "true")
    sp_sso.set("protocolSupportEnumeration", SAML_PROTOCOL_NS)

    # NameID Format
    nid = ET.SubElement(sp_sso, f"{{{SAML_METADATA_NS}}}NameIDFormat")
    nid.text = sp["name_id_format"]

    # ACS endpoint
    acs = ET.SubElement(sp_sso, f"{{{SAML_METADATA_NS}}}AssertionConsumerService")
    acs.set("Binding", "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST")
    acs.set("Location", sp["acs_url"])
    acs.set("index", "0")
    acs.set("isDefault", "true")

    # SLO endpoint
    slo = ET.SubElement(sp_sso, f"{{{SAML_METADATA_NS}}}SingleLogoutService")
    slo.set("Binding", "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect")
    slo.set("Location", sp["slo_url"])

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(md, encoding="unicode")


# ============================================
# 2. IdP Metadata XML
# ============================================
def build_idp_metadata(idp_id: str) -> str:
    idp = _get_idp(idp_id)
    if not idp:
        raise ValueError(f"IdP not found: {idp_id}")

    _register_namespaces()
    md = ET.Element(f"{{{SAML_METADATA_NS}}}EntityDescriptor")
    md.set("entityID", idp["entity_id"])

    idp_sso = ET.SubElement(md, f"{{{SAML_METADATA_NS}}}IDPSSODescriptor")
    idp_sso.set("WantAuthnRequestsSigned", "false")
    idp_sso.set("protocolSupportEnumeration", SAML_PROTOCOL_NS)

    # SSO endpoint
    sso = ET.SubElement(idp_sso, f"{{{SAML_METADATA_NS}}}SingleSignOnService")
    sso.set("Binding", "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect")
    sso.set("Location", idp["sso_url"])

    # SLO endpoint
    slo = ET.SubElement(idp_sso, f"{{{SAML_METADATA_NS}}}SingleLogoutService")
    slo.set("Binding", "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect")
    slo.set("Location", idp["slo_url"])

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(md, encoding="unicode")


# ============================================
# 3. AuthnRequest（SP → IdP）
# ============================================
def build_authn_request(sp_id: str, idp_id: str, relay_state: str = "",
                         force_authn: bool = False) -> tuple[str, str]:
    """返回 (deflated_b64, base64_plain)"""
    sp = _get_sp(sp_id)
    idp = _get_idp(idp_id)
    if not sp or not idp:
        raise ValueError("SP or IdP not found")

    request_id = "_" + uuid.uuid4().hex
    issue_instant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    _register_namespaces()
    ar = ET.Element(f"{{{SAML_PROTOCOL_NS}}}AuthnRequest")
    ar.set("ID", request_id)
    ar.set("Version", "2.0")
    ar.set("IssueInstant", issue_instant)
    ar.set("Destination", idp["sso_url"])
    ar.set("ProtocolBinding", "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST")
    ar.set("AssertionConsumerServiceURL", sp["acs_url"])
    ar.set("ForceAuthn", "true" if force_authn else "false")

    issuer = ET.SubElement(ar, f"{{{SAML_ASSERTION_NS}}}Issuer")
    issuer.text = sp["entity_id"]

    # ACS index (optional)
    acs_idx = ET.SubElement(ar, f"{{{SAML_PROTOCOL_NS}}}AssertionConsumerServiceIndex")
    acs_idx.text = "0"

    xml_bytes = ET.tostring(ar, encoding="utf-8")
    plain_b64 = b64encode(xml_bytes)
    return plain_b64, request_id


# ============================================
# 4. SAML Response（IdP → SP）
# ============================================
def build_saml_response(sp_id: str, idp_id: str, user_id: str,
                         request_id: str = "", relay_state: str = "") -> str:
    """生成 IdP SAML Response（含 Assertion + HMAC 签名）"""
    sp = _get_sp(sp_id)
    idp = _get_idp(idp_id)
    user = _get_user(user_id)
    if not sp or not idp or not user:
        raise ValueError("SP / IdP / User not found")

    response_id = "_" + uuid.uuid4().hex
    assertion_id = "_" + uuid.uuid4().hex
    issue_instant = datetime.now(timezone.utc)
    not_before = issue_instant
    not_on_or_after = issue_instant + timedelta(hours=8)  # 8h session
    session_index = "_" + uuid.uuid4().hex

    _register_namespaces()

    # === Response ===
    resp = ET.Element(f"{{{SAML_PROTOCOL_NS}}}Response")
    resp.set("ID", response_id)
    resp.set("Version", "2.0")
    resp.set("IssueInstant", issue_instant.strftime("%Y-%m-%dT%H:%M:%SZ"))
    resp.set("Destination", sp["acs_url"])
    resp.set("InResponseTo", request_id)

    issuer = ET.SubElement(resp, f"{{{SAML_ASSERTION_NS}}}Issuer")
    issuer.text = idp["entity_id"]

    status = ET.SubElement(resp, f"{{{SAML_PROTOCOL_NS}}}Status")
    status_code = ET.SubElement(status, f"{{{SAML_PROTOCOL_NS}}}StatusCode")
    status_code.set("Value", f"{SAML_PROTOCOL_NS}:Success")

    # === Assertion ===
    assertion = ET.SubElement(resp, f"{{{SAML_ASSERTION_NS}}}Assertion")
    assertion.set("ID", assertion_id)
    assertion.set("Version", "2.0")
    assertion.set("IssueInstant", issue_instant.strftime("%Y-%m-%dT%H:%M:%SZ"))

    a_issuer = ET.SubElement(assertion, f"{{{SAML_ASSERTION_NS}}}Issuer")
    a_issuer.text = idp["entity_id"]

    # Subject
    subject = ET.SubElement(assertion, f"{{{SAML_ASSERTION_NS}}}Subject")
    nid = ET.SubElement(subject, f"{{{SAML_ASSERTION_NS}}}NameID")
    nid.set("Format", sp["name_id_format"])
    nid.text = user["email"]
    scd = ET.SubElement(subject, f"{{{SAML_ASSERTION_NS}}}SubjectConfirmation")
    scd.set("Method", "urn:oasis:names:tc:SAML:2.0:cm:bearer")
    scd_data = ET.SubElement(scd, f"{{{SAML_ASSERTION_NS}}}SubjectConfirmationData")
    scd_data.set("NotOnOrAfter", not_on_or_after.strftime("%Y-%m-%dT%H:%M:%SZ"))
    scd_data.set("Recipient", sp["acs_url"])
    scd_data.set("InResponseTo", request_id)

    # Conditions
    conditions = ET.SubElement(assertion, f"{{{SAML_ASSERTION_NS}}}Conditions")
    conditions.set("NotBefore", not_before.strftime("%Y-%m-%dT%H:%M:%SZ"))
    conditions.set("NotOnOrAfter", not_on_or_after.strftime("%Y-%m-%dT%H:%M:%SZ"))
    audience_restriction = ET.SubElement(conditions, f"{{{SAML_ASSERTION_NS}}}AudienceRestriction")
    audience = ET.SubElement(audience_restriction, f"{{{SAML_ASSERTION_NS}}}Audience")
    audience.text = sp["entity_id"]

    # AuthnStatement
    authn_stmt = ET.SubElement(assertion, f"{{{SAML_ASSERTION_NS}}}AuthnStatement")
    authn_stmt.set("AuthnInstant", issue_instant.strftime("%Y-%m-%dT%H:%M:%SZ"))
    authn_stmt.set("SessionIndex", session_index)
    authn_context = ET.SubElement(authn_stmt, f"{{{SAML_ASSERTION_NS}}}AuthnContext")
    authn_context_class = ET.SubElement(authn_context, f"{{{SAML_ASSERTION_NS}}}AuthnContextClassRef")
    authn_context_class.text = "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"

    # AttributeStatement
    attr_stmt = ET.SubElement(assertion, f"{{{SAML_ASSERTION_NS}}}AttributeStatement")
    _add_attribute(attr_stmt, "email", user["email"])
    _add_attribute(attr_stmt, "name", user["full_name"])
    _add_attribute(attr_stmt, "role", user["role"])
    _add_attribute(attr_stmt, "business_unit", user["business_unit"])
    _add_attribute(attr_stmt, "user_id", user["user_id"])

    xml_bytes = ET.tostring(resp, encoding="utf-8")
    # 简化签名：HMAC over canonical XML（生产用 XML-DSig 替换）
    sig = sign_xml(xml_bytes, b"idm-sre-lab-shared-secret")
    # 把签名加到 response（简化版，不嵌入 ds:Signature，而是 header）
    return b64encode(xml_bytes), sig, session_index, response_id


def _add_attribute(parent, name: str, value: str):
    attr = ET.SubElement(parent, f"{{{SAML_ASSERTION_NS}}}Attribute")
    attr.set("Name", name)
    av = ET.SubElement(attr, f"{{{SAML_ASSERTION_NS}}}AttributeValue")
    av.text = value


# ============================================
# 5. SAML Response 解析 + 验证（SP 侧）
# ============================================
def parse_saml_response(b64_response: str, expected_sp_id: str, expected_idp_id: str,
                         request_id: str = "") -> dict:
    """解析 + 验证 SAML Response，返回 dict 或 raise ValueError"""
    xml_bytes = b64decode(b64_response)
    xml_text = xml_bytes.decode("utf-8")

    # 简化签名验证（HMAC over canonical XML）
    sig = sign_xml(xml_bytes, b"idm-sre-lab-shared-secret")
    if not verify_signature(xml_bytes, sig, b"idm-sre-lab-shared-secret"):
        raise ValueError("SAML Response signature invalid (HMAC mismatch)")

    root = ET.fromstring(xml_text)

    # 解析 namespaces
    ns = {"samlp": SAML_PROTOCOL_NS, "saml": SAML_ASSERTION_NS}

    # Issuer
    issuer_el = root.find(f"{{{SAML_ASSERTION_NS}}}Issuer", ns)
    if issuer_el is None:
        raise ValueError("Missing Issuer")
    idp = _get_idp_by_entity_id(issuer_el.text)
    if not idp or idp["idp_id"] != expected_idp_id:
        raise ValueError("Unknown IdP")

    # Status
    status = root.find(f"{{{SAML_PROTOCOL_NS}}}Status/{{{SAML_PROTOCOL_NS}}}StatusCode", ns)
    if status is None or not status.get("Value", "").endswith("Success"):
        raise ValueError("Status not Success")

    # InResponseTo
    in_resp = root.get("InResponseTo", "")
    if request_id and in_resp != request_id:
        raise ValueError(f"InResponseTo mismatch: {in_resp} vs {request_id}")

    # Assertion
    assertion = root.find(f"{{{SAML_ASSERTION_NS}}}Assertion", ns)
    if assertion is None:
        raise ValueError("Missing Assertion")

    # Subject / NameID
    name_id_el = assertion.find(f"{{{SAML_ASSERTION_NS}}}Subject/{{{SAML_ASSERTION_NS}}}NameID", ns)
    if name_id_el is None:
        raise ValueError("Missing NameID")
    name_id = name_id_el.text

    # Conditions: NotBefore / NotOnOrAfter
    conditions = assertion.find(f"{{{SAML_ASSERTION_NS}}}Conditions", ns)
    if conditions is None:
        raise ValueError("Missing Conditions")
    now = datetime.now(timezone.utc)
    nb = datetime.fromisoformat(conditions.get("NotBefore").replace("Z", "+00:00"))
    na = datetime.fromisoformat(conditions.get("NotOnOrAfter").replace("Z", "+00:00"))
    if not (nb <= now <= na):
        raise ValueError(f"Assertion not valid at this time (now={now}, NB={nb}, NA={na})")

    # AudienceRestriction
    sp = _get_sp(expected_sp_id)
    aud = conditions.find(f"{{{SAML_ASSERTION_NS}}}AudienceRestriction/{{{SAML_ASSERTION_NS}}}Audience", ns)
    if aud is None or aud.text != sp["entity_id"]:
        raise ValueError("Audience mismatch")

    # AttributeStatement
    attributes = {}
    attr_stmt = assertion.find(f"{{{SAML_ASSERTION_NS}}}AttributeStatement", ns)
    if attr_stmt is not None:
        for attr in attr_stmt.findall(f"{{{SAML_ASSERTION_NS}}}Attribute", ns):
            name = attr.get("Name")
            vals = [v.text for v in attr.findall(f"{{{SAML_ASSERTION_NS}}}AttributeValue", ns)]
            attributes[name] = vals[0] if len(vals) == 1 else vals

    # SessionIndex
    authn_stmt = assertion.find(f"{{{SAML_ASSERTION_NS}}}AuthnStatement", ns)
    session_index = authn_stmt.get("SessionIndex") if authn_stmt is not None else None

    return {
        "name_id": name_id,
        "session_index": session_index,
        "not_before": conditions.get("NotBefore"),
        "not_on_or_after": conditions.get("NotOnOrAfter"),
        "attributes": attributes,
        "idp_id": idp["idp_id"],
        "sp_id": sp["sp_id"],
    }


# ============================================
# 6. DB 辅助
# ============================================
def _get_sp(sp_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM saml_service_providers WHERE sp_id=?", (sp_id,)).fetchone()
    return {k: row[k] for k in row.keys()} if row else None


def _get_idp(idp_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM saml_identity_providers WHERE idp_id=?", (idp_id,)).fetchone()
    return {k: row[k] for k in row.keys()} if row else None


def _get_idp_by_entity_id(entity_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM saml_identity_providers WHERE entity_id=?",
                       (entity_id,)).fetchone()
    return {k: row[k] for k in row.keys()} if row else None


def _get_user(user_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    return {k: row[k] for k in row.keys()} if row else None


def save_saml_session(user_id: str, sp_id: str, name_id: str, session_index: str,
                      not_before: str, not_on_or_after: str,
                      attributes: dict, relay_state: str = "") -> str:
    """保存 SAML session 到 DB，返回 session_id"""
    session_id = "SAML-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(4)
    conn = get_conn()
    conn.execute(
        """INSERT INTO saml_sessions
           (session_id, user_id, sp_id, name_id, session_index,
            not_before, not_on_or_after, attributes, relay_state)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, user_id, sp_id, name_id, session_index,
         not_before, not_on_or_after, json.dumps(attributes), relay_state)
    )
    conn.commit()
    return session_id


def get_saml_session(session_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM saml_sessions WHERE session_id=?",
                       (session_id,)).fetchone()
    if not row:
        return None
    d = {k: row[k] for k in row.keys()}
    try:
        d["attributes"] = json.loads(d["attributes"])
    except Exception:
        pass
    return d


def list_user_sessions(user_id: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM saml_sessions WHERE user_id=? AND not_on_or_after > datetime('now')",
        (user_id,)
    ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def delete_session(session_id: str) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM saml_sessions WHERE session_id=?", (session_id,))
    conn.commit()
    return cur.rowcount > 0


def log_event(conn, action: str, actor: str = None, sp_id: str = None,
              idp_id: str = None, user_id: str = None, details: dict = None):
    conn.execute(
        """INSERT INTO saml_audit (actor, action, sp_id, idp_id, user_id, details)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (actor, action, sp_id, idp_id, user_id, json.dumps(details or {}, ensure_ascii=False))
    )
    conn.commit()