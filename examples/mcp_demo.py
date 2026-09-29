"""In-process integration demo: MCP client -> AgentGuard -> mock MCP provider."""
import asyncio
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from mcp import Client
from mcp.server import MCPServer
from pydantic import BaseModel

from agentguard.api import create_app
from agentguard.mcp_proxy import create_mcp_proxy


class MockRefund(BaseModel):
    mock: bool
    customer_id: str
    amount: float


async def main() -> None:
    calls = []
    upstream = MCPServer("Mock Payments")

    @upstream.tool()
    def refund(customer_id: str, amount: float) -> MockRefund:
        """Pretend to refund an account."""
        calls.append((customer_id, amount))
        return MockRefund(mock=True, customer_id=customer_id, amount=amount)

    with TemporaryDirectory() as directory:
        app = create_app(identities=[{"key": "demo-key", "agent_id": "finance-demo", "role": "finance"}],
                         admin_key="demo-admin", secret="demo-secret", db_path=f"{directory}/db.sqlite")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://guard.test") as gateway:
            proxy = create_mcp_proxy(gateway_url="http://guard.test", agent_key="demo-key",
                                     upstream=upstream, gateway_client=gateway)
            async with Client(proxy) as agent:
                pending = (await agent.call_tool("refund", {"customer_id": "42", "amount": 2500})).structured_content
                print("Before approval:", pending, "upstream calls:", len(calls))
                approval_id = pending["approval_id"]
                review = await gateway.post(f"/v1/approvals/{approval_id}",
                                            json={"decision": "APPROVED"},
                                            headers={"X-Admin-Key": "demo-admin"})
                review.raise_for_status()
                approved = (await agent.call_tool("refund", {"customer_id": "42",
                                                              "amount": 2500,
                                                              "approval_id": approval_id})).structured_content
                print("After approval:", approved, "upstream calls:", len(calls))


if __name__ == "__main__":
    asyncio.run(main())
