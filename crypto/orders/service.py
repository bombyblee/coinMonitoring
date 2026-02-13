import asyncio
from dataclasses import dataclass
from crypto.orders.parser import OrderIntent
from crypto.binance.symbol_rules import load_symbol_rules, quantize_qty

_FINAL = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}

@dataclass(frozen=True)
class RiskConfig:
    max_usdt_per_order: float = 200.0
    allowed_symbols: set[str] = None

class OrderService:
    def __init__(self, trader, risk: RiskConfig):
        self.trader = trader
        self.risk = risk
        self._rules_cache = {}  # symbol -> SymbolRules

    async def _get_rules(self, symbol: str):
        if symbol in self._rules_cache:
            return self._rules_cache[symbol]
        # exchange_info는 크니까 한 번만 가져오고 parsing해도 됨.
        # 여기서는 간단히 client로부터 직접 load(내부에서 exchange_info 호출)
        rules = load_symbol_rules(self.trader.client, symbol)  # sync call inside (괜찮: 초기 1회)
        self._rules_cache[symbol] = rules
        return rules

    async def _calc_qty(self, intent: OrderIntent) -> float:
        if intent.price is not None:
            ref_price = intent.price
        else:
            ref_price = await self.trader.get_last_price(intent.symbol)

        raw_qty = intent.usdt_amount / ref_price
        rules = await self._get_rules(intent.symbol)
        qty = quantize_qty(raw_qty, rules)

        if qty <= 0:
            raise ValueError("수량이 0이 됨(USDT가 너무 작거나 stepSize 영향). USDT를 늘려봐.")
        return qty

    async def place(self, intent: OrderIntent) -> dict:
        if self.risk.allowed_symbols and intent.symbol not in self.risk.allowed_symbols:
            raise ValueError(f"심볼 허용 안 됨: {intent.symbol}")
        if intent.usdt_amount > self.risk.max_usdt_per_order:
            raise ValueError(f"주문 금액 제한 초과: {intent.usdt_amount} > {self.risk.max_usdt_per_order}")

        qty = await self._calc_qty(intent)

        if intent.price is None:
            return await self.trader.new_market_order(intent.symbol, intent.side, qty)
        else:
            return await self.trader.new_limit_order(intent.symbol, intent.side, qty, intent.price)

    async def wait_final(self, symbol: str, order_id: int, timeout_sec: int = 600, interval_sec: float = 2.0) -> dict:
        # 1시간까지 폴링 (원하면 줄여)
        t0 = asyncio.get_event_loop().time()
        last = None
        while asyncio.get_event_loop().time() - t0 < timeout_sec:
            last = await self.trader.query_order(symbol, order_id)
            st = last.get("status")
            if st in _FINAL:
                return last
            await asyncio.sleep(interval_sec)
        return last or {"status": "UNKNOWN"}
