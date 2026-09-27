# PM-20260926-001：OAuth Token Endpoint 503 Spike

> **Status**：PUBLISHED
> **Severity**：SEV-1
> **Incident ID**：INC-20260925092744-5330
> **Author**：resilience-lead
> **Blameless**：Yes
> **Date**：2026-09-26

---

## 1. Summary

On 2026-09-25 at 17:30 SGT, the `/oauth/token` endpoint experienced a 90% error rate spike for 2 minutes, returning HTTP 503 Service Unavailable. Token issuance was degraded for approximately 1,200 active users during this window. The incident was triggered by a planned chaos engineering experiment (`pod_kill`) which intentionally simulated a process failure. Mitigation was achieved by waiting for the experiment to complete (auto-close after duration).

## 2. Timeline

| Time | Event | Actor |
|---|---|---|
| 2026-09-25 17:30:00 | Chaos experiment `pod_kill` started (2s duration) | resilience-lead |
| 2026-09-25 17:30:02 | `HighErrorRate` alert fired (error_rate 90%) | prometheus |
| 2026-09-25 17:30:05 | on-call ack via `/chaos/experiments` check | alice |
| 2026-09-25 17:30:30 | Identified as chaos experiment via `chaos_experiments` table | alice |
| 2026-09-25 17:32:00 | Experiment auto-completed (duration + 1s) | system |
| 2026-09-25 17:32:30 | Incident marked RESOLVED, lessons learned drafted | alice |

## 3. Root Cause (5 Whys)

```
Problem: /oauth/token 503 spike (90% errors, 2min)
Why 1:  Why was /oauth/token returning 503? → Experiment simulator forced 503 responses
Why 2:  Why was an experiment running on production? → Dev environment mistaken for staging
Why 3:  Why no environment isolation? → Single cluster, no namespace separation
Why 4:  Why no chaos guardrail? → `chaos_experiments` lacked "env" field
Why 5:  ROOT: Chaos Engineering policy missing (no environment gate, no PRB)
```

**Root cause**: Chaos engineering policy missing environment isolation, allowing dev experiments to impact shared cluster.

## 4. Impact

- **User impact**: 1,200 active users experienced failed token issuance for 2 minutes
- **Business impact**: 0% SLO breach (incident was within chaos duration)
- **SLO impact**: Burn rate spiked to 90% for 1 minute, no sustained impact

## 5. What Went Well

- ✅ `HighErrorRate` alert fired within 2 seconds
- ✅ on-call ack within 5 minutes
- ✅ Incident identified as chaos (not real outage) within 3 minutes
- ✅ Auto-close mechanism prevented manual cleanup

## 6. What Went Wrong

- ❌ No environment guardrail — dev chaos leaked to shared cluster
- ❌ No Slack notification when chaos experiment started
- ❌ Runbook step 1 ("Check chaos_experiments") not documented clearly

## 7. Action Items

| # | Owner | Action | Due Date | Priority |
|---|---|---|---|---|
| 1 | alice | Add `environment` field to chaos_experiments schema | 2026-10-01 | P0 |
| 2 | alice | Block chaos experiments with env=dev on production cluster | 2026-10-03 | P0 |
| 3 | bob | Add Slack notification on chaos experiment start | 2026-10-05 | P1 |
| 4 | carol | Update `high_error_rate` runbook step 1 with clear SQL query | 2026-10-07 | P2 |

## 8. Lessons Learned

- **System**: Chaos engineering needs environment isolation (k8s namespace or cluster-level)
- **Process**: On-call runbook step 1 should be auto-displayed in alert context
- **Culture**: blameless — no engineer was at fault, system lacked guardrail

## 9. References

- Incident: `INC-20260925092744-5330`
- Chaos experiment: `CHAOS-20260925091531-7380` (pod_kill, 2s)
- Runbook: `high_error_rate` (SEV-1)
- PRD: `docs/runbook.md`