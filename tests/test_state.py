from app.models import MarketSample
from app.state import SymbolStore


def test_store_roundtrip(tmp_path):
    db = tmp_path / "btc.db"
    store = SymbolStore(db, commit_every=1)
    s = MarketSample(1, "BTCUSDT", 99, 101, 100, 200, 10, 9, 20, 18, 30, 27, .1, .2, .3, .4, 100.2, 20, .1, .2, .3, 1, 2, 3, 4)
    store.insert_sample(s); store.close()
    import sqlite3
    con = sqlite3.connect(db)
    row = con.execute("select symbol, obi_l20 from market_samples").fetchone()
    con.close()
    assert row == ("BTCUSDT", .4)
