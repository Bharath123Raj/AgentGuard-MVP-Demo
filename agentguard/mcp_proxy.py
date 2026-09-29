"""MCP-to-MCP refund proxy. Only the configured upstream can receive calls."""
import math
import os
import re
from typing import Any

import httpx
from mcp import Client
from mcp.server import MCPServer


CUSTOMER_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def create_mcp_proxy(*, gateway_url: str, agent_key: str,
                     upstream: str | MCPServer,
                     gateway_client: httpx.AsyncClient | None = None) -> MCPServer:
    """Return an MCP server with a single allowlisted downstream tool.

    In production `upstream` is an operator-configured MCP URL; callers never
    provide a destination. Keep that upstream unreachable from untrusted agents.
    """
    if not gateway_url or not agent_key or upstream is None:
        raise ValueError("Gateway URL, agent key, and upstream are required")
    server = MCPServer("AgentGuard Protected Payments")

    @server.tool()
    async def refund(customer_id: str, amount: float, approval_id: str | None = None,
                     source_text: str = "") -> dict[str, Any]:
        """Request a protected refund; large refunds return an approval ID."""
        if not CUSTOMER_ID.fullmatch(customer_id):
            raise ValueError("Invalid customer ID")
        if not math.isfinite(amount) or amount <= 0 or amount > 100000:
            raise ValueError("Invalid refund amount")

        request = {"tool": "payments.refund", "resource": f"customer/{customer_id}",
                   "arguments": {"amount": amount}, "source_text": source_text}
        if approval_id is not None:
            request["approval_id"] = approval_id

        if gateway_client is None:
            async with httpx.AsyncClient(base_url=gateway_url, timeout=5.0) as client:
                response = await client.post("/v1/authorize", json=request,
                                             headers={"X-Agent-Key": agent_key})
        else:
            response = await gateway_client.post("/v1/authorize", json=request,
                                                 headers={"X-Agent-Key": agent_key})
        response.raise_for_status()  # fail closed; never call upstream on network errors
        verdict = response.json()
        if verdict["decision"] == "REQUIRE_APPROVAL":
            return {"status": "REQUIRE_APPROVAL", "approval_id": verdict["approval_id"],
                    "reason": verdict["reason"], "executed": False}
        if verdict["decision"] != "ALLOW":
            return {"status": "DENY", "reason": verdict["reason"], "executed": False}

        # The gateway policy evaluated these exact arguments; the agent cannot
        # choose the upstream URL, tool name, resource, or forwarded arguments.
        async with Client(upstream) as provider:
            result = await provider.call_tool("refund", {"customer_id": customer_id,
                                                         "amount": amount})
        if result.is_error:
            raise RuntimeError("Upstream refund tool failed; inspect the provider")
        if result.structured_content is None:
            raise RuntimeError("Upstream refund tool must provide structured output")
        return {"status": "ALLOW", "executed": True,
                "provider_result": result.structured_content}

    return server


def run_from_env() -> None:
    gateway_url = os.environ.get("AGENTGUARD_GATEWAY_URL", "http://127.0.0.1:8000")
    agent_key = os.environ.get("AGENTGUARD_MCP_AGENT_KEY")
    upstream_url = os.environ.get("AGENTGUARD_REFUND_MCP_URL")
    if not agent_key or not upstream_url:
        raise RuntimeError("Set AGENTGUARD_MCP_AGENT_KEY and AGENTGUARD_REFUND_MCP_URL")
    create_mcp_proxy(gateway_url=gateway_url, agent_key=agent_key,
                     upstream=upstream_url).run(transport="stdio")


if __name__ == "__main__":
    run_from_env()
