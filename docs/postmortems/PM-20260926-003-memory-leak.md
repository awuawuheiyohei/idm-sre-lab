# PM-20260926-003：Memory Leak from Long-Running Log Buffer

> **Status**：DRAFT
> **Severity**：SEV-2
> **Incident ID**：INC-20260925093500-8801
> **Author**：resilience-lead
> **Blameless**：Yes
> **Date**：2026-09-26

---

## 1. Summary

On 2026-09-25 at 17:40 SGT, a `memory_leak` incident simulator caused in-memory log buffer to grow to 50,000 entries (10x normal). In-process memory usage spiked to 800MB, triggering `MemoryLeak` runbook. Incident was identified as chaos within 2 minutes and resolved by experiment auto-close + buffer reset.

## 2. Timeline

| Time | Event | Actor |
|---|---|---|
| 17:40:00 | `memory_leak` incident simulator started | resilience-lead |
| 17:40:30 | Log buffer at 5,000 entries (10% threshold) | system |
| 17:41:00 | `MemoryLeak` runbook activated | system |
| 17:41:30 | on-call ack, identified chaos experiment | carol |
| 17:42:00 | Experiment auto-completed, buffer stable at 50,000 entries | system |
| 17:42:30 | Force buffer reset (cleared entries) | carol |
| 17:43:00 | Incident marked RESOLVED | carol |

## 3. Root Cause (5 Whys)

```
Problem: Memory spike to 800MB from log buffer growth
Why 1:  Why did buffer grow? → memory_leak chaos appended 100 entries/sec
Why 2:  Why was 100 entries/sec allowed? → No rate limit on logger
Why 3:  Why no rate limit? → Logger assumes human-readable volume, not chaos load
Why 4:  Why no buffer cap? → deque(maxlen=5000) but chaos bypasses normal flow
Why 5:  ROOT: MemoryLeak detection only via in-process metrics, not OS RSS
```

## 4. Impact

- **User impact**: None directly (services continued to function)
- **Operational impact**: 30 seconds of elevated memory, no auto-recovery
- **SLO impact**: Saturation alert fired (in-flight > 1000)

## 5. What Went Well

- ✅ `MemoryLeak` runbook activated automatically
- ✅ In-process metrics detected anomaly within 60 seconds
- ✅ Buffer bounded (deque maxlen)

## 6. What Went Wrong

- ❌ No OS-level memory monitoring (RSS)
- ❌ No auto-buffer-reset on threshold breach
- ❌ MemoryLeak runbook step 4 "kubectl rollout restart" would have lost all logs

## 7. Action Items

| # | Owner | Action | Due Date | Priority |
|---|---|---|---|---|
| 1 | alice | Add OS-level RSS monitoring to /metrics (process_resident_memory_bytes) | 2026-10-10 | P0 |
| 2 | bob | Add auto-buffer-reset on log buffer > 80% capacity | 2026-10-12 | P1 |
| 3 | carol | Update MemoryLeak runbook to use tracemalloc instead of restart | 2026-10-15 | P2 |

## 8. Lessons Learned

- **System**: In-process metrics miss OS-level signals (RSS, file descriptors, CPU)
- **Process**: Memory leak runbook should prefer tracing over restart
- **Culture**: blameless — no engineer wrote a leak, system lacked protection

## 9. References

- Runbook: `memory_leak` (SEV-1)
- Alert: `MemoryLeak` (early detection via in-process metrics)
- PRD: `docs/runbook.md` (Section 9)