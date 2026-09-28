# 5 分钟 Demo 脚本（Week 29-30）

> **目的**：5 分钟讲完 idm-sre-lab 全栈
> **使用场景**：Apple IdMS / Microsoft Entra ID / 国内 IdM 厂商面试 technical round
> **关键**：5 分钟内 demo 完 7 大模块（OAuth + SAML + WebAuthn + Devices + Observability + Chaos + Incident → Post-Mortem）

---

## Demo 时间表

| 时间 | 模块 | 演示命令 |
|---|---|---|
| 0:00-0:30 | 启动 + 简介 | `python3 -m app.main` + 30 秒讲"30 周路线图收尾" |
| 0:30-1:30 | OAuth 完整流程 | login → token → userinfo |
| 1:30-2:30 | SAML SSO | SP-initiated → IdP → ACS → cookie |
| 2:30-3:00 | WebAuthn | register + challenge + authenticate |
| 3:00-3:30 | Devices | register → activate → compliance |
| 3:30-4:00 | Observability | /metrics + /dashboard + 4 Golden Signals |
| 4:00-4:30 | Chaos | pod_kill experiment + baseline/after 对比 |
| 4:30-5:00 | Incident → Post-Mortem | simulator + PATCH RESOLVED + PM PUBLISHED |

---

## 详细脚本

### 0:00-0:30 — 启动

```bash
cd /Users/jiangwenrui/Downloads/mass/idm-sre-lab
python3 -m app.main
# 等 ~3 秒 server 起来
```

**讲**：
> "我做了一个 Apple IdMS 风格 Identity Management 平台，从 Week 1-2 地基到 Week 29-30 端到端验证 30 周完成。73 个 endpoints，202 个 tests，34 个 E2E smoke checks。让我 5 分钟 demo 完整流程。"

### 0:30-1:30 — OAuth 2.0

```bash
# 1. Discovery
curl http://127.0.0.1:5050/.well-known/openid-configuration | head

# 2. Login (模拟 POST form)
LOC=$(curl -s -X POST http://127.0.0.1:5050/oauth/authorize \
  -d "username=engineer01&password=Engineer@2026&client_id=tripbiz-booking-app&redirect_uri=http://127.0.0.1:5050/callback&scope=openid+profile+email" \
  -o /dev/null -w "%{redirect_url}")
echo $LOC  # → http://127.0.0.1:5050/callback?code=...

# 3. Exchange code for token
CODE=$(echo $LOC | sed -n 's/.*code=\([^&]*\).*/\1/p')
curl -X POST http://127.0.0.1:5050/oauth/token \
  -d "grant_type=authorization_code&code=$CODE&redirect_uri=http://127.0.0.1:5050/callback&client_id=tripbiz-booking-app&client_secret=tripbiz-booking-app-secret-2026" | python3 -m json.tool

# 4. Use access token
ACCESS=$(...)
curl -H "Authorization: Bearer $ACCESS" http://127.0.0.1:5050/oauth/userinfo
```

**讲**：
> "这是 authorization code grant。3 个 user 都有 password 哈希存储（bcrypt），client secret 也是 bcrypt 哈希。这是 RFC 6749 + 7662 introspect + PKCE S256。"

### 1:30-2:30 — SAML SSO

```bash
# 1. SP metadata (XML)
curl http://127.0.0.1:5050/saml/metadata | head -10

# 2. SP-initiated login → IdP
curl -X POST http://127.0.0.1:5050/saml/login?RelayState=/dashboard -L

# 3. IdP login form + submit
# (form auto-submit with engineer01/Engineer@2026)

# 4. ACS → cookie
# (curl with -c to capture cookie)
```

**讲**：
> "SAML SP-initiated SSO 完整流程：SP metadata → AuthnRequest → IdP login → SAML Response with Assertion → ACS verify → cookie。这是 Week 5-6 实现的 16 tests。"

### 2:30-3:00 — WebAuthn

```bash
# 1. Register begin
curl -X POST http://127.0.0.1:5050/webauthn/register/begin -d "username=engineer01"

# 2. Register finish
CHAL=$(...)
curl -X POST http://127.0.0.1:5050/webauthn/register/finish \
  -d "username=engineer01&challenge=$CHAL&credential_id=cred_demo&friendly_name=DemoKey"

# 3. Authenticate begin
curl -X POST http://127.0.0.1:5050/webauthn/authenticate/begin -d "username=engineer01"

# 4. Compute signature + finish
SIG=$(python3 -c "from app.webauthn.webauthn_core import sign_challenge_response; print(sign_challenge_response('$CHAL2', 'cred_demo', 1))")
curl -X POST http://127.0.0.1:5050/webauthn/authenticate/finish \
  -d "username=engineer01&challenge=$CHAL2&credential_id=cred_demo&counter=1&signature=$SIG"
```

**讲**：
> "WebAuthn / FIDO2 challenge-response。简化版用 HMAC，生产换 COSE 椭圆曲线。Counter 单调递增防 replay attack。"

### 3:00-3:30 — Devices Provisioning

```bash
# 1. Register device
curl -X POST http://127.0.0.1:5050/devices \
  -d "device_name=Demo+Laptop&user_id=USER-001&device_type=LAPTOP&os=Linux&serial_number=DEMO-001"

# 2. Activate
DEV=$(...)
curl -X POST http://127.0.0.1:5050/devices/$DEV/activate

# 3. Compliance
curl -X POST http://127.0.0.1:5050/devices/$DEV/compliance -d "compliance_state=COMPLIANT"

# 4. Portfolio stats
curl http://127.0.0.1:5050/devices/portfolio/stats
```

**讲**：
> "克诺尔 BU 风格设备生命周期。REGISTERED → ACTIVE → COMPLIANT。350 终端 × 800 员工场景。这对应 Intune MDM 同步。"

### 3:30-4:00 — Observability

```bash
# 1. Prometheus /metrics
curl http://127.0.0.1:5050/metrics | head -20

# 2. 4 Golden Signals
curl http://127.0.0.1:5050/observability/signals | python3 -m json.tool

# 3. Dashboard HTML
curl http://127.0.0.1:5050/observability/dashboard -o /tmp/dash.html
open /tmp/dash.html
```

**讲**：
> "Google SRE 4 Golden Signals：Traffic / Latency / Errors / Saturation。Prometheus exposition 兼容 Grafana。Latency p50/p95/p99 histogram。"

### 4:00-4:30 — Chaos

```bash
# 1. Create experiment
EXP=$(curl -X POST http://127.0.0.1:5050/chaos/experiments \
  -d "experiment_type=latency_injection&target_service=demo&duration_seconds=2&hypothesis=service+should+remain+stable" | python3 -c "import sys,json; print(json.load(sys.stdin)['experiment_id'])")

# 2. Run (synchronous, 2s)
curl -X POST http://127.0.0.1:5050/chaos/experiments/$EXP/run | python3 -m json.tool

# 3. View verdict
curl http://127.0.0.1:5050/chaos/experiments/$EXP | python3 -c "import sys,json; d=json.load(sys.stdin); print('verdict:', d['verdict']); print('baseline error_rate:', d['baseline_metrics'].get('error_rate_pct')); print('after error_rate:', d['after_metrics'].get('error_rate_pct'))"
```

**讲**：
> "Chaos Engineering：3 类实验 pod_kill / network_partition / latency_injection。每个实验有 hypothesis + baseline/after metrics 对照。Verdict PASSED/FAILED 由 hypothesis 决定。这避免 choreographed chaos。"

### 4:30-5:00 — Incident → Post-Mortem

```bash
# 1. List runbooks
curl http://127.0.0.1:5050/runbooks | python3 -c "import sys,json; print('count:', json.load(sys.stdin)['count'])"

# 2. Recommend runbook
curl http://127.0.0.1:5050/runbooks/recommend

# 3. Simulate incident
INC=$(curl -X POST http://127.0.0.1:5050/incidents/simulate \
  -d "incident_type=auth_fail&duration_seconds=2" | python3 -c "import sys,json; print(json.load(sys.stdin)['incident_id'])")

# 4. Resolve + lessons learned
curl -X PATCH http://127.0.0.1:5050/incidents/$INC \
  -d "status=RESOLVED&lessons_learned=need+rate+limit+before+user+retry+storm"

# 5. Create Post-Mortem
PM=$(curl -X POST http://127.0.0.1:5050/pm-documents \
  -d "title=Auth+Fail+Storm+PM&severity=SEV-2" | python3 -c "import sys,json; print(json.load(sys.stdin)['pm_id'])")

# 6. Publish PM
curl -X PATCH http://127.0.0.1:5050/pm-documents/$PM -d "status=PUBLISHED"
```

**讲**：
> "Incident → runbook 自动推荐 → simulator 触发 → resolve with lessons learned → Post-Mortem PUBLISHED。blameless culture：5 Whys 找系统根因，不追责个人。"

---

## 5 分钟结束语

> "30 周路线图收尾：73 endpoints，202 tests，34 E2E smoke checks，34/34 全 pass。Apple IdMS 风格：协议栈（OAuth + SAML + WebAuthn）+ SRE 实践（metrics + chaos + incident + PM）+ AI 集成（真实 LLM）+ 合规文档（ISO 27001 + PCI + STRIDE）。每个模块都有可 demo 端点 + 单元 + 集成测试 + 真实运行验证。这就是我过去 6 个月的'学习 + 产出'。"

---

## 备用问答（如果面试官追问）

**Q：为什么不用 chaos-mesh / prometheus-client / python-saml？**

A：PEP 668 阻挡 pip install。homebrew Python 不能全局 pip install。我的策略是"纯 Python + stdlib 实现"，这样：
- 不依赖第三方库的版本变化
- 完全可控
- 演示用 dep list 极简

**Q：HMAC 签名 vs RSA XML-DSig？**

A：HMAC 简化版用于 demo + 单元测试。生产部署必须用 XML-DSig（RSA 签名 + X.509 cert 链）。Week 32 计划：替换为 lxml + python3-saml（生产环境）。

**Q：怎么验证 chaos 实验没影响 production？**

A：Week 25-26 ISO 27001 A.8.20 提到了这个 — chaos_experiments 表有 `environment` 字段（计划中），未来加 namespace 隔离 + PRB 限制。

**Q：你怎么决定优先级（30 周里）？**

A：按 Apple IdMS 5+ 年 SRE JD 反推：
- 协议栈（Week 3-10）：核心 IdM 知识
- SRE 实践（Week 11-22）：on-call 必备
- AI（Week 23-24）：加分项
- 合规（Week 25-26）：面试常问
- Post-Mortem（Week 27-28）：文化展示

**Q：这些项目里哪个最接近 Apple IdMS 的实际架构？**

A：idm-sre-lab 整体就是 Apple IdMS 简化版。具体：
- Apple IdMS 用 HSM 存 signing key → 我用 RSA private key 在 DB（生产应换 HSM）
- Apple IdMS 多 IdP 联邦 → 我 mock 自建 IdP
- Apple IdMS 设备用 MDM（Jamf）→ 我模拟克诺尔 BU 风格

---

## 演示准备清单

- [ ] Server 启动（端口 5050）
- [ ] Admin seed 已跑
- [ ] Demo credentials 在脑里（engineer01 / Engineer@2026）
- [ ] e2e_smoke.sh 跑过（34/34）
- [ ] 浏览器打开 `observability/dashboard`（可视化备用）
- [ ] idm-sre-lab GitHub repo 可访问（demo 后展示源码）

---

**最后更新**：2026-09-28
**配套**：30-week-checklist.md / resume-reframe.md / e2e_smoke.sh