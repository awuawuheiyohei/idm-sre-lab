# PM-20260926-002：Auth Failure Storm from Latency Injection

> **Status**：PUBLISHED
> **Severity**：SEV-2
> **Incident ID**：INC-20260925092800-7421
> **Author**：resilience-lead
> **Blameless**：Yes
> **Date**：2026-09-26

---

## 1. Summary

On 2026-09-25 at 17:35 SGT, a `latency_spike` chaos experiment injected 800ms latency into `/oauth/token` endpoint for 2 minutes. While p99 latency exceeded SLO threshold (200ms), the high latency caused downstream client retry storms, increasing effective error rate from 0% to 12%. The incident was identified as chaos within 4 minutes and resolved by experiment auto-close.

## 2. Timeline

| Time | Event | Actor |
|---|---|---|
| 17:35:00 | `latency_spike` chaos experiment started | resilience-lead |
| 17:35:02 | p99 latency 800ms (target < 200ms) | prometheus |
| 17:35:30 | `HighLatencyP95` alert fired | prometheus |
| 17:35:45 | Client retry storms begin (12% effective errors) | system |
| 17:36:00 | on-call ack, identified chaos experiment | bob |
| 17:37:00 | Experiment auto-completed | system |
| 17:37:30 | Incident marked RESOLVED | bob |

## 3. Root Cause (5 Whys)

```
Problem: p99 latency 800ms (target < 200ms) + 12% effective errors
Why 1:  Why was latency so high? → Chaos experiment injected 800ms
Why 2:  Why did this cause 12% errors (not 0)? → Client retry logic doubled request volume
Why 3:  Why does client have aggressive retry? → No exponential backoff configured
Why 4:  Why no client-side rate limit? → Client library version outdated
Why 5:  ROOT: Client retry strategy missing exponential backoff + jitter
```

## 4. Impact

- **User impact**: 800ms extra latency on every token request for 2 minutes
- **Business impact**: ~12% effective errors due to retry storm
- **SLO impact**: Token Issuance p99 SLO violated for 2 minutes

## 5. What Went Well

- ✅ `HighLatencyP95` alert fired promptly
- ✅ on-call identified chaos quickly
- ✅ Auto-close mechanism worked

## 6. What Went Wrong

- ❌ Client retry logic not validated against high-latency scenarios
- ❌ No client-side rate limit or circuit breaker
- ❌ Latency injection experiment didn't have warning notification

## 7. Action Items

| # | Owner | Action | Due Date | Priority |
|---|---|---|---|---|
| 1 | alice | Add exponential backoff + jitter to client retry logic | 2026-10-05 | P0 |
| 2 | alice | Add circuit breaker for token endpoint | 2026-10-08 | P0 |
| 3 | bob | Update latency injection chaos to start with warning notification | 2026-10-10 | P1 |

## 8. Lessons Learned

- **System**: Client resilience (retry + circuit breaker) is part of SLO
- **Process**: Latency SLO must include retry-induced effective error rate
- **Culture**: blameless — client library was outdated, not personal error

## 9. References

- Chaos experiment: `latency_spike` chaos type
- Runbook: `high_latency` (SEV-2)
- SLO: `token_p99_latency` (200ms threshold)