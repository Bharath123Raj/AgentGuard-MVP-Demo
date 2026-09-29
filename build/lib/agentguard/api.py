"""AgentGuard policy decision API. Tool execution stays with the SDK caller."""
import base64
import hmac
import json
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .core import evaluate, fingerprint
from .store import Store
from .support import SupportLab


def validate_sandbox_config(identities: list[dict[str, str]], admin_key: str,
                            secret: str, db_path: str) -> None:
    """Reject development credentials in the container's sandbox profile."""
    keys = [admin_key, secret, *(entry["key"] for entry in identities)]
    if any(len(key) < 32 or "change" in key.lower() or "demo" in key.lower()
           or "replace" in key.lower() for key in keys):
        raise ValueError("Sandbox keys and signing secret must be unique, random, and at least 32 characters")
    if len(set(keys)) != len(keys):
        raise ValueError("Sandbox keys and signing secret must be distinct")
    if not Path(db_path).is_absolute() or db_path == ":memory:":
        raise ValueError("Sandbox database path must be absolute and persistent")


class Action(BaseModel):
    tool: str = Field(min_length=1, max_length=100)
    resource: str = Field(min_length=1, max_length=300)
    arguments: dict[str, Any] = Field(default_factory=dict)
    source_text: str = Field(default="", max_length=10000)
    approval_id: str | None = None


class Review(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]


class SupportLookup(BaseModel):
    order_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    source_text: str = Field(default="", max_length=10000)


class SupportRefund(SupportLookup):
    amount: float = Field(gt=0, le=100000, allow_inf_nan=False)
    approval_id: str | None = None


class SupportMessage(SupportLookup):
    model_config = ConfigDict(extra="forbid")
    recipient: str = Field(min_length=3, max_length=254)


def create_app(*, identities: list[dict[str, str]] | None = None,
               admin_key: str | None = None, secret: str | None = None,
               db_path: str | None = None) -> FastAPI:
    if identities is None:
        identities = json.loads(os.environ.get("AGENTGUARD_IDENTITIES", "[]"))
    admin_key = admin_key or os.environ.get("AGENTGUARD_ADMIN_KEY")
    secret = secret or os.environ.get("AGENTGUARD_SIGNING_SECRET")
    db_path = db_path or os.environ.get("AGENTGUARD_DB_PATH", "data/agentguard.db")
    if not identities or not admin_key or not secret:
        raise RuntimeError("Set identities, admin key, and signing secret before startup")
    if any(not all(i.get(k) for k in ("key", "agent_id", "role")) for i in identities):
        raise ValueError("Each identity needs key, agent_id, and role")
    if len({i["agent_id"] for i in identities}) != len(identities) or len({i["key"] for i in identities}) != len(identities):
        raise ValueError("Agent IDs and keys must be unique")
    deployment_mode = os.environ.get("AGENTGUARD_DEPLOYMENT_MODE", "local")
    if deployment_mode not in {"local", "sandbox"}:
        raise ValueError("AGENTGUARD_DEPLOYMENT_MODE must be local or sandbox")
    if deployment_mode == "sandbox":
        validate_sandbox_config(identities, admin_key, secret, db_path)
    staging_password = os.environ.get("AGENTGUARD_STAGING_PASSWORD")
    if os.environ.get("AGENTGUARD_REQUIRE_STAGING_PASSWORD") == "1" and not staging_password:
        raise ValueError("Staging access password is required")
    if staging_password:
        if deployment_mode != "sandbox" or len(staging_password) < 32 or staging_password in (
                admin_key, secret, *(entry["key"] for entry in identities)):
            raise ValueError("Staging password requires sandbox mode and a distinct 32-character value")
    store = Store(db_path, secret)
    support = SupportLab(store)
    app = FastAPI(title="AgentGuard MVP", version="0.10.0")
    if staging_password:
        expected = "Basic " + base64.b64encode(f"reviewer:{staging_password}".encode()).decode()

        @app.middleware("http")
        async def staging_access(request, call_next):
            if request.url.path != "/ready" and not hmac.compare_digest(
                    request.headers.get("authorization", ""), expected):
                return Response(status_code=401, headers={
                    "WWW-Authenticate": 'Basic realm="AgentGuard staging"',
                    "Cache-Control": "no-store",
                })
            return await call_next(request)
    web_dir = Path(__file__).parent / "web"
    app.mount("/dashboard/assets", StaticFiles(directory=str(web_dir)), name="dashboard-assets")

    @app.get("/", include_in_schema=False)
    def homepage():
        return RedirectResponse("/dashboard")

    @app.get("/dashboard", include_in_schema=False)
    def dashboard():
        return FileResponse(web_dir / "index.html", headers={
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        })

    def agent(x_agent_key: str | None = Header(default=None)) -> dict[str, str]:
        for entry in identities:
            if x_agent_key and hmac.compare_digest(x_agent_key, entry["key"]):
                return entry
        raise HTTPException(401, "Invalid agent key")

    def admin(x_admin_key: str | None = Header(default=None)) -> None:
        if not x_admin_key or not hmac.compare_digest(x_admin_key, admin_key):
            raise HTTPException(401, "Invalid admin key")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        try:
            with store._connect() as db:
                db.execute("SELECT 1 FROM events LIMIT 1").fetchone()
                db.execute("SELECT 1 FROM support_orders LIMIT 1").fetchone()
        except Exception:
            raise HTTPException(503, "Database unavailable") from None
        return {"status": "ready"}

    def decide_action(request: Action, identity: dict[str, str]):
        action = request.model_dump(exclude={"approval_id"})
        if len(json.dumps(action, ensure_ascii=False)) > 32768:
            raise HTTPException(413, "Action exceeds size limit")
        try:
            digest = fingerprint(secret, identity["agent_id"], action)
        except (TypeError, ValueError):
            raise HTTPException(422, "Arguments must be finite JSON values")
        verdict = evaluate(identity["role"], action)
        decision, reason = verdict.decision, verdict.reason
        approval_id = None

        if request.approval_id:
            # A changed policy or revoked role still blocks a previously approved action.
            if decision == "DENY":
                pass
            elif store.redeem(request.approval_id, identity["agent_id"], digest):
                decision, reason = "ALLOW", "Matching approval consumed"
            else:
                decision, reason = "DENY", "Approval missing, expired, used, or bound to another action"
        elif decision == "REQUIRE_APPROVAL":
            amount = request.arguments.get("amount") if request.tool == "payments.refund" else None
            approval_id = store.create_approval(identity["agent_id"], digest, request.tool,
                                                request.resource, amount)

        store.event(identity["agent_id"], request.tool, request.resource, decision, reason)
        return {"agent_id": identity["agent_id"], "decision": decision,
                "reason": reason, "risk_score": verdict.risk_score,
                "signals": verdict.signals, "approval_id": approval_id}

    @app.post("/v1/authorize")
    def authorize(request: Action, identity: dict[str, str] = Depends(agent)):
        return decide_action(request, identity)

    @app.post("/v1/demo/refunds")
    def execute_demo_refund(request: Action, identity: dict[str, str] = Depends(agent)):
        """A server-owned mock payment action; callers cannot invoke the mock tool directly."""
        if request.tool != "payments.refund" or set(request.arguments) != {"amount"}:
            raise HTTPException(422, "Demo refund requires tool payments.refund and only amount")
        outcome = decide_action(request, identity)
        if outcome["decision"] == "REQUIRE_APPROVAL":
            return {"executed": False, **outcome}
        if outcome["decision"] != "ALLOW":
            raise HTTPException(403, outcome["reason"])
        result = store.demo_refund(identity["agent_id"], request.resource,
                                   request.arguments["amount"])
        return {"executed": True, "refund": result, **outcome}

    @app.get("/v1/demo/refunds")
    def list_demo_refunds(_: None = Depends(admin)):
        return store.demo_refunds()

    def support_order(order_id: str, identity: dict[str, str]):
        if identity["role"] != "support_agent":
            raise HTTPException(403, "Support workflow requires support_agent role")
        order = support.order(order_id)
        if order is None:
            raise HTTPException(404, "Order not found")
        return order

    def business_deny(identity: dict[str, str], tool: str, resource: str, reason: str):
        store.event(identity["agent_id"], tool, resource, "DENY", reason)
        raise HTTPException(403, reason)

    @app.post("/v1/support/orders/lookup")
    def lookup_order(request: SupportLookup, identity: dict[str, str] = Depends(agent)):
        order = support_order(request.order_id, identity)
        action = Action(tool="orders.lookup", resource=f"order/{order['id']}",
                        arguments={"order_id": order["id"]}, source_text=request.source_text)
        verdict = decide_action(action, identity)
        if verdict["decision"] != "ALLOW":
            raise HTTPException(403, verdict["reason"])
        return {"executed": True, "order": order, **verdict}

    @app.post("/v1/support/refunds")
    def support_refund(request: SupportRefund, identity: dict[str, str] = Depends(agent)):
        order = support_order(request.order_id, identity)
        resource = f"customer/{order['customer_id']}"
        if order["refunded"]:
            business_deny(identity, "payments.refund", resource, "Order was already refunded")
        if request.amount > order["total"]:
            business_deny(identity, "payments.refund", resource, "Refund exceeds the order total")
        action = Action(tool="payments.refund", resource=resource,
                        arguments={"order_id": order["id"], "amount": request.amount},
                        source_text=request.source_text, approval_id=request.approval_id)
        verdict = decide_action(action, identity)
        if verdict["decision"] == "REQUIRE_APPROVAL":
            return {"executed": False, **verdict}
        if verdict["decision"] != "ALLOW":
            raise HTTPException(403, verdict["reason"])
        result = support.refund(order["id"], request.amount)
        if result is None:
            store.event(identity["agent_id"], action.tool, resource,
                        "EXECUTION_FAILED", "Order state changed before execution")
            raise HTTPException(409, "Order state changed before execution")
        store.event(identity["agent_id"], action.tool, resource, "EXECUTED", "Mock refund recorded")
        return {"executed": True, "refund": result, **verdict}

    @app.post("/v1/support/messages")
    def support_message(request: SupportMessage, identity: dict[str, str] = Depends(agent)):
        order = support_order(request.order_id, identity)
        resource = f"customer/{order['customer_id']}"
        if request.recipient != order["email"]:
            business_deny(identity, "email.send", resource, "Recipient differs from customer on record")
        body = (f"We received your inquiry about order {order['id']}. "
                "Please contact support for the latest order status.")
        action = Action(tool="email.send", resource=resource,
                        arguments={"order_id": order["id"], "recipient": request.recipient,
                                   "body": body}, source_text=request.source_text)
        verdict = decide_action(action, identity)
        if verdict["decision"] != "ALLOW":
            raise HTTPException(403, verdict["reason"])
        result = support.message(order["id"], request.recipient, body)
        store.event(identity["agent_id"], action.tool, resource, "EXECUTED", "Mock message recorded")
        return {"executed": True, "message": result,
                "template_id": "order_inquiry_acknowledgement", **verdict}

    @app.get("/v1/support/mock-counts")
    def support_counts(_: None = Depends(admin)):
        return support.counts()

    @app.get("/v1/approvals")
    def approvals(_: None = Depends(admin)):
        return store.approvals()

    @app.get("/v1/summary")
    def summary(_: None = Depends(admin)):
        return store.summary()

    @app.post("/v1/approvals/{approval_id}")
    def review(approval_id: str, body: Review, _: None = Depends(admin)):
        row = store.approval(approval_id)
        if row is None:
            raise HTTPException(404, "Approval not found")
        if not store.decide(approval_id, body.decision):
            raise HTTPException(409, "Approval is no longer pending")
        store.event(row["agent_id"], row["tool"], row["resource"], body.decision, "Human review")
        return {"id": approval_id, "status": body.decision}

    @app.get("/v1/events")
    def events(_: None = Depends(admin)):
        return {"chain_valid": store.verify_chain(), "events": store.events()}

    return app


def app_from_env():
    return create_app()
