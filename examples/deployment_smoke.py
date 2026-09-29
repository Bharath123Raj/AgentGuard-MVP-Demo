"""Check the local container through HTTP. Only server-owned mock effects are used."""
import argparse
import json
import uuid
from pathlib import Path

import httpx


def credentials(path: Path) -> tuple[str, str, str | None]:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line and not line.startswith("#"):
            key, sep, value = line.partition("=")
            if sep:
                values[key] = value.strip()
    identities = json.loads(values["AGENTGUARD_IDENTITIES"])
    finance = next(entry["key"] for entry in identities if entry["role"] == "finance")
    return finance, values["AGENTGUARD_ADMIN_KEY"], values.get("AGENTGUARD_STAGING_PASSWORD")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    args = parser.parse_args()
    finance_key, admin_key, staging_password = credentials(args.env)
    action = {"tool": "payments.refund", "resource": f"customer/smoke-{uuid.uuid4().hex}",
              "arguments": {"amount": 2501}}
    basic_auth = ("reviewer", staging_password) if staging_password else None
    with httpx.Client(base_url=args.url, timeout=10, trust_env=False, auth=basic_auth) as client:
        assert client.get("/ready").json() == {"status": "ready"}
        assert client.get("/v1/events").status_code == 401
        agent = {"X-Agent-Key": finance_key}
        admin = {"X-Admin-Key": admin_key}
        pending = client.post("/v1/demo/refunds", json=action, headers=agent)
        pending.raise_for_status()
        outcome = pending.json()
        assert outcome["decision"] == "REQUIRE_APPROVAL" and not outcome["executed"]
        review = client.post(f"/v1/approvals/{outcome['approval_id']}",
                             json={"decision": "APPROVED"}, headers=admin)
        review.raise_for_status()
        approved = client.post("/v1/demo/refunds", json={**action, "approval_id": outcome["approval_id"]},
                               headers=agent)
        approved.raise_for_status()
        assert approved.json()["decision"] == "ALLOW" and approved.json()["executed"]
        replay = client.post("/v1/demo/refunds", json={**action, "approval_id": outcome["approval_id"]},
                             headers=agent)
        assert replay.status_code == 403
        events = client.get("/v1/events", headers=admin)
        events.raise_for_status()
        assert events.json()["chain_valid"]
    print("PASS: ready, authentication, approval, one mock refund, replay denial, audit chain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
