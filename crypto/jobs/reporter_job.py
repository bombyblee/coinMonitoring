# jobs/futures_price_job.py
from __future__ import annotations
import asyncio
from crypto.jobs.base import ReporterJobBase

class FuturesReporterJob(ReporterJobBase):
    def __init__(self, symbol: str, messenger, state, market_api):
        super().__init__(messenger=messenger, state=state)
        self.symbol = symbol
        self.api = market_api

    def interval_sec(self) -> int:
        return int(getattr(self.state, "price_freq_sec", 600))

    async def _tick(self, chat_id: str) -> None:
        # fetch_last_price가 동기 호출이면 to_thread로 감싸는 게 안전
        last = await asyncio.to_thread(self.api.fetch_last_price, self.symbol)
        text = f"📈 {self.symbol} last={last}"
        await self.messenger.post_message(chat_id, text)
