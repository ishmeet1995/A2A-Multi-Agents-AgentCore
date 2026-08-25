# Runbook: Elevated 5xx Error Rate

**Metric:** `5xxErrorRate`
**Applies to:** API Gateway, Application Load Balancer, and any request-serving tier

## Trigger Conditions
- 5xxErrorRate > 1% of total requests over a 5-minute window
- Severity escalates to **critical** if error rate exceeds 5%, or if it's climbing rather than holding steady

## Diagnosis Steps
1. Check whether errors are concentrated on one endpoint/route or spread across all traffic. Concentrated errors point to a specific code path; spread-out errors point to an infrastructure or dependency-wide issue.
2. Check whether the error rate started right after a deployment — this is one of the most common root causes and should be checked first, before anything else.
3. Check downstream dependency health (database, third-party APIs, internal services this tier calls) — a downstream outage often surfaces as 5xx errors at this layer even though this tier's own code is fine.

## Remediation Decision
- **Correlated with a recent deploy**: this is a rollback decision. Do NOT auto-remediate — a human needs to confirm the rollback is safe (e.g., no destructive migrations that make rollback non-trivial).
- **Correlated with a downstream dependency outage**: no remediation action available at this tier — the fix is at the dependency, which is likely being monitored/remediated by its own alarm chain. Informational, but still worth surfacing so a human has full context.
- **Not correlated with a deploy or a known dependency issue, spread across all traffic**: could be a capacity/infrastructure issue — evaluate for scaling, but treat with caution since 5xx errors are rarely fixed by adding capacity alone.

## Remediation Actions (auto-approved cases only)
None. This alarm class consistently requires human judgment (rollback decisions, dependency correlation, or root-cause investigation) rather than a mechanical fix. Auto-remediation risk here is high: rolling back the wrong thing, or scaling infrastructure that isn't the actual bottleneck, can make the situation worse or mask the real problem.

## Escalation Path
Always escalate. Include in the page:
- Whether errors are concentrated on a specific endpoint or spread across all traffic
- Whether a deploy landed in the window before the alarm started
- Status of known downstream dependencies, if checked

## Notes
This is the one alarm class in this runbook set with zero auto-remediation actions. Every 5xx spike needs a human to look at deploy history and dependency health before any action is taken.
