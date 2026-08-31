from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path


def main() -> int:
    data = Path(os.getenv("OBERON_DATA_DIR", "/data"))
    market_dir = data / os.getenv("MARKET_DIR_NAME", "markets-v091")
    max_age = int(os.getenv("HEALTH_MAX_SAMPLE_AGE_SECONDS", "30"))
    dbs = list(market_dir.glob("*.db"))
    if not dbs:
        print("unhealthy: no market databases")
        return 1
    newest = 0
    for db in dbs:
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            row = con.execute("SELECT MAX(ts_ms) FROM market_samples").fetchone(); con.close()
            if row and row[0]: newest = max(newest, int(row[0]))
        except sqlite3.Error:
            continue
    age = time.time() - newest / 1000.0 if newest else 1e9
    if age > max_age:
        print(f"unhealthy: newest sample age={age:.1f}s")
        return 1
    print(f"healthy: databases={len(dbs)} newest_age={age:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
