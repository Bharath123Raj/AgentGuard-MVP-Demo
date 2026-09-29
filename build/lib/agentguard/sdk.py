"""Small synchronous SDK. The application must keep protected tools behind this call."""
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

T = TypeVar("T")


class ActionDenied(RuntimeError):
    pass


class ApprovalRequired(RuntimeError):
    def __init__(self, approval_id: str, reason: str):
        self.approval_id = approval_id
        super().__init__(f"{reason} (approval_id={approval_id})")


class AgentGuard:
    def __init__(self, *, agent_key: str, base_url: str = "http://127.0.0.1:8000",
                 client: httpx.Client | None = None):
        self.agent_key = agent_key
        self.client = client or httpx.Client(base_url=base_url, timeout=5.0)

    def run(self, *, tool: str, resource: str, arguments: dict[str, Any],
            execute: Callable[[], T], source_text: str = "",
            approval_id: str | None = None) -> T:
        payload = {"tool": tool, "resource": resource, "arguments": arguments,
                   "source_text": source_text}
        if approval_id:
            payload["approval_id"] = approval_id
        response = self.client.post("/v1/authorize", json=payload,
                                    headers={"X-Agent-Key": self.agent_key})
        response.raise_for_status()  # fail closed if gateway is unavailable
        result = response.json()
        if result["decision"] == "REQUIRE_APPROVAL":
            raise ApprovalRequired(result["approval_id"], result["reason"])
        if result["decision"] != "ALLOW":
            raise ActionDenied(result["reason"])
        return execute()
