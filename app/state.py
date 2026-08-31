from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .models import MarketSample, PaperFill


MARKET_COLUMNS = (
    "ts_ms,symbol,bid,ask,mid,spread_bps,bid_depth_5,ask_depth_5,bid_depth_10,ask_depth_10,"
    "bid_depth_20,ask_depth_20,obi_l1,obi_l5,obi_l10,obi_l20,microprice,microprice_bps,"
    "trade_flow_5s,trade_flow_30s,trade_flow_60s,ret_5s_bps,ret_30s_bps,ret_60s_bps,"
    "vol_60s_bps,mark_price,index_price,funding_rate"
)


class SymbolStore:
    def __init__(self, path: Path, commit_every: int = 25, busy_timeout_ms: int = 5000):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.commit_every = max(1, commit_every)
        self._pending = 0
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, timeout=busy_timeout_ms / 1000.0, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        self._migrate()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_samples (
              ts_ms INTEGER NOT NULL,
              symbol TEXT NOT NULL,
              bid REAL NOT NULL, ask REAL NOT NULL, mid REAL NOT NULL, spread_bps REAL NOT NULL,
              bid_depth_5 REAL NOT NULL, ask_depth_5 REAL NOT NULL,
              bid_depth_10 REAL NOT NULL, ask_depth_10 REAL NOT NULL,
              bid_depth_20 REAL NOT NULL, ask_depth_20 REAL NOT NULL,
              obi_l1 REAL NOT NULL, obi_l5 REAL NOT NULL, obi_l10 REAL NOT NULL, obi_l20 REAL NOT NULL,
              microprice REAL NOT NULL, microprice_bps REAL NOT NULL,
              trade_flow_5s REAL NOT NULL, trade_flow_30s REAL NOT NULL, trade_flow_60s REAL NOT NULL,
              ret_5s_bps REAL NOT NULL, ret_30s_bps REAL NOT NULL, ret_60s_bps REAL NOT NULL,
              vol_60s_bps REAL NOT NULL,
              mark_price REAL, index_price REAL, funding_rate REAL,
              PRIMARY KEY (ts_ms, symbol)
            );
            CREATE INDEX IF NOT EXISTS idx_market_samples_symbol_ts ON market_samples(symbol, ts_ms);
            CREATE TABLE IF NOT EXISTS paper_fills (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts_ms INTEGER NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL,
              price REAL NOT NULL, quantity REAL NOT NULL, mid_at_fill REAL NOT NULL, reason TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_paper_fills_symbol_ts ON paper_fills(symbol, ts_ms);
            """
        )
        self.conn.commit()

    def insert_sample(self, s: MarketSample) -> None:
        values = tuple(getattr(s, name) for name in MARKET_COLUMNS.split(","))
        placeholders = ",".join("?" for _ in values)
        with self._lock:
            self.conn.execute(f"INSERT OR REPLACE INTO market_samples ({MARKET_COLUMNS}) VALUES ({placeholders})", values)
            self._pending += 1
            if self._pending >= self.commit_every:
                self.conn.commit(); self._pending = 0

    def insert_fill(self, f: PaperFill) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO paper_fills(ts_ms,symbol,side,price,quantity,mid_at_fill,reason) VALUES (?,?,?,?,?,?,?)",
                (f.ts_ms, f.symbol, f.side, f.price, f.quantity, f.mid_at_fill, f.reason),
            )
            self._pending += 1
            if self._pending >= self.commit_every:
                self.conn.commit(); self._pending = 0

    def flush(self) -> None:
        with self._lock:
            self.conn.commit(); self._pending = 0

    def close(self) -> None:
        with self._lock:
            self.conn.commit()
            self.conn.close()
