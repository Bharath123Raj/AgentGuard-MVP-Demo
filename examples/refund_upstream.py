"""Mock MCP payment provider for local demos. Never issues a real refund."""
import uuid

from mcp.server import MCPServer
from pydantic import BaseModel

server = MCPServer("Mock Payments")


class MockRefund(BaseModel):
    transaction_id: str
    customer_id: str
    amount: float
    mock: bool


@server.tool()
def refund(customer_id: str, amount: float) -> MockRefund:
    """Make a pretend refund and return a fake transaction ID."""
    return MockRefund(transaction_id=str(uuid.uuid4()), customer_id=customer_id,
                      amount=amount, mock=True)


if __name__ == "__main__":
    server.run(transport="streamable-http", host="127.0.0.1", port=8001)
