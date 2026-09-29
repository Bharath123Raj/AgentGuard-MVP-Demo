"""Run with: python examples/demo.py (after pip install -e .[test])."""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from agentguard.api import create_app
from agentguard.sdk import AgentGuard, ActionDenied, ApprovalRequired


with TemporaryDirectory() as directory:
    app = create_app(identities=[
        {"key": "demo-finance-key", "agent_id": "finance-demo", "role": "finance"},
        {"key": "demo-analytics-key", "agent_id": "analytics-demo", "role": "analytics"},
    ], admin_key="demo-admin-key", secret="demo-signing-secret", db_path=f"{directory}/guard.db")
    with TestClient(app) as client:
        guard = AgentGuard(agent_key="demo-finance-key", client=client)
        refunds = []

        def issue_refund():
            refunds.append({"customer": "customer/42", "amount": 2500})
            return "Refund issued"

        try:
            guard.run(tool="payments.refund", resource="customer/42",
                      arguments={"amount": 2500}, execute=issue_refund)
        except ApprovalRequired as pending:
            print("Approval required:", pending.approval_id, "refunds executed:", len(refunds))
            client.post(f"/v1/approvals/{pending.approval_id}",
                        json={"decision": "APPROVED"}, headers={"X-Admin-Key": "demo-admin-key"}).raise_for_status()
            print(guard.run(tool="payments.refund", resource="customer/42",
                            arguments={"amount": 2500}, execute=issue_refund,
                            approval_id=pending.approval_id))

        try:
            guard.run(tool="db.delete", resource="production/customers",
                      arguments={}, execute=lambda: print("THIS MUST NOT RUN"))
        except ActionDenied as error:
            print("Blocked:", error)

        payload = {"tool": "payments.refund", "resource": "customer/99", "arguments": {"amount": 3500}}
        headers = {"X-Agent-Key": "demo-finance-key"}
        pending = client.post("/v1/demo/refunds", json=payload, headers=headers).json()
        print("Gateway-owned mock refund before approval:", pending["executed"])
        client.post(f"/v1/approvals/{pending['approval_id']}",
                    json={"decision": "APPROVED"}, headers={"X-Admin-Key": "demo-admin-key"}).raise_for_status()
        approved = client.post("/v1/demo/refunds", json={**payload, "approval_id": pending["approval_id"]},
                               headers=headers).json()
        print("Gateway-owned mock refund after approval:", approved["executed"])

        print("Audit chain valid:", client.get("/v1/events", headers={"X-Admin-Key": "demo-admin-key"}).json()["chain_valid"])
