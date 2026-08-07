from decimal import Decimal
from app.config import Settings
from app.models import Balance, BookTicker, SymbolRules
from app.strategy import Strategy


def test_quote_plan_respects_book():
    s = Settings(trading_mode="paper")
    rules = SymbolRules(Decimal("0.01"), Decimal("0.00001"), Decimal("0.00001"), Decimal("5"))
    strategy = Strategy(s, rules)
    book = BookTicker(Decimal("99999"), Decimal("1"), Decimal("100001"), Decimal("1"), 1, 1)
    plan = strategy.plan(book, Balance(Decimal("0.001")), Balance(Decimal("100")))
    assert plan.bid_price < book.ask
    assert plan.ask_price > book.bid
    assert plan.bid_qty * book.mid >= rules.min_notional
