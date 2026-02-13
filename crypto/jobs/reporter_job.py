import asyncio
from crypto.binance.futures_market_api import BinanceFuturesMarketApi
from crypto.analytics.formatter import format_snapshot

class FuturesReporterJob:
    def __init__(self, symbol: str, messenger, state):
        self.symbol = symbol
        self.messenger = messenger
        self.state = state
        self.api = BinanceFuturesMarketApi()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self, chat_id: str):
        self._stop.clear()
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(chat_id))

    async def stop(self):
        self._stop.set()
        if self._task:
            self._task.cancel()
            await asyncio.sleep(0)

    async def _run(self, chat_id: str):
        while not self._stop.is_set():
            if getattr(self.state, "enabled", True):
                try:
                    snap = self.api.fetch_snapshot(self.symbol)
                    text = format_snapshot(snap)
                    await self.messenger.post_message(chat_id, text)
                except Exception as e:
                    await self.messenger.post_message(chat_id, f"⚠️ price report failed: {e}")

            # ✅ 주기: state에서 읽기
            sec = getattr(self.state, "price_freq_sec", 600)
            await asyncio.sleep(sec)
