from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from crypto.binance.http_client import HttpClient
from .ohlcv_db import Ohlcv5mRepository

logger = logging.getLogger(__name__)

_INTERVAL   = "5m"
_TICK_SEC   = 300    # 5분 polling interval
_FETCH_LIMIT = 3     # 마지막 캔들은 forming 중일 수 있어 여유 있게 조회


class Ohlcv5mDbJob:
    """
    고정된 심볼 목록(기본: BTC/ETH/XRP)의 5분봉을 5분 주기로 조회해
    로컬 SQLite DB(Ohlcv5mRepository)에 영구 저장한다.

    watchlist와는 무관하게 항상 지정된 심볼만 대상으로 동작한다.
    """

    def __init__(
        self,
        symbols: list[str],
        db: Ohlcv5mRepository,
        http: Optional[HttpClient] = None,
    ):
        self.symbols = symbols
        self.db = db
        self._http = http or HttpClient(base_url="https://fapi.binance.com")
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    # ── public ───────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._stop.clear()
        await asyncio.to_thread(self.db.init_schema)
        self._task = asyncio.create_task(self._run(), name="ohlcv_5m_db_job")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            await asyncio.sleep(0)

    # ── internal loop ─────────────────────────────────────────────────────────

    async def _run(self) -> None:
        """다음 5분 경계까지 대기한 뒤, 5분마다 tick."""
        await self._sleep_until_next_boundary()
        while not self._stop.is_set():
            await self._tick()
            await asyncio.sleep(_TICK_SEC)

    async def _sleep_until_next_boundary(self) -> None:
        now = time.time()
        secs_into = now % _TICK_SEC
        wait = (_TICK_SEC - secs_into) + 3  # +3s 버퍼 for candle close
        if wait > _TICK_SEC:
            wait -= _TICK_SEC
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass  # normal: stop was not set

    async def _tick(self) -> None:
        for sym in self.symbols:
            try:
                await self._update_symbol(sym)
            except Exception as e:
                logger.warning("Ohlcv5mDbJob: update failed for %s: %s", sym, e)

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _update_symbol(self, symbol: str) -> None:
        raw = await asyncio.to_thread(self._fetch_klines, symbol, _FETCH_LIMIT)
        closed = raw[:-1]  # 마지막 캔들은 아직 forming 중이므로 제외
        if not closed:
            return
        n = await asyncio.to_thread(self.db.upsert_klines, symbol, closed)
        if n:
            logger.debug("Ohlcv5mDbJob: %s +%d row(s) saved to DB", symbol, n)

    def _fetch_klines(self, symbol: str, limit: int) -> list:
        return self._http.get(
            "/fapi/v1/klines",
            params={"symbol": symbol, "interval": _INTERVAL, "limit": limit},
        )
