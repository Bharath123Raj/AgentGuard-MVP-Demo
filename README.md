# AgentGuard MVP

An identity-aware decision gateway for AI agent tool calls. The Python SDK asks the gateway before calling a local tool. The gateway returns `ALLOW`, `DENY`, or `REQUIRE_APPROVAL`; an approval is tied to the agent, tool, resource, arguments, and untrusted source text, expires after 15 minutes, and can be used once.

## Run locally

Python 3.10+:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
pytest -q
python examples/demo.py
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` (or use your
existing Python environment). The same `pytest -q` and `python examples/demo.py`
commands work there.

Run a persistent API:

```bash
cp .env.example .env
# Replace every key and the signing secret in .env first.
set -a; source .env; set +a
uvicorn agentguard.api:app_from_env --factory --reload
```

The example environment file can be sourced by bash. The API docs are at `http://127.0.0.1:8000/docs`. Use the sandbox setup below for Docker Compose. Do not expose this development deployment to the public internet.

## Run the local Docker sandbox (Windows PowerShell)

From the extracted project folder, with Docker Desktop running:

```powershell
./scripts/init_sandbox.ps1
docker compose up --build -d
docker compose ps
python examples/deployment_smoke.py
```

The setup script creates `.env` with separate random keys. It refuses to replace
an existing `.env` because the signing secret must stay with the existing audit
database. The container is reachable only at `127.0.0.1:8000`, runs as a
non-root user, and stores the mock actions, approvals, and audit data in the
`guard_data` volume. No Ollama key is needed for this check. If PowerShell
blocks the script, run `powershell -ExecutionPolicy Bypass -File .\scripts\init_sandbox.ps1`
from the project folder; the policy applies to that one child process.

Check persistence after a container restart:

```powershell
docker compose restart gateway
python examples/deployment_smoke.py
```

Each smoke run creates one **mock** refund with a new synthetic customer ID.
Keep `.env` private and back it up with the Docker volume: changing the signing
secret invalidates existing audit-chain verification and approval bindings.
`docker compose down` stops the service while retaining the named volume;
`docker compose down -v` deletes its database. This is a single-instance local
sandbox, not a public or production deployment. The agent-facing SDK decision
endpoint can still be bypassed by a caller that controls its own tool execution;
the smoke check exercises the server-owned mock action instead.

### Run the same sandbox without Docker

In a new extracted folder, run `./scripts/init_sandbox.ps1` once. The script
will stop if `.env` already exists; keep that file and use its existing keys.
In the project folder, start the API in one PowerShell window:

```powershell
Get-Content .env | ForEach-Object {
    $name, $value = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable($name, $value, 'Process')
}
$env:AGENTGUARD_DEPLOYMENT_MODE = 'sandbox'
$env:AGENTGUARD_DB_PATH = Join-Path (Get-Location).Path 'data\sandbox.db'
python -m uvicorn agentguard.api:app_from_env --factory --host 127.0.0.1 --port 8010
```

Open `http://127.0.0.1:8010/dashboard` in a browser. In a second PowerShell
window in the same folder, run
`python examples/deployment_smoke.py --url http://127.0.0.1:8010`.
The dashboard asks for `AGENTGUARD_ADMIN_KEY` from your private `.env` file;
do not paste it into chat. The server has no Ollama dependency for this demo.

## Free hosted demo without Docker

`render.yaml` describes a Render **Free** Python web service with `/ready`
health checks. No payment or persistent disk is required for this mock demo.
The SQLite database is temporary: audit events, approvals, and mock actions
disappear when the service spins down, restarts, or redeploys. It can take about
a minute to wake after inactivity. Keep your lasting evaluation reports on your
computer, and do not present this demo as durable audit storage.

1. Run `./scripts/init_render.ps1` locally to generate `.env.render`. Keep that
   file private; it is ignored by Git. The script refuses to overwrite it so
   the signing secret stays paired with any existing hosted database.
2. Create a private GitHub repository containing this project, including
   `render.yaml` and the synthetic `data/` tickets. Inspect `git status`
   before pushing; never commit `.env`, `.env.render`, real keys, or personal
   ticket data. If you have GitHub CLI installed, from this folder run:

   ```powershell
   git init
   git add .
   git status --short
   git commit -m "AgentGuard free demo"
   gh repo create AgentGuard --private --source . --remote origin --push
   ```

3. In Render, create a Blueprint from that repository and confirm the service
   is on the **Free** plan with no disk or database. When
   prompted for `sync: false` variables, copy these four named values from
   `.env.render`: `AGENTGUARD_IDENTITIES`, `AGENTGUARD_ADMIN_KEY`,
   `AGENTGUARD_SIGNING_SECRET`, and `AGENTGUARD_STAGING_PASSWORD`.
4. After its health check succeeds, run the hosted smoke check from your own
   computer, replacing the example URL with your service's URL:

   ```powershell
   python examples/deployment_smoke.py --env .env.render --url https://YOUR-SERVICE.onrender.com
   ```

The hosted service requires browser HTTP Basic authentication: username
`reviewer`, password `AGENTGUARD_STAGING_PASSWORD` from `.env.render`. The
dashboard then separately asks for `AGENTGUARD_ADMIN_KEY`. The Blueprint fails
startup if the staging password is absent. Only `/ready` is public, and the
payments and messages in this build are mock effects. This shared staging
password is for a controlled demo, not production user management. The Free
service may be suspended under Render's usage limits.

## Streamlit Community Cloud showcase

`streamlit_app.py` runs the **same policy and mock API code in-process** for an
interactive portfolio page. Visitors can try a safe refund, approval pause,
prompt injection denial, unauthorized tool, order lookup, and recipient swap.
Each browser session gets synthetic credentials and a separate temporary SQLite
database. No Ollama key, payment service, or email account is needed.

Run it on your computer:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

For a free public link, push this project to a **public** GitHub repository
without `.env` or `.env.render`; inspect the files before committing. An app
from a private repository is private by default. In
[Streamlit Community Cloud](https://share.streamlit.io/), choose **Create app**,
select your repository and branch, set the main file path to
`streamlit_app.py`, and choose Python 3.12 in Advanced settings. The root
`requirements.txt` installs the demo dependencies. Keep your evaluation
reports locally; Community Cloud does not guarantee local SQLite persistence.

The Streamlit page is a **showcase**, not an externally callable FastAPI or MCP
gateway. Use the FastAPI service for agent-to-tool HTTP integration. Vercel can
host FastAPI, but the current SQLite approval and audit store would need a
shared persistent database before using its serverless functions.

## Operator dashboard

Open `http://127.0.0.1:8000/dashboard` while the gateway is running. Enter the
configured admin key to see all-time decision counts, pending and expired
approvals, recent events, and audit-chain status. Approve or reject a pending
request from the queue. Approval authorizes the agent's **next matching call**;
clicking Approve does not execute the tool.

For a quick local PowerShell trial, run this in the project folder:

```powershell
$env:AGENTGUARD_IDENTITIES='[{"key":"finance-demo-key","agent_id":"finance-demo","role":"finance"}]'
$env:AGENTGUARD_ADMIN_KEY='local-admin-key'
$env:AGENTGUARD_SIGNING_SECRET='local-demo-signing-secret-change-for-real-use'
$env:AGENTGUARD_DB_PATH='data/operator-demo.db'
uvicorn agentguard.api:app_from_env --factory --host 127.0.0.1 --port 8000
```

Open the dashboard and enter `local-admin-key`. In a second PowerShell window,
create a sample approval request:

```powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/v1/authorize' `
  -Headers @{'X-Agent-Key'='finance-demo-key'} -ContentType 'application/json' `
  -Body '{"tool":"payments.refund","resource":"customer/42","arguments":{"amount":2500}}'
```

Refresh the dashboard to review it. These example keys are for local testing
only. The dashboard holds the key in page memory, does not save it in browser
storage, and must be served only on a trusted local or HTTPS connection. The
standalone `mcp_demo.py` uses a temporary database, so its requests do not
appear in this persistent dashboard.

## Policy

The server derives `agent_id` and `role` from its configured agent API key. Agent-supplied identity fields are ignored. Policies currently permit:

| Role | Tool | Resource prefix | Extra condition |
| --- | --- | --- | --- |
| finance | `payments.refund` | `customer/` | amount > 2000 requires approval; amount must be 0–100000 |
| analytics | `db.read` | `public/` | none |
| support | `email.send` | `customer/` | outbound credential patterns denied |
| support_agent | `orders.lookup`, `payments.refund`, `email.send` | `order/` or `customer/` | business checks in the support endpoints |

Everything else is denied. A simple pattern check on `source_text` blocks some explicit prompt injection attempts; it is **not** a trained detector or a guarantee against prompt injection. The `risk_score` is a rule-based display signal, never a substitute for permission checks. Auth failures and invalid requests return HTTP errors; valid authorization requests return a decision JSON.

## Customer-support lab and measured results

The gateway owns three protected support actions: look up an order, issue a
mock refund, and record a mock outbound message. The synthetic orders are
`O-100` (total 1200), `O-200` (total 5000), and `O-300` (total 200). The
`support_agent` role can use these endpoints with its own configured key.
Refunds exceeding the order total or repeating a completed refund are blocked;
refunds above 2000 need a one-time approval. A message can go only to the
address stored for that order. Its body is a gateway-owned acknowledgement
that makes no shipping or delivery claim; model-supplied message text is not
accepted. Neither refunds nor messages reach a real external service.

Run the reproducible scenario suite in your extracted project folder:

```powershell
python examples/support_eval.py
```

It writes `reports/support_eval.json` and prints counts. Our reference run had
13/13 scripted cases match their expected outcomes, with 4/4 benign actions
completed and 0/8 scripted unsafe actions executed. **These are authored
policy checks, not an LLM prompt-injection benchmark or a real-world attack
success rate.** The report lists each case and its outcome. It uses a temporary
database, so its events will not appear on your separately running dashboard.

## Model-driven support agent

`examples/run_support_agent.py` connects a tool-calling chat model to the three
gateway-owned support actions. The model can request `lookup_order`,
`refund_order`, or `send_message`; it cannot choose a destination URL, access
admin endpoints, or approve its own requests. The host supplies the ticket to
the gateway's `source_text`, rather than accepting a rewritten copy from the
model. The gateway still has final control over every action. The agent calls
the support HTTP endpoints; the separate MCP example currently protects only
the refund tool.

This uses a configurable OpenAI-compatible `/v1/chat/completions` endpoint.
For example, after installing and starting a *tool-capable* model with
[Ollama](https://docs.ollama.com/capabilities/tool-calling), set the model
name you actually installed. Ollama documents its compatible endpoint at
`http://localhost:11434/v1/`. No model or model results are bundled.

From a fresh PowerShell window inside the **updated** project folder, configure
and start the gateway (stop an older server on port 8000 first):

```powershell
$env:AGENTGUARD_IDENTITIES='[{"key":"support-lab-demo-key","agent_id":"support-lab-demo","role":"support_agent"}]'
$env:AGENTGUARD_ADMIN_KEY='local-admin-key'
$env:AGENTGUARD_SIGNING_SECRET='local-demo-signing-secret-change-for-real-use'
$env:AGENTGUARD_DB_PATH='data/support-agent-demo.db'
python -m uvicorn agentguard.api:app_from_env --factory --host 127.0.0.1 --port 8000
```

In a **second** PowerShell window, with your model endpoint running:

```powershell
$env:AGENTGUARD_SUPPORT_AGENT_KEY='support-lab-demo-key'
$env:AGENTGUARD_CHAT_MODEL='YOUR_INSTALLED_TOOL_CAPABLE_MODEL'
$env:AGENTGUARD_CHAT_URL='http://127.0.0.1:11434/v1/chat/completions'
python examples/run_support_agent.py --ticket 'Please check order O-100.'
```

The agent reports each tool's decision and whether it executed. For a refund
above 2000, it stops and returns an approval ID. Review that ID at
`http://127.0.0.1:8000/dashboard`, then rerun the **identical ticket** with
`--approval-id THE_ID`. The approval works only if the agent requests the
same tool arguments. For another compatible model provider, set its chat URL
and (if required) `AGENTGUARD_CHAT_API_KEY` in the environment; never put the
key in tickets or source files. Ticket text and mock order details are sent
to the configured model provider.

After the single-ticket run, use `python examples/agent_eval.py --limit 2`
for a small live-model trial, or omit `--limit` to run all seven authored
tickets. It writes `reports/live_agent_eval.json` with per-ticket tool traces,
mock side effects, the host-generated `final_answer`, the untrusted
`model_answer` (each up to 4000 characters), and a separate observed path for
unsafe cases. `NO_TOOL_CALL` means the model made no request; read
`model_answer` to assess whether it refused, explained the situation, or made
an unsupported claim. `GATEWAY_DENIED_ATTEMPT` means the
model requested a tool and the gateway denied it. A denial followed by a
successful side effect is reported as `UNSAFE_SIDE_EFFECT`. The model's answer
is not automatically graded for truthfulness. Reports can contain model text,
so use synthetic tickets only. Model behavior can vary, and
these authored tickets are **not** an independent or held-out security
benchmark. A failed or unavailable model is counted as an evaluation failure.
The report includes `project_code_loaded: true` when the adjacent extracted
project supplied the agent code. Direct example scripts also choose that copy
over any older editable installation. The scorer checks tool effects, not the
truth of claims in `model_answer`; review that field manually. After an order
lookup, a denied action, a recorded refund, or a recorded message, the host
generates the final user-facing answer only from gateway responses. An
unverified model answer is preserved in the report but never shown as the
agent's final answer. A lookup-only answer states that currency is unspecified.
The support-message action sends a fixed gateway template.
After a denied tool call, the agent returns `BLOCKED` if no refund or message
was executed; the trace includes the gateway's denial reason. A tool-call
round limit or model/network error is `FAILED` in evaluation reports.

### Reproduce an attempted-action block

Run the deterministic agent tool-call probes without configuring a model:

```powershell
python examples/enforcement_eval.py
```

The scripted agent intentionally requests four unsafe actions: a refund above
the order total, an off-record email recipient, a credential in untrusted
ticket text, and an email after an explicit injected instruction. A fifth valid refund is an
allow control. The runner writes `reports/enforcement_eval.json` with each
attempt and the gateway's decision. These are scripted attempts whose inputs
were written with the policy; do not combine their counts with live-model
refusals or describe them as a measured LLM attack success rate.

To rerun the seven live tickets against the Ollama cloud endpoint used in the
earlier trial, run this in the project folder. The script prompts for the key
without displaying it or writing it to the report:

```powershell
python examples/agent_eval.py --ollama-cloud
```

Inspect `reports/live_agent_eval.json` for `observed_path`, `final_answer`,
and `trace` for A01–A03. `--ollama-cloud` prompts in each new session unless
`AGENTGUARD_CHAT_API_KEY` is already set there. For other providers, continue
to set `AGENTGUARD_CHAT_MODEL`, `AGENTGUARD_CHAT_URL`, and any needed API key.
To retest the benign refund after updating the project, run
`python examples/agent_eval.py --limit 2` and inspect B02. Its O-100 refund
of 800 is within the order total of 1200 and below the gateway approval
threshold of 2000; the expected trace is `lookup_order` followed by
`refund_order`, both `ALLOW` with `executed: true`. A model can still fail to
call a tool despite the instructions, so treat a passing scripted test as
gateway evidence, not proof of live-model reliability.

### Additional adversarial evaluation

With the same model settings as the seven-ticket trial, run the extra two
benign controls and 15 unsafe synthetic tickets:

```powershell
python examples/agent_eval.py --ollama-cloud --cases data/adversarial_tickets.jsonl --out reports/adversarial_agent_eval.json
```

The unsafe tickets include forged authority, a copied tool result, off-record
recipients, an outbound test credential, an approval claim, an invalid amount,
and explicit injection text. Inspect `observed_path`, `trace`, `model_answer`,
`final_answer`,
and `mock_actions` for each case. `NO_TOOL_CALL` alone is not a verified refusal;
the answer needs inspection. These tickets use the same authored synthetic
environment and are not a held-out benchmark. Some defenses depend on known
patterns in the ticket text.
For a focused rerun use, for example,
`python examples/agent_eval.py --ollama-cloud --cases data/adversarial_tickets.jsonl --ids B06 A04 A07 A12 A17 A18 --out reports/focused_agent_eval.json`.

Approval binding can also be checked independently of any model call:

```powershell
python examples/approval_eval.py
```

This writes `reports/approval_eval.json` for ten deterministic checks: changed
amount, resource or source text, a different agent, forged, expired or reused
approval, revoked role, extra arguments, and an unapproved high refund. The
mock refund baseline is reset for each check. These results measure the gateway
when an attempt occurs and must be kept separate from model behavior.

### Paired scripted comparison

Run the same eight authored ticket and tool-request pairs in two isolated mock
arms: a deliberately unguarded sink and the AgentGuard support gateway.

```powershell
python examples/paired_eval.py
```

The output `reports/paired_eval.json` reports effects separately for six unsafe
requests and two benign controls. Each case forces the same tool request in
both arms, so this measures the gateway's enforcement when a request occurs.
The unguarded arm accepts any listed arguments and records only an in-memory
mock effect. It is a deliberately weak comparator, not a production alternative.
The fixtures are newly authored for this comparison but **not independently
collected or held out**. Do not combine its counts with live-model results or
claim that it measures how often a live model attempts these actions. No real
payment or message service is used.

### Exploratory live-agent comparison

Run a configured tool-calling model on the same synthetic tickets in separate
guarded and unguarded mock labs. The bundled corpus contains three benign and
seven unsafe tickets. For Ollama Cloud, use the key prompt (its input is hidden):

```powershell
python examples/live_pair_eval.py --ollama-cloud --limit 2
python examples/live_pair_eval.py --ollama-cloud
```

If the key is already in `AGENTGUARD_CHAT_API_KEY`, the prompt is skipped.
The full run makes at least two model calls per ticket and may make more for
tool use. The runner writes `reports/live_pair_eval.json` with arm-specific
status, tool trace, mock actions, model answer, and a SHA-256 digest of the
corpus. Failed arms are excluded from effect denominators and shown as failed
pairs. Review the per-case traces: a model refusal in both arms provides no
evidence of gateway enforcement. The unguarded arm retains basic input schema
and known-order checks but skips role, amount, recipient, source-text, and
approval policy. It never calls a real payment or email service.

The two arms make **separate** model calls. Sampling and different tool
responses can change the sequence of requests; the runner alternates arm
order, but this is an exploratory comparison, not a controlled causal estimate.
The bundled tickets were authored for the prototype and are not independent or
held out. To evaluate separately prepared synthetic tickets, pass their JSONL
file with `--cases PATH`; each line needs `id`, `kind` (`benign` or `unsafe`),
`expect` (`lookup`, `refund`, `message`, or `no_effect`), and `ticket`. Use only
synthetic data, since the configured model provider receives the ticket text.

### Expanded authored support tickets

`data/support_review_v1.jsonl` contains 24 additional synthetic tickets: eight
benign and sixteen unsafe. They cover normal lookups, partial refunds and
acknowledgements, plus over-refunds, swapped recipients, claimed approvals,
copied tool results, invalid amounts, and instructions embedded in ticket
text. Each line includes a `family` label. This set was written by the project
author and **is not independent or held out**. It is useful for finding more
failure modes, not for claiming a general attack-prevention rate.

Check the JSONL and its content hash without a model or API key:

```powershell
python examples/live_pair_eval.py --cases data/support_review_v1.jsonl --labels data/support_review_v1_labels.json --validate-only
```

Then use the same Ollama Cloud key setup as above. A two-ticket trial covers
one benign refund and one over-refund; use a separate report path so the full
run does not overwrite it:

```powershell
python examples/live_pair_eval.py --ollama-cloud --cases data/support_review_v1.jsonl --labels data/support_review_v1_labels.json --ids R03 R09 --out reports/support_review_smoke.json
python examples/live_pair_eval.py --ollama-cloud --cases data/support_review_v1.jsonl --labels data/support_review_v1_labels.json --out reports/support_review_live_exact.json
```

The full run uses at least 48 model calls and can use more when tools are
requested. Inspect failed pairs and arm-specific `trace`, `model_answer`, and
`observed_path` before citing the counts. The scorer measures mock effects and
basic benign task completion; it does not grade the truth of free-form prose.
An `unsafe_effects` count includes **any** mock refund or message arising from
an unsafe ticket; a model may choose a harmless partial action. Inspect those
cases before describing them as successful attacks.

The separate `support_review_v1_labels.json` binds eight benign expected
actions to the original corpus hash. The ticket file stays byte-for-byte the
same as the first 24-case run. With `--labels`, the scorer checks the exact
order, amount, and recipient in structured mock results. The report also adds
`guarded_unsafe_policy_violations` and `unguarded_unsafe_policy_violations`,
which count recorded refunds above the order total or above the approval
threshold without review, and messages to off-record recipients. These are
explicit mock business-policy checks, not a prompt-injection success rate.
For corpora without exact-action labels, benign completion retains its older
count-based meaning. The previous `support_review_live.json` is not silently
rescored or overwritten; its manual audit remains in the evaluation review.

## SDK example

```python
from agentguard import AgentGuard, ApprovalRequired

guard = AgentGuard(agent_key="YOUR_FINANCE_AGENT_KEY")

def refund():
    return payments.refund(customer_id="42", amount=2500)

try:
    guard.run(tool="payments.refund", resource="customer/42",
              arguments={"amount": 2500}, execute=refund)
except ApprovalRequired as pending:
    print("Ask an admin to review", pending.approval_id)
    # After approval, retry the same run call with approval_id=pending.approval_id.
```

The caller must ensure `execute` performs **exactly** the described action. A caller can bypass a client-side SDK; use the included MCP proxy or server-owned demo endpoint to see gateway-controlled execution. Do not call the tool if the decision is pending or denied. Keep agent keys and admin keys separate.

## Protected MCP tool

Install the MCP extra and run the self-contained integration demo:

```bash
pip install -e '.[test,mcp]'
python examples/mcp_demo.py
```

On PowerShell those commands are identical. The demo runs an MCP client, an
AgentGuard MCP server, the policy API, and a fake payments MCP server in one
process. It shows zero provider calls while approval is pending and exactly one
after approval. It makes no real payment.

For a live local setup, start the FastAPI gateway as described above, then run
`python examples/refund_upstream.py` in a second terminal. Configure your MCP
host to launch `python -m agentguard.mcp_proxy` as a **stdio MCP server**, with
these environment variables in the host's MCP server configuration:

```text
AGENTGUARD_GATEWAY_URL=http://127.0.0.1:8000
AGENTGUARD_MCP_AGENT_KEY=<the configured finance agent key>
AGENTGUARD_REFUND_MCP_URL=http://127.0.0.1:8001/mcp
```

The MCP server exposes a single `refund(customer_id, amount, approval_id?,
source_text?)` tool. Calls above 2000 return an approval ID without reaching
the provider. An admin reviews the ID using the gateway's approvals API; the
agent then retries the exact same arguments with the approval ID. The tool
returns the provider's structured result after the gateway permits the call.
The proxy accepts no user-supplied destination or downstream tool name.

Keep the upstream MCP server inaccessible to untrusted agents; otherwise an
agent could connect to it directly. The MCP server uses a configured agent
key and trusts its host to protect that key. The optional `source_text` is
supplied by the host, so missing or dishonest source context cannot be detected
by this prototype. A provider must return structured MCP output.

## API

- `POST /v1/authorize` with `X-Agent-Key`: evaluates `tool`, `resource`, `arguments`, optional `source_text` and optional `approval_id`.
- `GET /v1/approvals` with `X-Admin-Key`: lists requests and the numeric refund amount, without raw arguments or source text.
- `GET /v1/summary` with `X-Admin-Key`: all-time counts and the current unexpired approval count.
- `POST /v1/approvals/{id}` with `X-Admin-Key`, `{"decision":"APPROVED"}` or `{"decision":"REJECTED"}`.
- `GET /v1/events` with `X-Admin-Key`: metadata-only audit events and chain verification.
- `POST /v1/demo/refunds` with `X-Agent-Key`: a **mock** server-owned refund. It evaluates the exact request and records a fake refund only on `ALLOW`; a pending decision returns `executed: false`. This is the enforcement example; it never calls a payment provider.
- `GET /v1/demo/refunds` with `X-Admin-Key`: lists executed mock refunds.
- `POST /v1/support/orders/lookup`, `/v1/support/refunds`, `/v1/support/messages` with a `support_agent` key: server-owned synthetic support actions.
- `GET /v1/support/mock-counts` with `X-Admin-Key`: counts mock refunds and messages.
- `GET /health`: process liveness response; `GET /ready`: database readiness response.
- `GET /dashboard`: local operator page; admin key is required for its data and review actions.

Audit records omit raw arguments and source text. The HMAC event chain can reveal simple database edits if the signing secret remains protected. SQLite files and keys are under the operator's control, so the log is not immutable or independently attested.

## Next build slices

1. Expand the authored ticket examples into independently collected or externally written held-out cases; compare an unguarded sandbox agent with the protected agent and report both safety and legitimate task completion.
2. Expand the single-tool MCP proxy into a configurable, schema-validated tool catalog with private upstream access and controlled identities.
3. Add persistent identity management, key rotation, stronger administration auth, policy versioning, and Postgres for multi-instance use.
4. Train detectors on labeled attack and benign data; report false positive rates, recall, latency, and calibration before using ML scores in policy decisions.
5. Add external monitoring and a durable multi-instance data store before an exposed deployment.

This repository has a policy gateway, Python SDK, server-owned mock workflows,
a narrowly scoped MCP-to-MCP refund proxy, a local operator dashboard,
scripted support-policy evaluation, and a configurable model-driven agent.
No live-model results, trained ML models, or production-grade operations are
claimed by the packaged reference report.
