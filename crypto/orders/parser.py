import re
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class OrderIntent:
    side: str                 # "BUY" / "SELL"
    symbol: str               # "BTCUSDT"
    usdt_amount: float        # 테더 기준 주문 금액
    price: Optional[float] = None  # None이면 MARKET

_PAT = re.compile(
    r"^\s*(BUY|SELL)\s+([A-Z0-9_]+)\s+([0-9]*\.?[0-9]+)\s*(?:@\s*([0-9]*\.?[0-9]+))?\s*$",
    re.IGNORECASE
)

def parse_order_intent(text: str) -> OrderIntent:
    m = _PAT.match(text.strip())
    if not m:
        raise ValueError("형식: BUY|SELL <SYMBOL> <USDT> [@ <PRICE>]\n예) BUY BTCUSDT 50 @ 52000")

    side = m.group(1).upper()
    symbol = m.group(2).upper()
    usdt = float(m.group(3))
    price = float(m.group(4)) if m.group(4) else None

    if usdt <= 0:
        raise ValueError("USDT 금액은 0보다 커야 함")
    if price is not None and price <= 0:
        raise ValueError("가격은 0보다 커야 함")

    return OrderIntent(side=side, symbol=symbol, usdt_amount=usdt, price=price)
