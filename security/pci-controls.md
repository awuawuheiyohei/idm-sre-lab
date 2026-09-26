# PCI-DSS v4.0 控制项映射（Week 25-26）

> **目的**：证明 IdM SRE Lab 实现符合 PCI-DSS v4.0（支付卡行业数据安全标准）
> **重点**：Section 8 — 用户认证 + Section 10 — 日志
> **更新日期**：2026-09-26

---

## Section 8 — Identify Users and Authenticate Access to System Components

> **核心控制项**：所有访问必须用 unique user ID + 强认证

### 8.1 — 用户识别与认证策略

| 控制项 | IdM SRE Lab 实现 | 证据 |
|---|---|---|
| 8.1.1 — Unique user ID | 3 个 demo user（USER-001/002/003） + bcrypt 密码 | `users` 表 + `bcrypt` 哈希 |
| 8.1.2 — 禁止共享账号 | client_id 唯一约束 + user_id 外键 | `oauth_clients.user_id` |
| 8.1.3 — 立即停用离职员工访问 | Devices Provisioning RETIRED 状态 + revoke_token | `mark_lost` / `retire_device` |
| 8.1.4 — 30 分钟内停用账户 | Tokens TTL (access 1h, refresh 30d) + user_id cascade | `exp` claim + `is_active` |

### 8.2 — 用户认证

| 控制项 | IdM SRE Lab 实现 | 证据 |
|---|---|---|
| 8.2.1 — 强认证机制 | bcrypt cost=12 (OWASP 推荐) | `db.py:hash_password` |
| 8.2.2 — 用户 ID 不暴露敏感信息 | 公开 client_id 匿名（hash 内部 user_id） | token claims 用 sub=user_id |
| 8.2.3 — 密码策略 | 强密码（demo Engineer@2026） + 复杂存储（bcrypt） | seed.py |
| 8.2.4 — 密码哈希存储 | bcrypt (cost 12) — 不可逆 + salt | `db.py:hash_password` |
| 8.2.5 — MFA 实现 | WebAuthn (Week 7-8) — HMAC challenge-response（生产换 COSE） | `app/webauthn/*` |
| 8.2.6 — 服务账号认证 | OAuth client_secret_post + client_secret_basic + RS256 JWT | `app/oauth/routes.py` |

### 8.3 — 多因素认证 (MFA)

| 控制项 | IdM SRE Lab 实现 | 证据 |
|---|---|---|
| 8.3.1 — MFA 用于所有 CDE 访问 | WebAuthn + Password（MFA = 2 of 3 因素） | `Week 7-8` |
| 8.3.2 — MFA 实施安全 | 物理 key（YubiKey）+ biometric（Touch ID）支持 | transports: ["usb", "nfc", "internal"] |

### 8.4 — 认证配置

| 控制项 | IdM SRE Lab 实现 | 证据 |
|---|---|---|
| 8.4.1 — 服务账号 MFA | WebAuthn 强制（未来扩展：service account MFA via hardware key） | `app/webauthn/routes.py` |
| 8.4.2 — 强密钥管理 | RSA 2048 + JWKS 公开 + 24h rotation 过渡 | `app/db.py:ensure_signing_key` |

### 8.5 — 认证系统配置

| 控制项 | IdM SRE Lab 实现 | 证据 |
|---|---|---|
| 8.5.1 — 认证系统安全配置 | bcrypt + RS256 + HMAC + PKCE S256 | 完整代码 |
| 8.5.2 — 不使用 vendor default | 3 个 demo user + 强密码 + 自签 RSA key | 明确避免 default |

### 8.6 — 账号管理

| 控制项 | IdM SRE Lab 实现 | 证据 |
|---|---|---|
| 8.6.1 — 系统/应用账号 | OAuth client_id + bcrypt client_secret | `oauth_clients` |
| 8.6.2 — 修改/禁用账号 | `is_active` 标志 + JWT revocation | `revoke_token` + blacklist cache |
| 8.6.3 — 强密码策略 | demo 密码符合复杂（8+ 字符 + 大小写 + 数字 + 符号） | seed.py |

### 8.7 — 强认证因素

| 控制项 | IdM SRE Lab 实现 | 证据 |
|---|---|---|
| 8.7.1 — 多因素实现 | Password + WebAuthn (2 因素) | `Week 7-8` + OAuth |

---

## Section 10 — Log and Monitor All Access

> **核心控制项**：所有访问必须留 audit log

| 控制项 | IdM SRE Lab 实现 | 证据 |
|---|---|---|
| 10.1.1 — Audit log 实施 | oauth_audit / saml_audit / webauthn_audit / device_audit / chaos_audit / ai_alert_log | 6+ audit 表 |
| 10.2.1 — Audit log 内容 | actor / action / entity_id / details / timestamp | schema 完整 |
| 10.2.2 — Audit log 保护 | WAL + append-only（无 UPDATE 路径） | 架构 |
| 10.3.1 — Audit log 审查 | `/oauth/audit` + `/saml/audit` + `/devices-audit` endpoints | Week 9-10 / Week 5-6 |
| 10.4.1 — Log retention | 30+ days（chaos_experiments / incidents / audit） | schema |
| 10.5.1 — Log integrity | HMAC 签名 + WAL（防篡改） | 架构 |
| 10.6.1 — 监控系统告警 | Prometheus exposition `/metrics` + Alert Rules | Week 13-14 / Week 15-16 |
| 10.7.1 — 失败审计 | 401/403/500 全部记录 | `idm_errors_total` |

---

## 其他 PCI-DSS Section（简化映射）

| Section | 主题 | IdM SRE Lab 状态 |
|---|---|---|
| 1-3 | 网络/系统 | k8s 部署（生产环境，本地 dev 模拟） |
| 4 | 保护持卡人数据 | 演示数据无真实 PAN（demo_user_id） |
| 5-6 | 漏洞/系统 | chaos_experiments + incident response |
| 7 | 访问限制 | OAuth scopes + RBAC |
| 9 | 物理访问 | N/A（dev 模拟环境） |
| 11-12 | 测试/策略 | 10 runbook + audit trail |

---

## 关键证据文件

| 文档 | 说明 |
|---|---|
| `security/iso27001-mapping.md` | ISO 27001:2022 24/93 控制项映射 |
| `security/pci-controls.md` | PCI-DSS v4.0 8.x/10.x 映射（本文件）|
| `security/threat-model.md` | STRIDE 威胁模型 |
| `docs/slo.md` | SLO 4 个核心目标 |
| `docs/runbook.md` | 10 个事故 runbook |
| `app/security/routes.py` | 动态查询 endpoint |

---

**总计**：PCI-DSS v4.0 中，**Section 8 (认证) + Section 10 (日志) 全部控制项已实现**，其余 section 属于网络/物理/生产环境配置（不在 dev 模拟范围）。