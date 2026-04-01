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

    async def new_take_profit_order(self, symbol: str, side: str, stop_price: float, quantity: float = None) -> dict:
        """TAKE_PROFIT_MARKET 알고 주문 (POST /fapi/v1/algoOrder).
        side: 포지션 청산 방향 (LONG→SELL, SHORT→BUY)
        stop_price: 트리거 가격
        quantity: 청산 수량 (지정 시 해당 수량만 청산, None이면 closePosition=true)
        """
        def _call():
            params = {
                "algoType": "CONDITIONAL",
                "symbol": symbol,
                "side": side,
                "type": "TAKE_PROFIT_MARKET",
                "triggerPrice": stop_price,
                "workingType": "MARK_PRICE",
            }
            if quantity is not None:
                params["quantity"] = quantity
            else:
                params["closePosition"] = "true"
            return self.client.sign_request("POST", "/fapi/v1/algoOrder", params)
        return await asyncio.to_thread(_call)

    async def new_stop_loss_order(self, symbol: str, side: str, stop_price: float, quantity: float = None) -> dict:
        """STOP_MARKET 알고 주문 (POST /fapi/v1/algoOrder).
        side: 포지션 청산 방향 (LONG→SELL, SHORT→BUY)
        stop_price: 트리거 가격
        quantity: 청산 수량 (지정 시 해당 수량만 청산, None이면 closePosition=true)
        """
        def _call():
            params = {
                "algoType": "CONDITIONAL",
                "symbol": symbol,
                "side": side,
                "type": "STOP_MARKET",
                "triggerPrice": stop_price,
                "workingType": "MARK_PRICE",
            }
            if quantity is not None:
                params["quantity"] = quantity
            else:
                params["closePosition"] = "true"
            return self.client.sign_request("POST", "/fapi/v1/algoOrder", params)
        return await asyncio.to_thread(_call)

    async def get_open_orders(self, symbol: str = None) -> list:
        """일반 오픈 주문 + 알고 오픈 주문 합산 조회."""
        def _call():
            params = {"symbol": symbol} if symbol else {}
            regular = self.client.get_open_orders(**params)

            algo_resp = self.client.sign_request("GET", "/fapi/v1/openAlgoOrders", params)
            algo_orders = algo_resp.get("orders", []) if isinstance(algo_resp, dict) else []

            # 알고 주문 필드를 일반 주문 형식으로 정규화
            for o in algo_orders:
                o.setdefault("orderId", o.get("algoId", ""))
                o.setdefault("stopPrice", o.get("triggerPrice", "0"))
            return regular + algo_orders

        return await asyncio.to_thread(_call)

    async def get_user_trades(self, symbol: str, start_time: int = None, limit: int = 100) -> list:
        """/fapi/v1/userTrades — 체결 내역. start_time은 밀리초 epoch."""
        def _call():
            params: dict = {"symbol": symbol, "limit": limit}
            if start_time:
                params["startTime"] = start_time
            return self.client.sign_request("GET", "/fapi/v1/userTrades", params)
        return await asyncio.to_thread(_call)

    async def exchange_info(self) -> dict:
        return await asyncio.to_thread(self.client.exchange_info)
