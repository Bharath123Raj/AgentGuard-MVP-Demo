"""Run a model-driven support ticket against the protected local gateway.

Example (with a tool-capable OpenAI-compatible endpoint configured):
python examples/run_support_agent.py --ticket 'Look up order O-100.'
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentguard.support_agent import CompatibleChatModel, SupportAgent


def main():
    parser = argparse.ArgumentParser(description="Run a protected synthetic support ticket")
    parser.add_argument("--ticket", required=True, help="Ticket text; use only synthetic data")
    parser.add_argument("--approval-id", help="Retry the identical ticket after human approval")
    args = parser.parse_args()
    model = os.environ.get("AGENTGUARD_CHAT_MODEL")
    key = os.environ.get("AGENTGUARD_SUPPORT_AGENT_KEY")
    if not model or not key:
        parser.error("Set AGENTGUARD_CHAT_MODEL and AGENTGUARD_SUPPORT_AGENT_KEY first")
    chat = CompatibleChatModel(
        url=os.environ.get("AGENTGUARD_CHAT_URL", "http://127.0.0.1:11434/v1/chat/completions"),
        model=model, api_key=os.environ.get("AGENTGUARD_CHAT_API_KEY"),
    )
    agent = SupportAgent(model=chat,
        gateway_url=os.environ.get("AGENTGUARD_GATEWAY_URL", "http://127.0.0.1:8000"),
        agent_key=key)
    result = agent.run(args.ticket, approval_id=args.approval_id)
    result.pop("model_answer", None)  # Keep untrusted model prose out of operator output.
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
