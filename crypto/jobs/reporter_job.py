import asyncio
from crypto.binance.futures_market_api import BinanceFuturesMarketApi
from crypto.analytics.formatter import format_snapshot

class FuturesReporterJob:
    def __init__(self, symbol: str, interval_sec: int, messenger):
        self.symbol = symbol
        self.interval_sec = interval_sec
        self.messenger = messenger
        self.api = BinanceFuturesMarketApi()

    async def run_forever(self, chat_id: str):
        while True:
            try:
                snap = self.api.fetch_snapshot(self.symbol)
                text = format_snapshot(snap)
                await self.messenger.post_message(chat_id, text)
            except Exception as e:
                # 실패도 알림(너무 스팸이면 나중에 제한)
                try:
                    await self.messenger.post_message(chat_id, f"⚠️ report failed: {e}")
                except Exception:
                    pass
            await asyncio.sleep(self.interval_sec)
