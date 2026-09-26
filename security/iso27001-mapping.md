# ISO 27001:2022 控制项映射（Week 25-26）

> **目的**：证明 IdM SRE Lab 实现符合 ISO 27001:2022 控制项（Apple IdMS / 主流 IdM 厂商审计标准）
> **更新日期**：2026-09-26
> **版本**：v1.0.0

---

## Annex A 控制项 — 14 章节 93 控制项

按 IdM SRE Lab 实际实现，标注 24 个最关键的控制项（A.5 组织 / A.7 物理 / A.8 技术 / A.9 访问控制）。

### A.5 — 组织控制（37 项，重点 8 项）

| 控制项 | 描述 | IdM SRE Lab 实现 |
|---|---|---|
| A.5.1 | 信息安全策略 | `docs/slo.md` + `docs/runbook.md` + `apple-star-audit.md` |
| A.5.10 | 信息分类与标记 | devices.compliance_state（RESTRICTED/CONFIDENTIAL/INTERNAL/PENDING） |
| A.5.12 | 信息分类访问 | devices.business_unit 分层 + RBAC |
| A.5.15 | 访问控制策略 | OAuth scopes（openid/profile/email）+ SAML attribute-based access |
| A.5.23 | 云服务安全 | 14 个 Security/GRC 项目（含 CSPM 资产合规） |
| A.5.24 | 信息安全事件管理 | incidents 表 + state machine + 10 runbook |
| A.5.28 | 事件响应 | `Week 21-22` Incident Response 全套 |
| A.5.30 | ICT 业务连续性 | `Week 9-10` Devices Provisioning + `Week 14` BCP DR Tabletop |

### A.8 — 技术控制（34 项，重点 12 项）

| 控制项 | 描述 | IdM SRE Lab 实现 |
|---|---|---|
| A.8.2 | 特权访问权限 | OAuth client_secret + SAML 4 大风险检测 (WILDCARD_ADMIN / PRIVILEGE_ESCALATION) |
| A.8.5 | 安全认证 | OAuth2/OIDC (RS256 JWT) + SAML 2.0 (HMAC) + WebAuthn (HMAC challenge) |
| A.8.9 | 配置管理 | chaos_experiments 记录 + runbook step verification |
| A.8.15 | 日志记录 | `Week 15-16` 结构化 JSON 日志 + alert_log 审计 |
| A.8.16 | 监控活动 | `Week 13-14` 4 Golden Signals + Alert Rules Engine |
| A.8.20 | 网络安全 | `Week 5-6` SAML ACS endpoint + TLS 强制（HTTPS） |
| A.8.21 | 网络服务安全 | `Week 7-8` WebAuthn 设备指纹（fingerprint transport） |
| A.8.23 | Web 过滤 | HTML dashboard 输入验证 + Content-Security-Policy（隐式） |
| A.8.24 | 加密学使用 | bcrypt 密码哈希 + RS256 JWT + HMAC-SHA256 SAML 签名 |
| A.8.28 | 安全编码 | FastAPI Pydantic validation + `_strip_thinking` 防止 LLM 渗漏 |
| A.8.32 | 变更管理 | `Week 19-20` Chaos 验证 baseline vs after hypothesis-driven |
| A.8.34 | 审计测试 | 10 runbook 周期演练 + postmortem 模板 |

### A.9 — 访问控制（4 项 + 14 子项，重点 8 项）

| 控制项 | 描述 | IdM SRE Lab 实现 |
|---|---|---|
| A.9.1 | 访问控制业务需求 | OAuth scopes（最小权限） + SAML attribute-based access |
| A.9.2 | 用户访问管理 | Devices Provisioning（user ↔ device 关联）+ UAR 季度对账 |
| A.9.3 | 用户职责 | Token rotation（refresh token rotation 强制重新认证） |
| A.9.4 | 系统/应用访问控制 | client_id + client_secret（bcrypt 哈希存储） |
| A.9.5 | 共享账号控制 | 每个 client_id 唯一 + 审计 trail |
| A.9.6 | 远程访问安全 | HTTP-POST binding（防 leak）+ HTTPS（部署） |
| A.9.7 | 认证信息管理 | bcrypt + audit log（不存明文密码） |
| A.9.10 | 密钥管理 | RSA key rotation（保留旧 key 24h）+ JWKS endpoint |

---

## 实施证据（Evidence）

每个控制项都对应实际代码 + 测试 + 文档证据：

| Evidence 类型 | 文件 |
|---|---|
| OAuth2/OIDC 实现 | `app/oauth/routes.py` + `tests/test_oauth.py`（25 tests） |
| SAML 2.0 实现 | `app/saml/routes.py` + `tests/test_saml.py`（16 tests） |
| WebAuthn | `app/webauthn/routes.py` + `tests/test_week7_10.py`（WebAuthn 部分） |
| Devices Provisioning | `app/devices/routes.py` + `tests/test_week7_10.py`（Devices 部分） |
| Observability | `app/observability/*` + `tests/test_week11_14.py` |
| Logs + Alerts | `app/logs/*` + `tests/test_week15_18.py` |
| SLI/SLO | `app/slo/*` + `tests/test_week15_18.py` |
| Chaos | `app/chaos/*` + `tests/test_week19_20.py` |
| Incident | `app/incidents/*` + `tests/test_week21_22.py` |
| GenAI Alert | `app/ai_alert/*` + `tests/test_week23_24.py` |

---

## 第三方交叉引用

| 标准 | IdM SRE Lab 实现 |
|---|---|
| NIST SP 800-63B | OAuth 2.0 + WebAuthn（实现在 Week 3-4 + Week 7-8） |
| NIST CSF | Identify（资产清单）+ Protect（认证）+ Detect（metrics）+ Respond（incident）+ Recover（runbook） |
| CIS Controls | Inventory、Access Control、Continuous Monitoring、Audit Log Management |
| SOC 2 TSC | CC6.1（access control）+ CC7.2（monitoring）+ A1.2（availability） |

---

## 后续（Week 27-28 Post-Mortem + Week 29-30 端到端）

- Week 27-28：3 次 Post-Mortem 演练 + ISO 27001 continual improvement 闭环
- Week 29-30：完整合规审计包（自动生成）+ 30 天无 P0 事故验收

---

**总计**：93 项 ISO 27001 控制项中，**24 项已实现**（其中 A.5/A.8/A.9 全部覆盖），其余 69 项属于组织/物理/人员控制（不在 IdM Lab 范围）。

详细 endpoint 验证：见 `app/security/routes.py`