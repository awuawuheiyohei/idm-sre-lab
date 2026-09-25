# IdM SRE Lab — On-Call Runbook（Week 21-22）

> **目的**：Apple IdMS SRE 风格 — 每个 alert 必须有 runbook 链接，每个 on-call 工程师都能按 runbook 缓解。
> **更新日期**：2026-09-25

---

## On-Call 流程（Google SRE 标准）

1. **Alert 触发** → PagerDuty 通知 → on-call engineer 收到 page
2. **Acknowledge**（5 分钟内）— 防止 alert storm
3. **查 runbook**（用 `/runbooks/recommend` 自动推荐）
4. **Mitigate** — 按 runbook steps 操作
5. **Resolve** — 标记 `RESOLVED` + 写 `lessons_learned`
6. **Postmortem**（SEV-1/2 强制）— `docs/postmortem-template.md`

---

## 10 个常见事故 Runbook（按严重度排序）

### SEV-1（Critical）：立即 page

#### 1. `high_error_rate` — HTTP 5xx 错误率 > 5%

**Indicators**：idm_errors_total 5xx 计数 > 总请求 5% 持续 5+ 分钟

**Steps**：
1. 查 chaos_experiments 是否在跑（避免误判）
2. 检查 token-issuer / saml-issuer 最近 deploy
3. 检查依赖（DB / JWT signing key / external IdP）
4. 查 `/logs?level=ERROR` 找堆栈模式
5. 如果是 DB 问题：触发 connection pool reset

**Escalation**：15 分钟未缓解 → on-call lead → Incident Commander

#### 3. `token_failure_spike` — Token 验证失败突增

**Indicators**：401/400 错误突增 / `/oauth/introspect` `active=false` 比例升高

**Steps**：
1. 检查 RSA signing key 状态（rotation 没完成）
2. 检查 client_secret 是否误 rotate
3. 检查是否在测试 expired token
4. 如果是 key rotation：保留旧 key 至少 24h

**Escalation**：影响所有 client → 立即 page security team

#### 9. `memory_leak` — OOM 风险

**Indicators**：RSS 持续增长 / in-flight requests > 10000

**Steps**：
1. 抓 heap snapshot（tracemalloc）
2. 找 top 增长对象
3. 临时 `kubectl rollout restart` 释放内存
4. 找 leak 根因（未关闭 connection / cache 无 eviction）

**Escalation**：立即 → on-call lead

---

### SEV-2（Warning）：1 小时内响应

#### 2. `high_latency` — p99 > 1000ms

**Steps**：
1. 检查 DB 连接池状态
2. 检查 JWT signing key 缓存 miss（RSA key cache 重建）
3. 减少 JWKS endpoint cache TTL
4. 检查外部 IdP SSO timeout 配置

#### 4. `database_connection_pool` — DB 连接耗尽

**Steps**：
1. 查 busy_timeout 配置
2. 杀长查询（> 5s）
3. 重启服务
4. 临时 disable 长 query feature

#### 5. `certificate_expiry` — TLS 证书 30 天内过期

**Steps**：
1. 查 RSA key 创建时间
2. 生成新 key（保留旧 key 24h 过渡）
3. 通知 client 切换 JWKS endpoint
4. 24h 后撤销旧 key

**Escalation**：提前 7 天预警 → 立即升级 SEV-1

#### 7. `disk_space_low` — 磁盘 < 10%

**Steps**：
1. 查 DB WAL / SHM 大小
2. 清理过期 chaos_experiments / incidents
3. 触发 `PRAGMA wal_checkpoint(TRUNCATE)`

#### 8. `cpu_saturation` — CPU > 90%

**Steps**：
1. 查热点 endpoint（p99 哪个 endpoint 慢）
2. 临时 HPA 扩容
3. 检查是否有死循环 / 死锁

#### 10. `service_discovery_failure` — Pod unreachable

**Steps**：
1. `kubectl describe pod` 看 restart reason
2. 检查 DB connection（启动时 init_db）
3. 检查 signing key 加载
4. 看 OOMKilled / CrashLoopBackOff

---

### SEV-3（Info）：1 工作日内响应

#### 6. `rate_limit_exceeded` — 客户端触发 rate limit

**Steps**：
1. 检查 client_id 合法性
2. 临时增加 rate limit
3. 通知 client 团队让其自我 rate limit

---

## Mitigate → Resolve 流程

```bash
# 1. 创建 incident（手工或 simulator）
curl -X POST /incidents -d "incident_type=auth_fail&severity=SEV-1&title=..."
# 或
curl -X POST /incidents/simulate -d "incident_type=auth_fail&duration_seconds=30"

# 2. 查推荐 runbook
curl /runbooks/recommend

# 3. Mitigation 完成后标记 RESOLVED + lessons learned
curl -X PATCH /incidents/INC-XXX \
  -d "status=RESOLVED&mitigation=rolled+back+deploy&lessons_learned=need+canary"
```

---

## Postmortem（SEV-1/2 强制）

按 `docs/postmortem-template.md` 模板写 PM 文档，重点：
- **blameless** culture（不追责个人）
- 5 Whys root cause 分析
- action items 落地（写入 `caps` 表 — Week 27-28）

---

**详细 endpoint 见**：`app/incidents/routes.py`
**完整 10 个 runbook**：`app/incidents/runbook.py`