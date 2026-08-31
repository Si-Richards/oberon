import time
from app.signal_report import Row
from app.directional_report import analyze


def test_directional_analysis_has_results():
    start = int(time.time() * 1000) - 1000_000
    rows = []
    price = 100.0
    for i in range(800):
        sig = -1.0 if i % 20 < 10 else 1.0
        price *= 1 + sig * 0.00002
        rows.append(Row(start + i * 1000, price, "TESTUSDT", {"obi_l20": sig, "trade_flow_30s": sig}))
    out = analyze(rows, 5, 20, 16.5)
    assert out
