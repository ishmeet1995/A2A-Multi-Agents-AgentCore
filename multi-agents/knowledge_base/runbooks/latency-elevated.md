# Runbook: Elevated Latency

**Metric:** `Latency`
**Applies to:** API Gateway, load balancers, and other request-serving tiers

## Trigger Conditions
- **Informational threshold:** Latency reaches 70%+ of the configured alert threshold but has not crossed it (e.g., 420ms against a 500ms threshold)
- **Alarm threshold:** Latency crosses the configured threshold (varies by API, typically 500ms–1000ms depending on the endpoint's SLA)

## Diagnosis Steps
1. Check whether latency rose gradually (traffic growth) or spiked suddenly (a specific request pattern, a downstream dependency slowing down, or a cold-start event).
2. If a spike, check downstream dependencies (database query times, third-party API calls) for the same window — elevated latency is very often a symptom of a slow dependency, not the service itself.
3. Check whether the elevated latency correlates with a specific endpoint or is uniform across all traffic. A single slow endpoint points to a code or query issue; uniform elevation points to infrastructure (network, instance sizing, or a noisy-neighbor effect).

## Remediation Decision
- **Below alert threshold** (this is the common case, e.g. 420ms/500ms): informational only. No remediation action. Continue monitoring; do not page anyone.
- **Above alert threshold, uniform across traffic**: treat as a capacity issue — evaluate whether to scale the affected tier.
- **Above alert threshold, isolated to one endpoint or correlated with a specific downstream dependency**: this needs code-level or dependency-level investigation, not infrastructure remediation. Escalate to human.

## Remediation Actions (auto-approved cases only)
1. If uniform elevation above threshold and correlated with traffic growth: same auto-scaling action as the CPU runbook — add capacity to the affected tier.
2. Below-threshold informational alarms take no action beyond logging the observation for trend tracking.

## Escalation Path
Escalate to on-call human if:
- Latency crosses threshold and is isolated to a specific endpoint or downstream dependency (needs investigation an auto-remediation can't do)
- Latency remains elevated after a scaling action, suggesting the bottleneck isn't capacity

## Notes
Approaching-but-not-crossing-threshold alarms are the most common alert this system will see and are correctly handled by taking no action. Resist the temptation to "do something" — the runbook is explicit that below-threshold is informational only.
