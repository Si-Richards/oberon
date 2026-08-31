from app.features import FeatureEngine, imbalance, microprice


def test_book_features():
    bids = [(100.0, 2.0), (99.9, 1.0)]
    asks = [(100.1, 1.0), (100.2, 1.0)]
    assert imbalance(bids, asks, 1) > 0
    mp = microprice(100.0, 2.0, 100.1, 1.0)
    assert 100.0 < mp < 100.1
    assert mp > 100.05


def test_flow_sign():
    f = FeatureEngine()
    f.on_trade(1000, 100.0, 1.0, False)
    f.on_trade(1500, 100.0, 0.25, True)
    assert f.trade_flow(2000, 5) > 0
