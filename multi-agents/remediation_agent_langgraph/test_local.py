"""
Structural test — verifies the Remediation Agent's graph compiles and
routes correctly across all three actions, using a fake LLM.

Run: python test_local.py
"""

from langchain_core.messages import AIMessage

from agent import build_graph


class FakeLLM:
    """Scripted responses keyed on which metric is in the prompt, so we
    exercise all three action branches: restart, scale, escalate."""

    def invoke(self, messages):
        prompt = messages[-1].content
        if "CPUUtilization" in prompt:
            text = "ACTION: RESTART_INSTANCE\nREASONING: Single runaway process, traffic normal, safe to restart per runbook."
        elif "ApproximateAgeOfOldestMessage" in prompt:
            text = "ACTION: SCALE_OUT\nREASONING: Consumers healthy but under-provisioned for current volume per runbook."
        elif "DiskSpaceUtilization" in prompt:
            text = "ACTION: ESCALATE_HUMAN\nREASONING: Disk space alarms are always escalated per runbook, never auto-remediated."
        else:
            text = "ACTION: ESCALATE_HUMAN\nREASONING: Not confident this matches an auto-approved case."
        return AIMessage(content=text)


def run_case(alarm_name: str, metric: str, diagnosis: str):
    app = build_graph(FakeLLM())
    result = app.invoke({"alarm_name": alarm_name, "metric": metric, "diagnosis": diagnosis})
    print(f"\n=== {alarm_name} ({metric}) ===")
    print("decided_action:", result["decided_action"])
    print("final_response:", result["final_response"])
    return result


if __name__ == "__main__":
    print("Testing Remediation Agent graph structure and routing...\n")

    r1 = run_case("high-cpu-web-01", "CPUUtilization", "CPU sustained above threshold, single process")
    r2 = run_case("queue-backlog-orders", "ApproximateAgeOfOldestMessage", "Consumers stalled")
    r3 = run_case("disk-space-low-db-02", "DiskSpaceUtilization", "Disk usage above 90%")

    assert r1["decided_action"] == "RESTART_INSTANCE"
    assert r2["decided_action"] == "SCALE_OUT"
    assert r3["decided_action"] == "ESCALATE_HUMAN"
    assert "[REMEDIATED]" in r1["final_response"]
    assert "[REMEDIATED]" in r2["final_response"]
    assert "[ESCALATED]" in r3["final_response"]

    print("\n✅ All routing assertions passed. Remediation Agent structure is sound.")
