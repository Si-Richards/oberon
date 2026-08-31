import sqlite3
import time
from pathlib import Path

from app.signal_report import inspect_database, load_rows, add_derived_features, forward_returns, analyze_feature


def make_db(path: Path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE market_samples (ts_ms INTEGER, symbol TEXT, bid REAL, ask REAL, book_imbalance_l20 REAL, trade_flow REAL)")
    now = int(time.time() * 1000) - 700_000
    price = 100.0
    for i in range(700):
        signal = ((i % 50) - 25) / 25.0
        price *= 1 + signal * 0.00002
        con.execute("INSERT INTO market_samples VALUES (?,?,?,?,?,?)", (now + i * 1000, "TESTUSDT", price - .01, price + .01, signal, signal * .7))
    con.commit(); con.close()


def test_schema_adaptive_report(tmp_path):
    db = tmp_path / "testusdt.db"
    make_db(db)
    sources = inspect_database(db)
    assert sources
    rows = load_rows(sources[0], 0)
    assert len(rows) == 700
    add_derived_features(rows)
    fwd = forward_returns(rows, (5, 30, 60))
    result = analyze_feature(rows, fwd, "book_imbalance_l20", (5, 30, 60), 20)
    assert result is not None
    assert result["horizons"]
