# Post-Mortem Template（Week 27-28）

> **目的**：Apple IdMS SRE 风格 — "blameless" post-mortem culture
> **原则**：不追责个人（no blame），只关注系统/流程改进
> **更新日期**：2026-09-26
> **模板版本**：v1.0

---

## Header

| 字段 | 说明 |
|---|---|
| PM ID | PM-YYYYMMDD-NNN |
| Title | 简短描述（1 行） |
| Severity | SEV-1 / SEV-2 / SEV-3 |
| Incident ID | 关联的 incident_id（如有） |
| Author | PM 文档作者 |
| Status | DRAFT / REVIEW / PUBLISHED |
| Blameless | Yes（永远） |

---

## 1. Summary（简短总结，1-2 段）

- 发生了什么（事实，无评判）
- 影响范围（用户数 / 时长 / 业务影响）

**模板**：
```
On [date], [system] experienced [symptom] for [duration],
affecting [user count] users. [What happened at high level].
[Resolution approach] was applied and service was restored at [time].
```

---

## 2. Timeline（按时间顺序）

| Time | Event |
|---|---|
| T+0 | 事故触发（alert fire / user report） |
| T+5min | on-call ack |
| T+10min | 开始 mitigation |
| T+30min | 服务恢复 |
| T+1d | Post-Mortem 文档开始 |
| T+1w | 文档 PUBLISHED + action items 落地 |

**原则**：
- 精确到分钟（不要 "around 3pm"）
- 包含 **所有** 关键决策（不只成功，也含失败尝试）
- 注明每个时间点的 **act** + **actor**

---

## 3. Root Cause Analysis（5 Whys）

**5 Whys 模板**：

```
Problem: [症状描述]
Why 1: [第一层原因]
Why 2: [第二层原因]
Why 3: [第三层原因]
Why 4: [第四层原因]
Why 5: [根本原因，通常是流程/架构层面]
```

**示例**：
```
Problem: OAuth token endpoint 503 50% requests
Why 1: token-issuer pod 持续 restart
Why 2: pod OOMKilled
Why 3: JWT signing key cache 内存泄漏
Why 4: cache 无 eviction 策略
Why 5: 设计阶段未考虑 long-running 进程的内存监控（observability gap）
```

---

## 4. Impact（影响范围）

- **用户影响**：多少用户受影响 + 多长时间
- **业务影响**：收入损失 / SLA 违约 / 监管风险
- **SLO 影响**：是否触发 burn rate alert

---

## 5. What Went Well（做得好的）

- 哪个 alert 快速识别事故
- 哪个 runbook 步骤有效
- 哪个 mitigation 起作用
- 团队响应时间

---

## 6. What Went Wrong（做得不好的）

- 哪个 alert 缺失或延迟
- 哪个 runbook 不准确
- 哪个 mitigation 失败
- 哪个流程有 gap

---

## 7. Action Items（行动项）

| # | Owner | Action | Due Date | Priority |
|---|---|---|---|---|
| 1 | alice | 加 JWT signing key cache eviction 策略 | YYYY-MM-DD | P0 |
| 2 | bob | 加 long-running 进程内存监控 | YYYY-MM-DD | P1 |
| 3 | carol | 改进 on-call runbook for OOM 场景 | YYYY-MM-DD | P2 |

**原则**：
- 每个 action item 必填 owner + due date
- P0 = 立即（< 1 周），P1 = 短期（< 1 月），P2 = 中期（< 1 季度）
- 写明 **具体** 动作（不是"加监控"，而是"加 JWT signing key cache size > 1000MB 告警"）

---

## 8. Lessons Learned（教训）

- 系统层面：架构/代码如何改进
- 流程层面：on-call / runbook / 测试如何改进
- 文化层面：知识共享 / blameless / 持续学习

---

## 9. References（参考）

- 相关 incident ID
- 相关 chaos experiment
- 相关 commit / PR
- 相关 runbook 章节

---

## Anti-Patterns（避免）

- ❌ **追责个人**："alice 配置错了"
- ✅ **追责系统**："我们的 CI 没有 catch 这个 lint 错误"
- ❌ **模糊 action**："加测试"
- ✅ **具体 action**："加 test:unit for db_connection() timeout handling (4 test cases)"
- ❌ **掩盖**："只写 what went well"
- ✅ **诚实**："5 Whys 找根因，承认 gap"
- ❌ **跳过 PUBLISHED**：PM 文档写完不发布 = 不闭环
- ✅ **强制 PUBLISHED**：写完发到 #incidents Slack channel，所有 on-call 都看到

---

## PM 文档生命周期

```
DRAFT → REVIEW → PUBLISHED → (90 天后) → ARCHIVED
       ↓
   (Review 由 incident lead + SRE 负责人 + 受影响 BU 代表)
```

---

**详细 PM 文档示例**：见 `docs/postmortems/` 目录
**API endpoint**：`/pm-documents` CRUD
**实施**：见 `app/postmortem/routes.py`