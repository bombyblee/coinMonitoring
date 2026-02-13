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

    async def exchange_info(self) -> dict:
        return await asyncio.to_thread(self.client.exchange_info)
