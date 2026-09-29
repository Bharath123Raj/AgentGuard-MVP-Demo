"""SQLite approvals and tamper-evident (not immutable) event chain."""
import hashlib
import hmac
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path: str, secret: str):
        self.path, self.secret = path, secret.encode()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, action_digest TEXT NOT NULL,
                    tool TEXT NOT NULL, resource TEXT NOT NULL, amount REAL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL, expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                    agent_id TEXT NOT NULL, tool TEXT NOT NULL, resource TEXT NOT NULL,
                    decision TEXT NOT NULL, reason TEXT NOT NULL,
                    prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS demo_refunds (
                    id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
                    customer TEXT NOT NULL, amount REAL NOT NULL,
                    created_at REAL NOT NULL
                );
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, agent_id: str, tool: str, resource: str, decision: str, reason: str):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT event_hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
            prev = row[0] if row else "0" * 64
            at = time.time()
            fields = [at, agent_id, tool, resource, decision, reason, prev]
            payload = json.dumps(fields, separators=(",", ":"))
            digest = hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()
            db.execute("INSERT INTO events (at,agent_id,tool,resource,decision,reason,prev_hash,event_hash) VALUES (?,?,?,?,?,?,?,?)",
                       (*fields, digest))

    def create_approval(self, agent_id: str, digest: str, tool: str,
                        resource: str, amount: float | None = None) -> str:
        approval_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as db:
            db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?)",
                       (approval_id, agent_id, digest, tool, resource, amount, "PENDING", now, now + 900))
        return approval_id

    def approval(self, approval_id: str):
        with self._connect() as db:
            row = db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            return dict(row) if row else None

    def approvals(self, limit: int = 100):
        now = time.time()
        with self._connect() as db:
            return [dict(row) for row in db.execute("""
                SELECT id,agent_id,tool,resource,amount,
                    CASE WHEN status='PENDING' AND expires_at<=? THEN 'EXPIRED'
                         ELSE status END AS status,
                    created_at,expires_at
                FROM approvals ORDER BY created_at DESC LIMIT ?
            """, (now, limit))]

    def decide(self, approval_id: str, status: str) -> bool:
        with self._connect() as db:
            result = db.execute("UPDATE approvals SET status=? WHERE id=? AND status='PENDING' AND expires_at>?",
                                (status, approval_id, time.time()))
            return result.rowcount == 1

    def redeem(self, approval_id: str, agent_id: str, digest: str) -> bool:
        with self._connect() as db:
            result = db.execute("UPDATE approvals SET status='CONSUMED' WHERE id=? AND status='APPROVED' AND agent_id=? AND action_digest=? AND expires_at>?",
                                (approval_id, agent_id, digest, time.time()))
            return result.rowcount == 1

    def events(self, limit: int = 50):
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]

    def summary(self):
        """All-time decision counts and current unexpired approval backlog."""
        with self._connect() as db:
            counts = {row["decision"]: row["count"] for row in db.execute(
                "SELECT decision, COUNT(*) AS count FROM events GROUP BY decision")}
            pending = db.execute(
                "SELECT COUNT(*) FROM approvals WHERE status='PENDING' AND expires_at>?",
                (time.time(),)).fetchone()[0]
        return {"total_events": sum(counts.values()), "allowed": counts.get("ALLOW", 0),
                "denied": counts.get("DENY", 0), "pending": pending,
                "approved_reviews": counts.get("APPROVED", 0)}

    def demo_refund(self, agent_id: str, customer: str, amount: float) -> dict:
        """Mock payment provider owned by the gateway (never makes real payments)."""
        result = {"id": str(uuid.uuid4()), "agent_id": agent_id, "customer": customer,
                  "amount": amount, "created_at": time.time()}
        with self._connect() as db:
            db.execute("INSERT INTO demo_refunds VALUES (?,?,?,?,?)", tuple(result.values()))
        return result

    def demo_refunds(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM demo_refunds ORDER BY created_at DESC")]

    def verify_chain(self) -> bool:
        prev = "0" * 64
        with self._connect() as db:
            for row in db.execute("SELECT * FROM events ORDER BY id"):
                fields = [row[key] for key in ("at", "agent_id", "tool", "resource", "decision", "reason", "prev_hash")]
                digest = hmac.new(self.secret, json.dumps(fields, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
                if row["prev_hash"] != prev or not hmac.compare_digest(digest, row["event_hash"]):
                    return False
                prev = row["event_hash"]
        return True
