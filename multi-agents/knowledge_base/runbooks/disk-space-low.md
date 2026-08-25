# Runbook: Low Disk Space

**Metric:** `DiskSpaceUtilization`
**Applies to:** Database instances and any stateful storage tier

## Trigger Conditions
- DiskSpaceUtilization > 90%
- Severity is **critical** regardless of how long it's been sustained — disk exhaustion on a database instance can cause write failures with very little warning

## Diagnosis Steps
1. Identify what's consuming space: application logs, database transaction logs/WAL, temp tables, or actual data growth. Check `df -h` breakdown by mount point and the largest files/directories on the volume.
2. Check whether this is a gradual trend (data growth, expected) or a sudden jump (log flood, temp table explosion, likely a bug or runaway job).
3. Check for any backup or maintenance job that may have started recently and could be holding temp space it hasn't released yet.

## Remediation Decision
**This alarm class is always escalated to a human. There is no auto-remediation path.**

Reasoning: deleting files or truncating logs on a database instance without understanding exactly what's being removed risks data loss, breaking replication, or corrupting an in-progress transaction. The cost of a wrong automated guess here is much higher than the cost of a short delay waiting for a human.

## Remediation Actions
None are auto-approved. A human must:
1. Confirm what's consuming the space using the diagnosis steps above.
2. Decide whether to expand the volume (safe, reversible) vs. delete/archive data (requires understanding of retention requirements).
3. If expanding the volume, this can be done live on most managed database services without downtime — prefer this as the default safe action while investigating the root cause.

## Escalation Path
Always escalate immediately. Page on-call with:
- Current disk usage percentage and trend (gradual vs. sudden)
- Breakdown of what's consuming space, if known
- Estimated time until the volume is completely full at current growth rate, if calculable

## Notes
If this is a recurring alarm on the same instance, that's a signal the instance is undersized for its data growth rate and needs a capacity planning conversation — flag this in the escalation even if the immediate alarm is resolved.
