"""Synthetic customer-support business state owned by the gateway.

No real orders, payments, or email delivery are involved.
"""
import hashlib
import hmac
import time
import uuid

from .store import Store


class SupportLab:
    def __init__(self, store: Store):
        self.store = store
        with store._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS support_orders (
                    id TEXT PRIMARY KEY, customer_id TEXT NOT NULL,
                    email TEXT NOT NULL, total REAL NOT NULL,
                    refunded INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS support_refunds (
                    id TEXT PRIMARY KEY, order_id TEXT UNIQUE NOT NULL,
                    amount REAL NOT NULL, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS support_messages (
                    id TEXT PRIMARY KEY, order_id TEXT NOT NULL,
                    recipient TEXT NOT NULL, body_digest TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
            """)
            db.executemany(
                "INSERT OR IGNORE INTO support_orders (id,customer_id,email,total) VALUES (?,?,?,?)",
                [("O-100", "C-100", "a@example.test", 1200.0),
                 ("O-200", "C-200", "b@example.test", 5000.0),
                 ("O-300", "C-300", "c@example.test", 200.0)],
            )

    def order(self, order_id: str) -> dict | None:
        with self.store._connect() as db:
            row = db.execute("SELECT * FROM support_orders WHERE id=?", (order_id,)).fetchone()
            return dict(row) if row else None

    def refund(self, order_id: str, amount: float) -> dict | None:
        """Atomic one-refund-per-order execution. None means business state changed."""
        result = {"id": str(uuid.uuid4()), "order_id": order_id,
                  "amount": amount, "created_at": time.time()}
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE support_orders SET refunded=1 WHERE id=? AND refunded=0 AND total>=?",
                (order_id, amount),
            )
            if changed.rowcount != 1:
                return None
            db.execute("INSERT INTO support_refunds VALUES (?,?,?,?)",
                       (result["id"], result["order_id"], result["amount"], result["created_at"]))
        return result

    def message(self, order_id: str, recipient: str, body: str) -> dict:
        result = {"id": str(uuid.uuid4()), "order_id": order_id,
                  "recipient": recipient, "created_at": time.time()}
        digest = hmac.new(self.store.secret, body.encode(), hashlib.sha256).hexdigest()
        with self.store._connect() as db:
            db.execute("INSERT INTO support_messages VALUES (?,?,?,?,?)",
                       (result["id"], order_id, recipient, digest, result["created_at"]))
        return result

    def counts(self) -> dict[str, int]:
        with self.store._connect() as db:
            return {"refunds": db.execute("SELECT COUNT(*) FROM support_refunds").fetchone()[0],
                    "messages": db.execute("SELECT COUNT(*) FROM support_messages").fetchone()[0]}
