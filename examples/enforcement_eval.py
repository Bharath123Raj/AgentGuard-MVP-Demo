"""Deterministic agent tool-call probes, separate from live-model evaluation.

The scripted model intentionally requests each fixture's tool call. Results
measure gateway enforcement when a call is attempted, not attack frequency or
resistance of a real LLM to prompt injection.
"""
import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from agentguard.api import create_app
from agentguard.support_agent import SupportAgent


class ScriptedAttempt:
    def __init__(self, tool: str, arguments: dict):
        self.tool, self.arguments = tool, arguments

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        if any(message["role"] == "tool" for message in messages):
            return {"role": "assistant", "content": "Tool result received."}
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "probe-call", "type": "function", "function": {
                "name": self.tool, "arguments": json.dumps(self.arguments)}}]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run scripted tool-call enforcement probes")
    parser.add_argument("--cases", default="data/enforcement_probes.jsonl")
    parser.add_argument("--out", default="reports/enforcement_eval.json")
    args = parser.parse_args()
    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if not cases:
        parser.error("Probe file is empty")

    results = []
    for case in cases:
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(identities=[{"key": "probe-support-key", "agent_id": "support-probe",
                                          "role": "support_agent"}],
                             admin_key="probe-admin-key", secret="probe-signing-secret",
                             db_path=f"{directory}/probe.db")
            with TestClient(app) as gateway:
                agent = SupportAgent(model=ScriptedAttempt(case["tool"], case["arguments"]),
                                     gateway_url="http://guard.test", agent_key="probe-support-key",
                                     gateway_client=gateway)
                outcome = agent.run(case["ticket"])
                counts = gateway.get("/v1/support/mock-counts",
                                     headers={"X-Admin-Key": "probe-admin-key"}).json()
                trace = outcome["trace"]
                decision = trace[0]["decision"] if len(trace) == 1 else "MISSING_OR_EXTRA_CALLS"
                expected_effect = case["expect_decision"] == "ALLOW"
                effect = bool(counts["refunds"] or counts["messages"])
                passed = decision == case["expect_decision"] and effect == expected_effect
                results.append({"id": case["id"], "kind": case["kind"],
                                "attempted_tool": case["tool"],
                                "expected_decision": case["expect_decision"],
                                "actual_decision": decision, "trace": trace,
                                "mock_actions": counts, "passed": passed})
                print(f"{case['id']}: {'PASS' if passed else 'FAIL'} ({decision})")

    unsafe = [case for case in results if case["kind"] == "unsafe"]
    report = {"title": "AgentGuard deterministic attempted-tool enforcement probes",
              "generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "limitations": ["All tool calls are scripted and guaranteed to be attempted.",
                              "Fixtures were authored with the prototype, not independently held out.",
                              "No model provider, real payment, or real message service is involved."],
              "summary": {"cases": len(results), "passed": sum(c["passed"] for c in results),
                          "unsafe_attempts": len(unsafe),
                          "unsafe_denied": sum(c["actual_decision"] == "DENY" for c in unsafe),
                          "unsafe_effects_executed": sum(bool(c["mock_actions"]["refunds"] or
                                                            c["mock_actions"]["messages"]) for c in unsafe)},
              "cases": results}
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), **report["summary"]}, indent=2))
    return 0 if all(c["passed"] for c in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
