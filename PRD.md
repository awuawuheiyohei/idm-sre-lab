# IdM SRE Lab — PRD

> **一句话**：自建一套 Apple IdMS 风格的 Identity Management 平台（OAuth2/OIDC + SAML 2.0 + WebAuthn），配套完整 SRE 实践（SLI/SLO/observability/chaos/on-call）—— 5-6 个月完成，**真实能跑 + 真有事故响应 runbook**。
> **核心目的**：跨过 Apple IdMS SRE JD 的"5+ 年 SRE"硬门槛，并准备 Microsoft Identity / Google Cloud Identity / Okta 等同类岗位。

---

## 🎯 用户

我自己——目标转岗 SRE（从 IT 运维 + 安全审计）。
**目标公司类型**：IdM/Auth0/SSO 类（Apple IdMS / Microsoft Entra ID / Okta / Auth0 / Cloudflare Access）。

**用户匹配背景**（已有的优势）：
- ✅ Intune MDM + Azure AD 集成经验（克诺尔轨交 + 商用车 BU）
- ✅ ISO 27001 审计（合规已懂）
- ✅ vmodel-pipeline（Tekton CI/CD + Argo CD + Helm IaC，**完整 SRE 元素**）
- ✅ Python（5+ 项目实操）
- ✅ 4 个 LLM 项目（GenAI 告警工程）
- ❌ **缺**：5+ 年 SRE 直接经验、SLI/SLO 实战、chaos engineering

---

## 📥 输入

### 1. 用户认证请求

```yaml
# OAuth2 / OIDC 流程
client_id: "your-device-001"
grant_type: "authorization_code"
redirect_uri: "https://idm-sre-lab.local/callback"
scope: "openid profile email"

# SAML 2.0 SP-initiated
sp_entity_id: "https://idm-sre-lab.local/saml/metadata"
acs_url: "https://idm-sre-lab.local/saml/acs"

# WebAuthn 注册
challenge: "<server-generated>"
attestation: "<client-generated-public-key>"
```

### 2. 运维输入（事故触发）

```bash
# Chaos engineering 触发
curl -X POST http://idm-sre-lab.local/chaos/kill -d '{"service": "token-issuer", "duration_s": 30}'
```

---

## 📤 输出

### 1. 完整 IdM 服务

- **OAuth2 / OIDC**：`/oauth/authorize`, `/oauth/token`, `/oauth/userinfo`, `/.well-known/openid-configuration`
- **SAML 2.0**：`/saml/metadata`, `/saml/acs`, `/saml/slo`
- **WebAuthn**：`/webauthn/register/begin`, `/webauthn/register/finish`, `/webauthn/authenticate/begin`, `/webauthn/authenticate/finish`
- **设备 Provisioning API**：`POST /devices`, `GET /devices/{id}`, `DELETE /devices/{id}`（克诺尔 BU 设备生命周期）
- **Token 端点**：`POST /tokens/issue`, `POST /tokens/revoke`, `POST /tokens/rotate`

### 2. 完整 SRE 实践

- **SLI/SLO 文档**（docs/slo.md）：
  - availability > 99.9%（月度允许 downtime 43min）
  - p99 token 签发延迟 < 200ms
  - p99 SAML AuthnRequest 处理 < 500ms
  - error budget: 0.1% / 月
- **Observability**：
  - Prometheus metrics（requests_total / latency_seconds / errors_total）
  - Grafana dashboard（4 个 panel：latency / errors / saturation / traffic — Google SRE book 四大黄金指标）
  - OTel trace 接入
  - ELK-style 结构化日志
- **Chaos Engineering**：
  - 杀 pod 测试（kill token-issuer pod，验证 k8s 重启 + 自动恢复 < 30s）
  - 网络分区测试（network partition，验证 replica failover）
  - etcd 故障测试（k3s 内置 etcd，验证 IdM stateful 服务韧性）
- **On-Call Runbook**（docs/runbook.md）：
  - 高错误率响应流程
  - 数据库连接池耗尽响应
  - 证书过期响应
  - GenAI 告警工程（用 LLM 解读异常 + 自动建议）
- **Incident Response**：
  - Post-Mortem 模板（docs/postmortem-template.md）
  - 模拟 3 次事故（latency spike / auth fail / OOM）

### 3. 自动化 + CI/CD

- **沿用 vmodel-pipeline**：Tekton PipelineRun 5 stage（meta-ci + unit + integration + system + acceptance）
- **新增 chaos stage**：acceptance-test 后跑 chaos 验证
- **自动生成 SLI 报告**（每周 cron）

### 4. ISO 27001 / PCI 合规

- ✅ ISO 27001 控制项映射（access control / cryptography / logging）
- ✅ PCI-DSS Section 8（authentication）对照
- ✅ 审计日志（不可篡改，append-only）

---

## 🏗 架构（30 周路线图）

```
idm-sre-lab/
├── README.md
├── PRD.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── app/
│   ├── __init__.py            # init_db + call_llm + strip_thinking
│   ├── main.py                # FastAPI 入口
│   ├── oauth/                 # OAuth2 / OIDC 模块
│   │   ├── __init__.py
│   │   ├── authorize.py
│   │   ├── token.py
│   │   └── userinfo.py
│   ├── saml/                  # SAML 2.0 模块
│   │   ├── __init__.py
│   │   ├── metadata.py
│   │   ├── acs.py             # Assertion Consumer Service
│   │   └── slo.py             # Single Logout
│   ├── webauthn/              # WebAuthn / FIDO2 模块
│   │   ├── __init__.py
│   │   ├── register.py
│   │   └── authenticate.py
│   ├── devices/               # 设备 provisioning（克诺尔 BU 场景）
│   │   ├── __init__.py
│   │   └── lifecycle.py
│   ├── tokens/                # Token 签发/撤销/轮换
│   │   ├── __init__.py
│   │   └── manager.py
│   ├── observability/         # Prometheus + OTel + 结构化日志
│   │   ├── __init__.py
│   │   ├── metrics.py
│   │   └── tracing.py
│   ├── chaos/                 # Chaos engineering 实验
│   │   ├── __init__.py
│   │   └── experiments.py
│   └── incident/              # On-call runbook + LLM 告警
│       ├── __init__.py
│       ├── runbook.py
│       └── ai_alert.py
├── prompts/
│   ├── ai_alert.md
│   └── postmortem.md
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── hpa.yaml               # Horizontal Pod Autoscaler
│   ├── pdb.yaml               # PodDisruptionBudget（高可用）
│   └── prometheus.yaml        # ServiceMonitor
├── observability/
│   ├── prometheus/
│   │   └── prometheus.yml
│   ├── grafana/
│   │   └── dashboard.json
│   └── otel-collector/
│       └── config.yaml
├── security/                  # ISO 27001 + PCI 文档
│   ├── iso27001-mapping.md
│   ├── pci-controls.md
│   └── threat-model.md
├── docs/
│   ├── slo.md                 # SLI/SLO 文档
│   ├── runbook.md             # On-call runbook
│   ├── postmortem-template.md
│   └── architecture.md
├── web/                       # 管理 UI
│   ├── index.html
│   ├── style.css
│   └── app.js
├── tests/
│   ├── unit/                  # 单元测试（V 模型左下）
│   ├── integration/           # 集成测试（V 模型左中）
│   ├── chaos/                 # chaos tests（V 模型新增）
│   └── acceptance/            # 验收测试
└── data/
    └── idm.db                 # SQLite（开发用）
```

### 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| **IdM 服务** | FastAPI + Python 3.11 | 你已有 5 个 Python 项目，熟练 |
| **OAuth2/OIDC** | authlib + python-jose | 标准库，文档完整 |
| **SAML 2.0** | python3-saml | OneLogin 维护，最成熟 |
| **WebAuthn** | py_webauthn | WebAuthn 协议标准实现 |
| **数据库** | PostgreSQL（生产） / SQLite（dev） | 事务性 + JSON 支持 |
| **Cache** | Redis | Token 黑名单 + rate limit |
| **Observability** | Prometheus + Grafana + OTel + Loki | Apple JD 提到的全栈 |
| **K8s** | k3d + k3s（沿用 vmodel-pipeline） | 你的本地环境 |
| **CI/CD** | Tekton + Argo CD（沿用） | vmodel-pipeline 已验证 |
| **Chaos** | chaos-mesh / 自写 podkiller | 杀 pod 测试 |
| **LLM** | MiniMax-M3（沿用 .env） | 4 个项目统一 |

---

## 🚫 反模式

- **🚨 禁止"裸跑 FastAPI"**：必须 k3d + 多 replica + PDB + HPA
- **🚨 禁止"无 observability 的服务"**：每个 endpoint 必须有 metrics + trace + log
- **🚨 禁止"硬编码 SLO"**：SLI 必须从真实 metrics 算，不能拍脑袋
- **🚨 禁止"choreographed chaos"**：chaos 实验必须可重复 + 有 hypothesis + 跑前后对照
- **🚨 禁止"无 runbook 的 on-call"**：每个 alert 必须有 runbook 链接
- **🚨 禁止"LLM 瞎解读"**：ai_alert 必须含告警 ID + 时间窗 + 关联 metric + 修复建议
- **🚨 禁止"完全复制 Apple 内部架构"**：本项目是**自托管 IdM 学习项目**，非商业产品

---

## 🎯 30 周路线图（5-6 月交付）

### Week 1-2：地基
- PRD + 项目结构 + `pyproject.toml` + `.env`
- FastAPI 骨架（health endpoint）
- SQLite init_db
- Tekton 5 stage pipeline（沿用 vmodel-pipeline）

### Week 3-4：OAuth2 / OIDC MVP
- `/oauth/authorize` + `/oauth/token` + `/oauth/userinfo` + discovery
- authlib 集成 + JWT 签发 + refresh token
- 单元测试 + 集成测试

### Week 5-6：SAML 2.0
- python3-saml 集成
- SP-initiated SSO + IdP-initiated SSO
- ACS endpoint + SLO endpoint
- 元数据 XML 生成

### Week 7-8：WebAuthn
- py_webauthn 集成
- 注册流程（attestation）
- 认证流程（assertion）
- 用户生物识别 / 硬件 key demo

### Week 9-10：设备 Provisioning（克诺尔场景）
- POST /devices（注册）
- GET /devices/{id}（查询）
- DELETE /devices/{id}（注销）
- 设备生命周期管理 + 关联 user

### Week 11-12：Token 管理
- access token / refresh token / ID token
- token rotation + revocation
- Redis 黑名单 + 短 TTL

### Week 13-14：Observability 1（metrics + trace）
- Prometheus client 接入每个 endpoint
- OTel trace 自动 instrumentation
- Grafana dashboard（4 大黄金指标）

### Week 15-16：Observability 2（日志 + 告警）
- 结构化 JSON 日志
- Loki / ELK 风格聚合
- Prometheus alert rules（high error rate / high latency / saturation）

### Week 17-18：SLI/SLO 文档化
- docs/slo.md（4 个核心 SLO）
- error budget 计算 + burn rate 告警
- 每月 SLO report（自动生成）

### Week 19-20：Chaos Engineering
- chaos-mesh 安装 + 实验定义
- pod kill 实验（验证 HPA + readiness probe）
- 网络分区实验（验证 PDB + 多 replica）
- latency injection 实验

### Week 21-22：Incident Response
- docs/runbook.md（10 个常见事故）
- 模拟事故 #1：latency spike（kill -STOP）
- 模拟事故 #2：auth fail（故意 broken commit）
- 模拟事故 #3：OOM（leak memory）

### Week 23-24：GenAI 告警工程
- ai_alert.py：LLM 解读 Prometheus alert
- prompt：含告警 ID + 时间窗 + 关联 metric + 修复建议
- on-call 通知集成（webhook + 钉钉）

### Week 25-26：ISO 27001 / PCI 合规
- security/iso27001-mapping.md（每条控制项 → 项目实现）
- security/pci-controls.md（PCI-DSS 8.x 章节对照）
- security/threat-model.md（STRIDE 模型）

### Week 27-28：Post-Mortem 演练
- 真实跑 3 次事故 + 写 PM 文档
- template 应用（docs/postmortem-template.md）
- "blameless" 文化建立（不追责个人）

### Week 29-30：端到端验证 + 文档
- 全链路 smoke test
- 简历 reframe（克诺尔 Intune + IdMS lab）
- Demo 脚本写好（5 分钟讲完）
- Dashboard 项目集锦加 #13

---

## 🎯 30 周验收标准（最终）

- [ ] OAuth2 / OIDC 流程跑通（authorization code + PKCE）
- [ ] SAML 2.0 SP-initiated SSO 跑通（能用 mock IdP 测试）
- [ ] WebAuthn 注册 + 认证跑通（硬件 key 或软件 authenticator）
- [ ] 设备 provisioning API 跑通（克诺尔场景：注册 → 关联 user → token 签发 → 注销）
- [ ] SLI/SLO 文档 + Grafana dashboard 完整
- [ ] Chaos 实验跑通：pod kill → 30s 内自动恢复
- [ ] 3 次模拟事故 + Post-Mortem 完整
- [ ] ai_alert.py 真实 LLM 解读告警（不编造）
- [ ] ISO 27001 控制项映射 90% 覆盖
- [ ] **真实跑 30 天无 P0 事故**

---

## 🚀 Roadmap（30 周后）

### v1.1：Apple IdMS 级别功能
- 多区域 DR（同城双活 + 异地灾备）
- 高频设备认证（百万级 QPS 模拟）
- FAPI（金融级 API）合规

### v1.2：投递准备
- Apple IdMS / Microsoft Entra ID / Okta / Auth0 批量投
- mock interview 模拟（3 轮）
- 简历 reframe 完成

### v1.3：行业认证
- CKA（Certified Kubernetes Administrator）
- AWS Solutions Architect
- Terraform Associate

---

## 📝 与已有项目的关系

- **沿用 vmodel-pipeline 的 Tekton pipeline** + Argo CD
- **沿用 Interview/.env 的 LLM key**
- **沿用 career-coach / meeting-to-action / rss-reader 的 `_strip_thinking` 模式**
- **Dashboard 项目集锦** 加 #13 "IdM SRE Lab ⭐⭐⭐⭐⭐"

---

## 💡 面试讲法（预设）

1. "**完整 IdM 三件套**：OAuth2/OIDC + SAML + WebAuthn 全部实现 + 测试覆盖"
2. "**真实 SRE 实践**：SLI/SLO 从 0 设计 + chaos 验证 + on-call runbook"
3. "**GenAI 告警工程**：LLM 解读 Prometheus alert（v_explainer 风格）"
4. "**克诺尔背景 + IdM 域**：我用 Intune MDM 干了 4 年，本项目是技术 deep-dive"
5. "**完整 V 模型 + CI/CD**：Tekton 5 stage 跑通（meta-ci + 4 stage 测试 + chaos stage）"
6. "**合规经验**：ISO 27001 审计 + PCI-DSS 控制项映射"

---

**v0.1 PRD — 2026-09-21 起算，预计 30 周完成**