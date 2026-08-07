from __future__ import annotations

import time
from decimal import Decimal, ROUND_DOWN, ROUND_UP


def now_ms() -> int:
    return int(time.time() * 1000)


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def ceil_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_UP) * step


def bps_delta(a: Decimal, b: Decimal) -> Decimal:
    if b == 0:
        return Decimal("0")
    return abs(a - b) / b * Decimal("10000")
