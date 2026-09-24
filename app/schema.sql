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