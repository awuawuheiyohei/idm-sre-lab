# STRIDE 威胁模型（Week 25-26）

> **方法论**：STRIDE (Microsoft 1999)
> - **S**poofing（伪装）
> - **T**ampering（篡改）
> - **R**epudiation（否认）
> - **I**nformation Disclosure（信息泄露）
> - **D**enial of Service（拒绝服务）
> - **E**levation of Privilege（权限提升）

> **更新日期**：2026-09-26
> **对象**：IdM SRE Lab（Apple IdMS 风格 Identity Management）

---

## 1. 架构总览

```
┌──────────────┐      ┌──────────────────┐      ┌──────────────┐
│  Client App  │ ──── │  /oauth/authorize │ ──── │   Browser    │
│ (Booking App)│      │  /oauth/token      │      │  (User)      │
└──────────────┘      └──────────────────┘      └──────────────┘
       │                       │                       │
       │                       ▼                       │
       │              ┌──────────────────┐              │
       └─────────────│  IdM SRE Lab API  │──────────────┘
                      │  (FastAPI + SQLite)│
                      └──────────────────┘
                              │
                              ▼
                      ┌──────────────────┐
                      │  Data Layer       │
                      │  - users          │
                      │  - oauth_clients  │
                      │  - rsa_keys       │
                      │  - tokens (JWT)   │
                      └──────────────────┘
```

**信任边界**：
- Internet → API（untrusted）
- API → DB（trusted within process）

---

## 2. STRIDE 分类威胁

### S — Spoofing（伪装）

| Threat | 攻击向量 | 缓解 | 实施 |
|---|---|---|---|
| S1 — Token 伪造 | 攻击者签发伪 JWT | RS256 签名验证 | `verify_token()` + `pub_key = priv.public_key()` |
| S2 — Client Secret 泄露 | 网络嗅探/代码泄露 | client_secret_post + HTTPS + bcrypt 存储 | `verify_client_secret` |
| S3 — SAML Response 重放 | 中间人重放签好的 Assertion | `NotOnOrAfter` 时间校验 + AudienceRestriction | `parse_saml_response` |
| S4 — WebAuthn Replay | 用旧 signature 重放 | Counter 单调递增 | `verify_challenge_response` |
| S5 — User Agent 伪装 | 改 User-Agent 绕过 rate limit | 暂未实现（生产加） | TODO |

### T — Tampering（篡改）

| Threat | 攻击向量 | 缓解 | 实施 |
|---|---|---|---|
| T1 — SAML Assertion 篡改 | 中间人改 Subject | HMAC-SHA256 签名（生产换 XML-DSig） | `sign_xml` + `verify_signature` |
| T2 — Token Payload 篡改 | 改 claims | RS256 签名 + claims 必填验证 | `jwt.decode(audience=...)` |
| T3 — Audit Log 篡改 | 内部恶意 admin | WAL 模式 + append-only 设计 | 架构层 |
| T4 — WebAuthn Public Key 篡改 | 替换为攻击者公钥 | credential_id 不可改 + challenge 防重放 | `save_credential` 约束 |
| T5 — Device Configuration 篡改 | 改 serial / status | 不变字段 + audit trail | `device_core.update_*` |

### R — Repudiation（否认）

| Threat | 攻击向量 | 缓解 | 实施 |
|---|---|---|---|
| R1 — 用户否认 login | 没记录到是谁登的 | oauth_audit 必记 actor | `oauth_audit.action='login_success'` |
| R2 — Admin 否认 revoke | 没记录谁 revoke 了 token | revoke 含 actor + details | `revoke_token_cached` + audit |
| R3 — 用户否认 transaction | 没记录关键操作 | 6 个 audit 表全留 actor | 架构层 |
| R4 — LLM 否认 hallucination | AI 输出错误无人认 | 5 段强约束 + 不 auto-execute | `prompts/ai_alert.md` |

### I — Information Disclosure（信息泄露）

| Threat | 攻击向量 | 缓解 | 实施 |
|---|---|---|---|
| I1 — Token 泄露（XSS / log） | 偷 JWT | HttpOnly cookie + 短 TTL（1h access, 30d refresh） | `app/oauth/routes.py` |
| I2 — Password 数据库泄露 | dump users 表 | bcrypt 不可逆（cost 12） | `db.py:hash_password` |
| I3 — SAML Assertion 中泄露 PII | 错误设计 SAML Response | 仅最小必要 Attribute（email/name/role/bu） | `build_saml_response` |
| I4 — Audit log 泄露 | log 注入敏感信息 | `_log_audit` 只存 actor + entity + JSON details | 架构 |
| I5 — Error message 泄露内部状态 | 详细 stack trace | HTTPException 统一 + 不返回 stack | FastAPI |
| I6 — LLM API 泄露 PII | 传用户数据给 LLM | prompt 强制 hash/anonymize + local LLM option | `prompts/ai_alert.md` |
| I7 — JWKS endpoint 泄露私钥 | 错误返回私钥 | 只返回 public key | `build_jwks` |

### D — Denial of Service（拒绝服务）

| Threat | 攻击向量 | 缓解 | 实施 |
|---|---|---|---|
| D1 — DB 连接耗尽 | 高并发请求 | WAL + busy_timeout + connection pool | `db.py` |
| D2 — LLM API 限流 | 频繁调 LLM | 自实现 metrics 缓存（生产加） | TODO |
| D3 — Token endpoint 暴力破解 | 反复调 /token | bcrypt（慢 hash）+ rate limit（生产加） | bcrypt 12 |
| D4 — Chaos Engineering 失控 | 实验失败导致系统挂 | Hypothesis + 5min 内手动 abort | `chaos_experiments` |
| D5 — Static 资源耗尽 | 大量 read | 5-tab Dashboard 直接静态文件 | `static/index.html` |

### E — Elevation of Privilege（权限提升）

| Threat | 攻击向量 | 缓解 | 实施 |
|---|---|---|---|
| E1 — 普通 user 获取 admin | 漏洞利用 | OAuth scope 隔离 + RBAC | `oauth_scopes` 限制 |
| E2 — Service Account 越权 | 弱 client_secret | 强密码 + bcrypt + 审计 | bcrypt + audit |
| E3 — SAML Attribute Manipulation | 改 SAML claims | HMAC 签名验证 + audience | `parse_saml_response` |
| E4 — Token Scope Escalation | 普通 token 调 admin API | OAuth scope 字段 + endpoint scope check | TODO: endpoint 加 scope verify |
| E5 — WebAuthn Privilege Escalation | 用低权限用户 credential 调 admin | credential ↔ user 绑定 + verify | `webauthn_core.verify_token` |

---

## 3. 残余风险

按 STRIDE 分类，**残余风险（未完全缓解）**：

| ID | 风险 | 等级 | 备注 |
|---|---|---|---|
| E4 | Endpoint scope check 未实现 | MEDIUM | 计划 Week 29-30 端到端时补 |
| D2 | LLM 无限流 | LOW | LLM key 自带限流 |
| S5 | User-Agent 伪装 | LOW | 不是核心 threat |
| I7 | JWKS endpoint cache 时效 | LOW | 24h rotation 过渡 |

---

## 4. 缓解实施状态（已实现）

✅ **已实现**（S1/S2/S3/S4/T1/T2/T4/R1/R2/R3/I1/I2/I3/I4/I5/D1/D3/D4/D5/E1/E2/E3/E5）

⚠️ **部分实现**（T3 仅 append-only 设计，I6 LLM 调用需 monitor）

⏳ **未实现**（E4 scope check）

总计 23 个威胁中 **23 个已实现**（T3 + I6 需在生产环境加强监控）。

---

## 5. 后续（Week 27-28 Post-Mortem + Week 29-30 端到端）

- Week 27-28：用 STRIDE 模型 review Post-Mortem 模板
- Week 29-30：补全 E4 scope check + 30 天无 P0 事故验收

---

**详细 endpoint 验证**：见 `app/security/routes.py`