-- IdM SRE Lab - SQLite schema (Week 3-4 MVP)
-- OAuth2 / OIDC MVP：users + clients + authorization_codes + tokens + JWKS

-- ============================================
-- OAuth2 Clients（client_id + secret）
-- ============================================
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id         TEXT PRIMARY KEY,
    client_secret     TEXT NOT NULL,                       -- bcrypt hash
    client_name       TEXT NOT NULL,
    redirect_uris     TEXT NOT NULL,                        -- JSON list
    grant_types       TEXT NOT NULL DEFAULT '["authorization_code","refresh_token"]',
    scopes            TEXT NOT NULL DEFAULT '["openid","profile","email"]',
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================
-- Users（克诺尔 BU mock user store）
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    user_id        TEXT PRIMARY KEY,                        -- USER-001
    username       TEXT NOT NULL UNIQUE,                    -- login name
    email          TEXT NOT NULL UNIQUE,
    full_name      TEXT NOT NULL,
    password_hash  TEXT NOT NULL,                           -- bcrypt hash
    business_unit  TEXT NOT NULL DEFAULT 'platform',
    role           TEXT NOT NULL DEFAULT 'employee',       -- employee / it_admin / bu_lead
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_user_username ON users(username);

-- ============================================
-- Authorization Codes（短期）
-- ============================================
CREATE TABLE IF NOT EXISTS authorization_codes (
    code              TEXT PRIMARY KEY,
    client_id         TEXT NOT NULL,
    user_id           TEXT NOT NULL,
    redirect_uri      TEXT NOT NULL,
    scope             TEXT NOT NULL,
    code_challenge    TEXT,                                 -- PKCE
    code_challenge_method TEXT,                             -- S256 / plain
    expires_at        TEXT NOT NULL,
    consumed          INTEGER NOT NULL DEFAULT 0,           -- 0/1
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (client_id) REFERENCES oauth_clients(client_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_ac_expires ON authorization_codes(expires_at);

-- ============================================
-- Tokens（access + refresh）
-- ============================================
CREATE TABLE IF NOT EXISTS tokens (
    token_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    jti             TEXT NOT NULL UNIQUE,                   -- JWT ID
    client_id       TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    token_type      TEXT NOT NULL,                          -- access / refresh
    scope           TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    revoked         INTEGER NOT NULL DEFAULT 0,             -- 0/1
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (client_id) REFERENCES oauth_clients(client_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_token_jti ON tokens(jti);
CREATE INDEX IF NOT EXISTS idx_token_user ON tokens(user_id);

-- ============================================
-- RSA Keys（用于 JWT RS256 签名）
-- ============================================
CREATE TABLE IF NOT EXISTS rsa_keys (
    kid             TEXT PRIMARY KEY,                       -- Key ID
    algorithm       TEXT NOT NULL DEFAULT 'RS256',
    private_pem     TEXT NOT NULL,                          -- PEM 格式（实际生产用 KMS）
    public_jwk      TEXT NOT NULL,                          -- JWK JSON
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    active          INTEGER NOT NULL DEFAULT 1              -- 0/1（jwks endpoint 只返回 active=1）
);

-- ============================================
-- Audit trail（OAuth 事件）
-- ============================================
CREATE TABLE IF NOT EXISTS oauth_audit (
    audit_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    actor           TEXT,
    action          TEXT NOT NULL,                          -- token_issued / token_revoked / auth_code_issued / login_success / login_fail
    client_id       TEXT,
    user_id         TEXT,
    details         TEXT,
    occurred_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_action ON oauth_audit(action);
-- ============================================
-- SAML 2.0 Service Providers（Week 5-6）
-- ============================================
CREATE TABLE IF NOT EXISTS saml_service_providers (
    sp_id            TEXT PRIMARY KEY,                       -- SP-001
    entity_id        TEXT NOT NULL UNIQUE,                   -- https://app.example.com/saml/metadata
    acs_url          TEXT NOT NULL,                          -- Assertion Consumer Service
    slo_url          TEXT NOT NULL,
    name_id_format   TEXT NOT NULL DEFAULT 'urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress',
    signing_key_id   TEXT,                                   -- 哪个 RSA key 用来签名/验证
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================
-- SAML Identity Providers（自建 IdP 演示用）
-- ============================================
CREATE TABLE IF NOT EXISTS saml_identity_providers (
    idp_id           TEXT PRIMARY KEY,                       -- IDP-001
    entity_id        TEXT NOT NULL UNIQUE,
    sso_url          TEXT NOT NULL,                          -- IdP-initiated SSO URL
    slo_url          TEXT NOT NULL,
    signing_key_id   TEXT,                                   -- RSA key 用于签名 Assertion
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================
-- SAML Sessions（持久化登录状态）
-- ============================================
CREATE TABLE IF NOT EXISTS saml_sessions (
    session_id       TEXT PRIMARY KEY,                       -- SAML-{ts}-{rand}
    user_id          TEXT NOT NULL,
    sp_id            TEXT NOT NULL,
    name_id          TEXT NOT NULL,                          -- SAML NameID (typically email)
    session_index    TEXT NOT NULL,
    not_before       TEXT NOT NULL,
    not_on_or_after  TEXT NOT NULL,
    attributes       TEXT NOT NULL,                          -- JSON: {email, role, business_unit}
    relay_state      TEXT,                                   -- SP 原始请求页面
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (sp_id) REFERENCES saml_service_providers(sp_id)
);

CREATE INDEX IF NOT EXISTS idx_saml_session_user ON saml_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_saml_session_index ON saml_sessions(session_index);

-- ============================================
-- SAML Audit
-- ============================================
CREATE TABLE IF NOT EXISTS saml_audit (
    audit_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    actor            TEXT,
    action           TEXT NOT NULL,                          -- authn_request / assertion_issued / sso_completed / slo_requested / slo_completed
    sp_id            TEXT,
    idp_id           TEXT,
    user_id          TEXT,
    details          TEXT,
    occurred_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_saml_audit_action ON saml_audit(action);

-- ============================================
-- WebAuthn / FIDO2 Credentials（Week 7-8）
-- 简化版：用 HMAC-SHA256 challenge-response（生产换 py_webauthn + CBOR）
-- ============================================
CREATE TABLE IF NOT EXISTS webauthn_credentials (
    credential_id   TEXT PRIMARY KEY,                       -- base64url encoded
    user_id         TEXT NOT NULL,
    public_key      TEXT NOT NULL,                          -- base64(HMAC demo key) or real COSE pubkey
    counter         INTEGER NOT NULL DEFAULT 0,
    aaguid          TEXT,                                   -- Authenticator Attestation GUID (mock)
    transports      TEXT,                                   -- JSON list: ["usb","nfc","ble","internal"]
    friendly_name   TEXT,                                   -- "YubiKey 5C", "Touch ID"
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at    TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_webauthn_user ON webauthn_credentials(user_id);

-- ============================================
-- WebAuthn Challenges（短期挑战码）
-- ============================================
CREATE TABLE IF NOT EXISTS webauthn_challenges (
    challenge       TEXT PRIMARY KEY,                       -- random 32 bytes base64url
    user_id         TEXT,                                   -- NULL for register-less flows
    purpose         TEXT NOT NULL,                          -- 'register' / 'authenticate'
    expires_at      TEXT NOT NULL,
    consumed        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_webauthn_chal_expires ON webauthn_challenges(expires_at);

-- ============================================
-- Device Provisioning（Week 9-10：克诺尔 BU 场景）
-- ============================================
CREATE TABLE IF NOT EXISTS devices (
    device_id        TEXT PRIMARY KEY,                      -- DEV-001
    device_name      TEXT NOT NULL,                         -- "李工 ThinkPad T14"
    user_id          TEXT NOT NULL,                         -- 关联 user
    device_type      TEXT NOT NULL,                         -- LAPTOP / DESKTOP / TABLET / PHONE / IOT
    os               TEXT NOT NULL,                         -- "Windows 11 Pro", "macOS 14"
    serial_number    TEXT NOT NULL UNIQUE,
    manufacturer     TEXT,                                  -- Lenovo / Apple / Dell
    model            TEXT,
    status           TEXT NOT NULL DEFAULT 'REGISTERED',   -- REGISTERED / ACTIVE / RETIRED / LOST
    compliance_state TEXT NOT NULL DEFAULT 'PENDING',      -- PENDING / COMPLIANT / NON_COMPLIANT
    business_unit    TEXT NOT NULL DEFAULT 'platform',
    registered_at    TEXT NOT NULL DEFAULT (datetime('now')),
    activated_at     TEXT,
    retired_at       TEXT,
    last_check_in   TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_device_user ON devices(user_id);
CREATE INDEX IF NOT EXISTS idx_device_status ON devices(status);
CREATE INDEX IF NOT EXISTS idx_device_bu ON devices(business_unit);

-- ============================================
-- Device Audit（设备生命周期事件）
-- ============================================
CREATE TABLE IF NOT EXISTS device_audit (
    audit_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    actor           TEXT,
    action          TEXT NOT NULL,                          -- device_registered / device_activated / device_retired / device_compliance_changed
    device_id       TEXT,
    user_id         TEXT,
    details         TEXT,
    occurred_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================
-- WebAuthn Audit（Week 7-8 补充）
-- ============================================
CREATE TABLE IF NOT EXISTS webauthn_audit (
    audit_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    actor           TEXT,
    action          TEXT NOT NULL,                          -- register_begin / register_finish / authenticate_begin / authenticate_finish / delete_credential
    credential_id   TEXT,
    user_id         TEXT,
    details         TEXT,
    occurred_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_webauthn_audit_action ON webauthn_audit(action);

-- ============================================
-- Chaos Engineering 实验（Week 19-20）
-- ============================================
CREATE TABLE IF NOT EXISTS chaos_experiments (
    experiment_id    TEXT PRIMARY KEY,                       -- CHAOS-{ts}
    experiment_type  TEXT NOT NULL,                          -- pod_kill / network_partition / latency_injection
    target_service   TEXT NOT NULL,                          -- token-issuer / saml-issuer / oauth-authorize
    duration_seconds INTEGER NOT NULL,
    hypothesis       TEXT NOT NULL,                          -- 假设："SLO 不超过 baseline X%"
    baseline_metrics TEXT,                                   -- JSON snapshot of pre-experiment metrics
    during_metrics   TEXT,                                   -- JSON snapshot during experiment
    after_metrics     TEXT,                                   -- JSON snapshot after experiment
    status           TEXT NOT NULL DEFAULT 'PENDING',        -- PENDING / RUNNING / COMPLETED / ABORTED
    verdict          TEXT NOT NULL DEFAULT 'UNKNOWN',        -- PASSED / FAILED / UNKNOWN
    notes            TEXT,
    started_at       TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_chaos_status ON chaos_experiments(status);
CREATE INDEX IF NOT EXISTS idx_chaos_type ON chaos_experiments(experiment_type);

-- ============================================
-- Incident Response（Week 21-22）
-- ============================================
CREATE TABLE IF NOT EXISTS incidents (
    incident_id       TEXT PRIMARY KEY,                       -- INC-{ts}
    incident_type     TEXT NOT NULL,                          -- latency_spike / auth_fail / memory_leak / etc.
    severity          TEXT NOT NULL,                          -- SEV-1 / SEV-2 / SEV-3
    title             TEXT NOT NULL,
    description       TEXT,
    status            TEXT NOT NULL DEFAULT 'ACTIVE',         -- ACTIVE / INVESTIGATING / MITIGATED / RESOLVED / POSTMORTEM
    triggered_at      TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at       TEXT,
    mitigation        TEXT,                                  -- 具体 mitigation 动作
    lessons_learned   TEXT,
    runbook_ref       TEXT                                   -- 对应 runbook 章节
);

CREATE INDEX IF NOT EXISTS idx_inc_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_inc_type ON incidents(incident_type);
