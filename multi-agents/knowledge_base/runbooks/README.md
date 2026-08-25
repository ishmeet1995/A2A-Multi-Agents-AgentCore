# Knowledge Base Source Documents

Six runbooks, one per alarm metric, ready to upload to S3 and index as a
Bedrock Knowledge Base once the AWS account is verified.

## Files
| File | Metric | Auto-remediation? |
|---|---|---|
| `cpu-utilization-high.md` | `CPUUtilization` | Yes, conditional |
| `disk-space-low.md` | `DiskSpaceUtilization` | Never — always escalate |
| `latency-elevated.md` | `Latency` | Informational only (common case) |
| `memory-utilization-high.md` | `MemoryUtilization` | Yes, conditional (stopgap only) |
| `error-rate-5xx-elevated.md` | `5xxErrorRate` | Never — always escalate |
| `queue-backlog-high.md` | `ApproximateAgeOfOldestMessage` | Yes, conditional |

Deliberately mixed: some metrics always escalate, some are conditional,
one is usually a no-op. This gives the diagnose node in `agent.py`
real decisions to make instead of a rubber-stamp "remediate everything."

## S3 upload plan (Step 2)
```
s3://<your-bucket>/runbooks/cpu-utilization-high.md
s3://<your-bucket>/runbooks/disk-space-low.md
s3://<your-bucket>/runbooks/latency-elevated.md
s3://<your-bucket>/runbooks/memory-utilization-high.md
s3://<your-bucket>/runbooks/error-rate-5xx-elevated.md
s3://<your-bucket>/runbooks/queue-backlog-high.md
```
```bash
aws s3 cp . s3://<your-bucket>/runbooks/ --recursive --exclude "README.md"
```

## Chunking strategy — decide this before creating the KB
Each runbook is a self-contained decision document (~300-400 words). Default
Bedrock KB fixed-size chunking (300 tokens, 20% overlap) would likely split
a single runbook's "Diagnosis Steps" from its "Remediation Decision" across
two chunks — bad for retrieval, since the model needs both together to
reason correctly.

**Recommendation:** use a larger fixed chunk size (e.g. 1000+ tokens) so
each runbook stays whole in one chunk, or use Bedrock KB's "no chunking"
option and rely on the section headers (`## Trigger Conditions`, etc.) for
structure within each retrieved document. Six short, complete documents are
easier to retrieve correctly than fragments of them.

## Retrieval test cases for later
Once the KB exists, these are the queries to sanity-check retrieval quality
against (should each surface the matching runbook, not a wrong one):
- "CPU is at 91% on a web instance, what should I check first?"
- "database disk is almost full, can I auto-remediate?"
- "latency is close to threshold but hasn't crossed it"
- "a container's memory has been climbing steadily since yesterday's deploy"
- "getting 5xx errors right after a deployment"
- "SQS oldest message age is over an hour"
