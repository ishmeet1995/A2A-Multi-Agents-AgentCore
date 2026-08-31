# Notification Agent (AgentCore Harness)

The third agent in the project — deliberately simple, which is exactly
where Harness fits: no branching logic, no explicit state machine needed.
Given an escalation, format it and send it. A model-driven loop is
completely adequate for a task this linear; LangGraph's explicit-graph
overhead wouldn't buy anything here.

## Part 1: Deploy the Lambda (works right now, no Bedrock needed)

```bash
cd notification_lambda
zip function.zip lambda_function.py

aws lambda create-function \
  --function-name send-escalation-notification \
  --runtime python3.12 \
  --role arn:aws:iam::<account-id>:role/<a-basic-lambda-execution-role> \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://function.zip \
  --region us-east-1
```

If you don't have a Lambda execution role yet, create a minimal one first:
```bash
aws iam create-role \
  --role-name notification-lambda-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
  }'

aws iam attach-role-policy \
  --role-name notification-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

Test it directly (still no Bedrock involved):
```bash
aws lambda invoke \
  --function-name send-escalation-notification \
  --payload '{"alarm_name":"disk-space-low-db-02","reason":"test","severity":"critical"}' \
  --cli-binary-format raw-in-base64-out \
  response.json
cat response.json
```

## Part 2: Create the Harness (needs InvokeModel access — do this once unblocked)

Fastest path is the AgentCore CLI:
```bash
agentcore harness create \
  --name notification-agent \
  --model bedrock/amazon.nova-micro-v1:0 \
  --system-prompt "You format and send escalation notifications for cloud ops alarms. Given an alarm name, reason, and severity, call the send_notification tool with a clear, concise message. Always call the tool — never just describe what you would send." \
  --execution-role arn:aws:iam::<account-id>:role/AgentCoreExecutionRole
```

Then attach the Lambda as a tool via Gateway (the CLI wizard will prompt
for this, or use `agentcore add gateway` — this wraps the Lambda so the
harness can call it in its tool-use loop).

## Part 3: Wire it into the Remediation Agent

`remediation_agent_langgraph/tools.py`'s `escalate_to_human()` becomes a
real InvokeHarness call instead of a mock — see the updated version below.
Falls back to the mock automatically if the harness isn't reachable, so
local testing keeps working without AWS.
