"""
Structural test — verifies the graph compiles and routes correctly using a
fake LLM, so you don't need ANTHROPIC_API_KEY just to confirm the wiring works.

Run: python test_local.py
"""

from langchain_core.messages import AIMessage

from agent import build_graph


class FakeLLM:
    """Stands in for ChatAnthropic. Returns a scripted diagnosis based on
    which alarm/metric is in the prompt, so we can exercise both branches
    of the conditional edge."""

    def invoke(self, messages):
        prompt = messages[-1].content
        if "CPUUtilization" in prompt:
            text = (
                "CPU is above threshold, consistent with a traffic spike or "
                "runaway process per the runbook.\n"
                "REMEDIATION_NEEDED: CPU sustained above 80% threshold"
            )
        elif "DiskSpaceUtilization" in prompt:
            text = (
                "Disk space is critically low on a database instance; runbook "
                "requires human sign-off, not auto-remediation.\n"
                "REMEDIATION_NEEDED: Disk usage above 90% on db instance"
            )
        else:
            text = (
                "Latency is elevated but has not crossed the alert threshold.\n"
                "INFORMATIONAL_ONLY: within normal operating range"
            )
        return AIMessage(content=text)


def run_case(alarm_name: str):
    app = build_graph(FakeLLM())
    result = app.invoke({"alarm_name": alarm_name})
    print(f"\n=== {alarm_name} ===")
    print("needs_remediation:", result["needs_remediation"])
    print("final_response:", result["final_response"])
    return result


if __name__ == "__main__":
    print("Testing graph structure and routing with a fake LLM...\n")

    r1 = run_case("high-cpu-web-01")          # expect: routed to remediation
    r2 = run_case("disk-space-low-db-02")     # expect: routed to remediation
    r3 = run_case("elevated-latency-api-gw")  # expect: routed to informational

    assert r1["needs_remediation"] is True
    assert r2["needs_remediation"] is True
    assert r3["needs_remediation"] is False
    assert "[STUB A2A CALL]" in r1["final_response"]
    assert "[INFORMATIONAL]" in r3["final_response"]

    print("\n✅ All routing assertions passed. Graph structure is sound.")
