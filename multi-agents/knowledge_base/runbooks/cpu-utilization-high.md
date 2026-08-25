# Runbook: High CPU Utilization

**Metric:** `CPUUtilization`
**Applies to:** EC2 web/app tier instances (not database instances — see separate runbook if disk-adjacent)

## Trigger Conditions
- CPUUtilization > 80% sustained for 5+ consecutive minutes
- Severity escalates to **critical** if sustained above 90% for 15+ minutes

## Diagnosis Steps
1. Check CloudWatch Logs Insights for the instance over the alarm window — look for a single process consuming disproportionate CPU (a "runaway process" signature: one PID pinned near 100%, others normal).
2. Cross-reference with the load balancer's request count metric for the same window. If request count rose in step with CPU, this is **traffic-driven**, not process-driven.
3. Check whether a deployment or config change landed in the last 30 minutes before the alarm — a bad deploy is a common cause of a runaway process that traffic alone wouldn't explain.

## Remediation Decision
- **Traffic-driven** (request count and CPU rose together, no single runaway process): this is an auto-scaling situation, not a restart situation. Auto-remediation is appropriate.
- **Process-driven, single PID pinned, traffic normal**: safe to attempt an instance restart as auto-remediation.
- **Process-driven, but tied to a recent deploy**: do NOT auto-remediate. A restart will likely recur. Escalate to human for rollback decision.

## Remediation Actions (auto-approved cases only)
1. If traffic-driven: trigger the Auto Scaling Group to add one instance; do not restart the affected instance (it's healthy, just under load).
2. If single runaway process and traffic normal: restart the affected instance via the ASG's `TerminateInstanceInAutoScalingGroup` with `ShouldDecrementDesiredCapacity=false`, so the ASG replaces it cleanly.

## Escalation Path
Escalate to on-call human if:
- The runaway process correlates with a recent deploy (likely code regression, needs a rollback decision a human should make)
- CPU remains above 90% after one remediation attempt
- This is the second CPU alarm on the same instance within 24 hours (may indicate a persistent underlying issue, not a one-off)

## Notes
Never restart a database-adjacent or stateful instance under this runbook — those alarms should route to their own runbook (see disk-space-low.md for database-tier alarms) and always require human sign-off.
