from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .util import now_ms


class StateStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def _migrate(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                type TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY,
                client_order_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                status TEXT NOT NULL,
                price TEXT NOT NULL,
                orig_qty TEXT NOT NULL,
                executed_qty TEXT NOT NULL,
                updated_ms INTEGER NOT NULL
            );
            """
        )
        self.db.commit()

    def event(self, kind: str, payload: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT INTO events(ts_ms,type,payload) VALUES(?,?,?)",
            (now_ms(), kind, json.dumps(payload, separators=(",", ":"), default=str)),
        )
        self.db.commit()

    def upsert_order(self, order: dict[str, Any]) -> None:
        self.db.execute(
            """
            INSERT INTO orders(order_id,client_order_id,symbol,side,status,price,orig_qty,executed_qty,updated_ms)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(order_id) DO UPDATE SET
              status=excluded.status,
              price=excluded.price,
              orig_qty=excluded.orig_qty,
              executed_qty=excluded.executed_qty,
              updated_ms=excluded.updated_ms
            """,
            (
                int(order["orderId"]),
                order.get("clientOrderId", ""),
                order["symbol"],
                order["side"],
                order.get("status", "UNKNOWN"),
                str(order.get("price", "0")),
                str(order.get("origQty", "0")),
                str(order.get("executedQty", "0")),
                now_ms(),
            ),
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()
