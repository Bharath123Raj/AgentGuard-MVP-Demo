"""Policy and input signals. Explicit authorization rules always take priority."""
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any


ROLE_TOOLS = {
    "finance": {"payments.refund": "customer/"},
    "analytics": {"db.read": "public/"},
    "support": {"email.send": "customer/"},
    "support_agent": {"orders.lookup": "order/", "payments.refund": "customer/",
                      "email.send": "customer/"},
}
INJECTION = re.compile(
    r"(?:ignore (?:all )?(?:previous|prior) instructions|"
    r"(?:reveal|retrieve|read|send|exfiltrate).{0,90}(?:credentials|api[ _-]?key|secret|\.aws)|"
    r"(?:disable|bypass).{0,50}(?:guard|security|policy))",
    re.I | re.S,
)
SECRET = re.compile(
    r"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b|"
    r"(?:password|api[ _-]?key|secret)\s*[:=]\s*[^\s,;]{8,})",
    re.I,
)


def fingerprint(secret: str, agent_id: str, action: dict[str, Any]) -> str:
    canonical = json.dumps({"agent_id": agent_id, "action": action}, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Verdict:
    decision: str
    reason: str
    risk_score: float
    signals: list[str]


def evaluate(role: str, action: dict[str, Any]) -> Verdict:
    tool = action["tool"]
    resource = action["resource"]
    args = action["arguments"]
    prefix = ROLE_TOOLS.get(role, {}).get(tool)
    if prefix is None or not resource.startswith(prefix) or len(resource) <= len(prefix):
        return Verdict("DENY", "Tool or resource is outside this agent's permissions", 1.0, ["permission_denied"])

    source_text = action.get("source_text", "")
    if INJECTION.search(source_text):
        return Verdict("DENY", "Suspicious instruction in untrusted source text", 0.95, ["injection_pattern"])
    # Outbound content must not contain credentials; arguments never enter audit records.
    if tool == "email.send" and (SECRET.search(source_text) or
                                 SECRET.search(json.dumps(args, ensure_ascii=False))):
        return Verdict("DENY", "Possible secret in outbound content", 0.95, ["secret_pattern"])

    if tool == "payments.refund":
        amount = args.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not (0 < amount <= 100000):
            return Verdict("DENY", "Refund amount must be between 0 and 100000", 0.8, ["invalid_amount"])
        if amount > 2000:
            return Verdict("REQUIRE_APPROVAL", "Refund above 2000 requires approval", 0.6, ["high_refund"])
    return Verdict("ALLOW", "Permitted by role and resource policy", 0.1, [])
