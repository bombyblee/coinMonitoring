import asyncio
from binance.um_futures import UMFutures

class BinanceFuturesTrader:
    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://fapi.binance.com"):
        self.client = UMFutures(key=api_key, secret=api_secret, base_url=base_url)

    async def get_last_price(self, symbol: str) -> float:
        # /fapi/v1/ticker/price
        def _call():
            r = self.client.ticker_price(symbol=symbol)
            return float(r["price"])
        return await asyncio.to_thread(_call)

    async def new_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        def _call():
            return self.client.new_order(symbol=symbol, side=side, type="MARKET", quantity=quantity)
        return await asyncio.to_thread(_call)

    async def new_limit_order(self, symbol: str, side: str, quantity: float, price: float, tif: str = "GTC") -> dict:
        def _call():
            return self.client.new_order(
                symbol=symbol, side=side, type="LIMIT",
                timeInForce=tif, quantity=quantity, price=price
            )
        return await asyncio.to_thread(_call)

    async def query_order(self, symbol: str, order_id: int) -> dict:
        def _call():
            return self.client.query_order(symbol=symbol, orderId=order_id)
        return await asyncio.to_thread(_call)

    async def new_close_market_order(self, symbol: str, side: str, quantity: float) -> dict:
        """포지션 청산용 시장가 주문 (reduceOnly=True). USDT 손익 기준 트리거에서 사용."""
        def _call():
            return self.client.new_order(
                symbol=symbol,
                side=side,
                type="MARKET",
                quantity=quantity,
                reduceOnly="true",
            )
        return await asyncio.to_thread(_call)

    async def new_take_profit_order(self, symbol: str, side: str, stop_price: float) -> dict:
        """TAKE_PROFIT_MARKET 주문 (closePosition=true). 가격 기준 TP에서 사용.
        side: 포지션 청산 방향 (LONG→SELL, SHORT→BUY)
        stop_price: 트리거 가격 (MARK_PRICE 기준)
        """
        def _call():
            return self.client.new_order(
                symbol=symbol,
                side=side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=stop_price,
                closePosition="true",
                workingType="MARK_PRICE",
            )
        return await asyncio.to_thread(_call)

    async def new_stop_loss_order(self, symbol: str, side: str, stop_price: float) -> dict:
        """STOP_MARKET 주문 (closePosition=true). 가격 기준 SL에서 사용.
        side: 포지션 청산 방향 (LONG→SELL, SHORT→BUY)
        stop_price: 트리거 가격 (MARK_PRICE 기준)
        """
        def _call():
            return self.client.new_order(
                symbol=symbol,
                side=side,
                type="STOP_MARKET",
                stopPrice=stop_price,
                closePosition="true",
                workingType="MARK_PRICE",
            )
        return await asyncio.to_thread(_call)

    async def get_open_orders(self, symbol: str = None) -> list:
        """현재 오픈 주문 조회 (/fapi/v1/openOrders). symbol 미지정 시 전체 심볼."""
        def _call():
            if symbol:
                return self.client.get_open_orders(symbol=symbol)
            return self.client.get_open_orders()
        return await asyncio.to_thread(_call)

    async def exchange_info(self) -> dict:
        return await asyncio.to_thread(self.client.exchange_info)
