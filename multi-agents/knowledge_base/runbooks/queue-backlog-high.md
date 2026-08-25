# Runbook: Queue Backlog / Message Age

**Metric:** `ApproximateAgeOfOldestMessage`
**Applies to:** SQS queues and similar async processing backlogs

## Trigger Conditions
- Oldest message age > 15 minutes for a queue with a normal end-to-end SLA under 5 minutes
- Severity escalates to **critical** if age exceeds 1 hour, or if the queue depth is also growing (backlog increasing, not just aging)

## Diagnosis Steps
1. Check consumer health first: are the workers/consumers for this queue actually running and processing, or have they stalled/crashed? A stalled consumer fleet is the single most common cause.
2. If consumers are healthy and processing, check whether the incoming message rate has simply exceeded processing capacity (a genuine volume spike) — compare incoming rate vs. processing rate over the alarm window.
3. Check for a "poison message" pattern: a single message that repeatedly fails and gets retried, blocking or slowing the rest of the queue depending on the queue's configuration.

## Remediation Decision
- **Consumers stalled/crashed, no code correlation**: safe to auto-remediate by restarting the consumer fleet.
- **Consumers healthy, genuine volume spike, processing rate below incoming rate**: auto-scaling the consumer fleet is appropriate.
- **Poison message pattern suspected**: do NOT auto-remediate by purging or skipping messages — a human needs to inspect the message content first, since discarding it may mean silent data loss.
- **Consumer crash correlated with a recent deploy**: do not just restart — restarting will likely crash again. Escalate for a rollback decision.

## Remediation Actions (auto-approved cases only)
1. Stalled consumers, no deploy correlation: restart the consumer fleet/ASG.
2. Volume spike, healthy consumers: scale out the consumer fleet.

## Escalation Path
Always escalate if:
- A poison message pattern is suspected (never auto-purge)
- Consumer crashes correlate with a recent deploy
- Backlog remains after one remediation attempt (restart or scale-out didn't resolve it)

## Notes
Queue age and queue depth are different signals — depth alone can be normal for a bursty workload, but rising *age* on the oldest message means something is actually stuck, not just busy. This runbook is keyed on age for that reason.
