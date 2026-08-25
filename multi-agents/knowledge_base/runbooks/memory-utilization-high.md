# Runbook: High Memory Utilization

**Metric:** `MemoryUtilization`
**Applies to:** EC2 app-tier instances and containerized workloads (ECS/EKS)

## Trigger Conditions
- MemoryUtilization > 85% sustained for 10+ minutes
- Severity escalates to **critical** if the instance is within 5% of OOM-kill territory (typically >95%)

## Diagnosis Steps
1. Check whether memory usage climbed gradually over hours/days (classic memory leak signature) or jumped suddenly (a specific request or batch job).
2. If containerized, check whether one container/task is responsible or whether it's spread across all tasks on the host — one bad container points to that specific service; spread-out growth points to a host-level issue.
3. Check recent deploy history — memory leaks are frequently introduced by a specific code change and show up as a slow, steady climb starting right after that deploy.

## Remediation Decision
- **Gradual climb correlated with a specific deploy (leak signature)**: do NOT auto-remediate with a restart alone — a restart will temporarily fix the symptom but the leak will recur. Auto-remediation may restart the affected process/container to buy time, but this must be paired with an escalation, not treated as resolved.
- **Sudden jump tied to a known batch job or traffic spike, memory recovers after**: informational, no action needed if it self-resolves.
- **Sustained high with no clear deploy correlation**: treat as a capacity issue — the workload may simply be undersized for its instance type.

## Remediation Actions (auto-approved cases only)
1. For a suspected leak, restart the specific affected container/process (not the whole host) to relieve immediate pressure — but always pair this with an escalation, since the underlying leak is not fixed by a restart.
2. For a capacity issue with no leak signature, this is an infrastructure sizing decision — do not auto-remediate; escalate.

## Escalation Path
Always escalate if:
- The pattern matches a memory leak (gradual, deploy-correlated climb) — the automated restart is a stopgap, not a fix
- Memory approaches OOM-kill territory (>95%) regardless of cause — this is time-sensitive

## Notes
A memory leak that gets "fixed" by an automated restart without escalation will simply recur on the same slow timeline. Treat automated restarts here as buying time for a human, never as resolution.
