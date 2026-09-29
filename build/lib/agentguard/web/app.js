"use strict";

const element = (id) => document.getElementById(id);
let adminKey = "";
let refreshing = false;

function feedback(message, type = "") {
  const label = element("feedback");
  label.textContent = message;
  label.className = `feedback ${type}`;
}

function lock(message = "View locked.") {
  adminKey = "";
  element("admin-key").value = "";
  element("access-panel").hidden = false;
  element("console").hidden = true;
  feedback(message);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    cache: "no-store",
    headers: {"X-Admin-Key": adminKey, ...(options.headers || {})},
  });
  if (response.status === 401) {
    lock("Admin key rejected. Enter the configured key to continue.");
    throw new Error("Unauthorized");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function cell(row, value, small = "") {
  const td = document.createElement("td");
  td.textContent = String(value ?? "—");
  if (small) {
    const sub = document.createElement("small");
    sub.textContent = String(small);
    td.append(sub);
  }
  row.append(td);
  return td;
}

function pill(value) {
  const span = document.createElement("span");
  span.className = `pill ${String(value).toLowerCase()}`;
  span.textContent = String(value);
  return span;
}

function date(timestamp) {
  return new Date(timestamp * 1000).toLocaleString();
}

async function review(item, decision) {
  const verb = decision === "APPROVED" ? "Approve" : "Reject";
  const detail = `${item.agent_id} · ${item.tool} · ${item.resource}`;
  if (!window.confirm(`${verb} this exact request?\n${detail}\nAmount: ${item.amount ?? "—"}`)) return;
  try {
    await api(`/v1/approvals/${encodeURIComponent(item.id)}`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({decision}),
    });
    feedback(`${verb}d request ${item.id}.`, "ok");
    await refresh();
  } catch (error) {
    if (adminKey) feedback(error.message, "error");
  }
}

function showApprovals(items) {
  const body = element("approvals-body");
  body.replaceChildren();
  const pending = items.filter((item) => item.status === "PENDING").length;
  element("approvals-count").textContent = `${pending} awaiting review · ${items.length} recent`;
  if (!items.length) {
    const row = document.createElement("tr");
    cell(row, "No approval requests yet.");
    body.append(row);
  }
  for (const item of items) {
    const row = document.createElement("tr");
    cell(row, item.agent_id, item.tool);
    cell(row, item.resource);
    cell(row, item.amount ?? "—");
    cell(row, date(item.created_at));
    const status = cell(row, "");
    status.append(pill(item.status));
    if (item.status === "PENDING") {
      const actions = document.createElement("div");
      actions.className = "actions";
      for (const [decision, label, className] of [
        ["APPROVED", "Approve", "primary"], ["REJECTED", "Reject", "danger"],
      ]) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = className;
        button.textContent = label;
        button.addEventListener("click", () => review(item, decision));
        actions.append(button);
      }
      status.append(actions);
    }
    body.append(row);
  }
}

function showEvents(data) {
  const badge = element("chain-status");
  badge.textContent = data.chain_valid ? "● Chain verified" : "● Chain verification failed";
  badge.className = `chain ${data.chain_valid ? "valid" : "invalid"}`;
  const body = element("events-body");
  body.replaceChildren();
  if (!data.events.length) {
    const row = document.createElement("tr");
    cell(row, "No decisions recorded yet.");
    body.append(row);
  }
  for (const item of data.events) {
    const row = document.createElement("tr");
    cell(row, date(item.at));
    cell(row, item.agent_id);
    cell(row, item.tool, item.resource);
    const status = cell(row, "");
    status.append(pill(item.decision));
    cell(row, item.reason);
    body.append(row);
  }
}

async function refresh() {
  if (!adminKey || refreshing) return;
  refreshing = true;
  element("refresh").disabled = true;
  try {
    const [summary, approvals, events] = await Promise.all([
      api("/v1/summary"), api("/v1/approvals"), api("/v1/events"),
    ]);
    if (!adminKey) return;
    for (const name of ["total-events", "allowed", "denied", "pending"]) {
      element(name).textContent = Number(summary[name.replaceAll("-", "_")]).toLocaleString();
    }
    showApprovals(approvals);
    showEvents(events);
    element("access-panel").hidden = true;
    element("console").hidden = false;
  } catch (error) {
    if (adminKey) feedback(error.message, "error");
  } finally {
    refreshing = false;
    element("refresh").disabled = false;
  }
}

element("access-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  adminKey = element("admin-key").value;
  element("admin-key").value = "";
  feedback("");
  await refresh();
});
element("refresh").addEventListener("click", refresh);
element("lock").addEventListener("click", () => lock());
window.setInterval(refresh, 20000);
