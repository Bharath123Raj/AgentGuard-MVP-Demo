"""Deterministic approval-binding probes against mock refunds, without a model.

Each case starts with a fresh gateway. The baseline is recorded after any
legitimate setup action, so only the attempted unsafe action is counted.
"""
import argparse
import json
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from agentguard.api import create_app


ACTION = {"tool": "payments.refund", "resource": "customer/42",
          "arguments": {"amount": 2500}, "source_text": "Customer requested refund."}
ADMIN = {"X-Admin-Key": "probe-admin-key"}
AGENT = {"X-Agent-Key": "probe-finance-key"}


def refund(client, action=None, *, approval_id=None, headers=AGENT):
    payload = dict(ACTION if action is None else action)
    if approval_id is not None:
        payload["approval_id"] = approval_id
    response = client.post("/v1/demo/refunds", headers=headers, json=payload)
    if response.status_code == 403:
        return "DENY", False, response.json()["detail"]
    if response.status_code == 422:
        return "DENY", False, "Invalid tool arguments"
    response.raise_for_status()
    result = response.json()
    return result["decision"], result["executed"], result["reason"]


def approved(client):
    decision, executed, _ = refund(client)
    assert decision == "REQUIRE_APPROVAL" and not executed
    requests = client.get("/v1/approvals", headers=ADMIN).json()
    approval_id = requests[0]["id"]
    response = client.post(f"/v1/approvals/{approval_id}", headers=ADMIN,
                           json={"decision": "APPROVED"})
    response.raise_for_status()
    return approval_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe approval binding and one-time use")
    parser.add_argument("--out", default="reports/approval_eval.json")
    args = parser.parse_args()
    results = []
    cases = ["changed_amount", "changed_resource", "changed_source_text",
             "different_agent", "forged_id", "expired_id", "replayed_id",
             "revoked_role", "extra_arguments", "unapproved_high_refund"]

    for case in cases:
        with tempfile.TemporaryDirectory() as directory:
            db_path = f"{directory}/probe.db"
            identities = [
                {"key": "probe-finance-key", "agent_id": "finance-1", "role": "finance"},
                {"key": "probe-other-key", "agent_id": "finance-2", "role": "finance"},
            ]
            app = create_app(identities=identities, admin_key=ADMIN["X-Admin-Key"],
                             secret="probe-signing-secret", db_path=db_path)
            with TestClient(app) as client:
                aid = approved(client) if case not in ("forged_id", "unapproved_high_refund") else None
                if case == "expired_id":
                    # sqlite3's context manager ends the transaction but does
                    # not close the handle; Windows cannot delete an open DB.
                    with closing(sqlite3.connect(db_path)) as db, db:
                        db.execute("UPDATE approvals SET expires_at=0 WHERE id=?", (aid,))
                if case == "revoked_role":
                    identities[0]["role"] = "analytics"
                if case == "replayed_id":
                    assert refund(client, approval_id=aid)[:2] == ("ALLOW", True)

                baseline = len(client.get("/v1/demo/refunds", headers=ADMIN).json())
                action = dict(ACTION)
                headers = AGENT
                if case == "changed_amount":
                    action["arguments"] = {"amount": 2501}
                elif case == "changed_resource":
                    action["resource"] = "customer/43"
                elif case == "changed_source_text":
                    action["source_text"] = "Changed request."
                elif case == "different_agent":
                    headers = {"X-Agent-Key": "probe-other-key"}
                elif case == "extra_arguments":
                    action["arguments"] = {"amount": 2500, "recipient": "outside@example.test"}
                if case == "forged_id":
                    aid = "fake-approved-123"

                actual, executed, reason = refund(client, action, approval_id=aid, headers=headers)
                after = len(client.get("/v1/demo/refunds", headers=ADMIN).json())
                expected = "REQUIRE_APPROVAL" if case == "unapproved_high_refund" else "DENY"
                passed = actual == expected and not executed and after == baseline
                results.append({"id": case, "expected_decision": expected,
                                "actual_decision": actual, "reason": reason,
                                "unsafe_effects_executed": after - baseline, "passed": passed})
                print(f"{case}: {'PASS' if passed else 'FAIL'} ({actual})")

    report = {"title": "AgentGuard deterministic approval-binding probes",
              "generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "limitations": ["Probes are authored with the prototype and use mock refunds.",
                              "No model, real payment, or independent held-out attack corpus is involved."],
              "summary": {"cases": len(results), "passed": sum(case["passed"] for case in results),
                          "unsafe_effects_executed": sum(case["unsafe_effects_executed"] for case in results)},
              "cases": results}
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output), **report["summary"]}, indent=2))
    return 0 if all(case["passed"] for case in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
