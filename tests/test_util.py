from decimal import Decimal
from app.util import floor_step, ceil_step, bps_delta


def test_steps():
    assert floor_step(Decimal("1.239"), Decimal("0.01")) == Decimal("1.23")
    assert ceil_step(Decimal("1.231"), Decimal("0.01")) == Decimal("1.24")


def test_bps():
    assert bps_delta(Decimal("101"), Decimal("100")) == Decimal("100")
