from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from crypto.binance.http_client import HttpClient
from .watchlist import Watchlist
from .ohlcv_store import OhlcvStore

logger = logging.getLogger(__name__)

_INTERVAL        = "1m"
_TICK_SEC        = 60    # polling interval
_INIT_FETCH      = 3     # extra candles fetched on updates (latest may be forming)
_BINANCE_MAX_LIMIT = 1500  # Binance API hard limit per klines request


class OhlcvJob:
    """
    Keeps OhlcvStore in sync with Binance 1-minute klines for all watchlist symbols.

    Lifecycle
    ---------
    - start(): loads initial history for every symbol, then kicks off the loop.
    - stop():  cancels the background task.

    Per-tick behaviour
    ------------------
    - New symbols added to the watchlist are initialised automatically.
    - Symbols removed from the watchlist are dropped from the store.
    - Each update fetches the last 3 candles and appends all but the final one
      (which may still be forming).
    """

    def __init__(
        self,
        watchlist: Watchlist,
        store: OhlcvStore,
        http: Optional[HttpClient] = None,
    ):
        self.watchlist = watchlist
        self.store = store
        self._http = http or HttpClient(base_url="https://fapi.binance.com")
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    # ── public ───────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._stop.clear()
        for sym in self.watchlist.symbols():
            await self._init_symbol(sym)
        self._task = asyncio.create_task(self._run(), name="ohlcv_job")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            await asyncio.sleep(0)

    # ── internal loop ─────────────────────────────────────────────────────────

    async def _run(self) -> None:
        """Wait until the next minute boundary, then tick every 60 s."""
        await self._sleep_until_next_minute()
        while not self._stop.is_set():
            await self._tick()
            await asyncio.sleep(_TICK_SEC)

    async def _sleep_until_next_minute(self) -> None:
        """Sleep until a few seconds past the next UTC minute boundary."""
        now = time.time()
        secs_into_minute = now % 60
        wait = (60 - secs_into_minute) + 2   # +2 s buffer for candle close
        if wait > _TICK_SEC:
            wait -= _TICK_SEC
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass  # normal: stop was not set

    async def _tick(self) -> None:
        current = set(self.watchlist.symbols())
        stored  = set(self.store.symbols())

        # initialise new symbols
        for sym in current - stored:
            await self._init_symbol(sym)

        # remove dropped symbols
        for sym in stored - current:
            self.store.remove(sym)
            logger.info("OhlcvJob: removed %s from store", sym)

        # update existing symbols
        for sym in current & stored:
            try:
                await self._update_symbol(sym)
            except Exception as e:
                logger.warning("OhlcvJob: update failed for %s: %s", sym, e)

    # ── helpers ───────────────────────────────────────────────────────────────

    async def _init_symbol(self, symbol: str) -> None:
        try:
            raw = await asyncio.to_thread(
                self._fetch_klines_bulk, symbol, self.store.max_len
            )
            self.store.init_symbol(symbol, raw)
            logger.info("OhlcvJob: initialised %s (%d candles)", symbol, len(raw))
        except Exception as e:
            logger.warning("OhlcvJob: init failed for %s: %s", symbol, e)

    async def _update_symbol(self, symbol: str) -> None:
        raw = await asyncio.to_thread(self._fetch_klines, symbol, _INIT_FETCH)
        # skip the last row — it may still be forming
        added = 0
        for row in raw[:-1]:
            if self.store.append(symbol, row):
                added += 1
        if added:
            logger.debug("OhlcvJob: %s +%d row(s)", symbol, added)

    def _fetch_klines(self, symbol: str, limit: int) -> list:
        return self._http.get(
            "/fapi/v1/klines",
            params={"symbol": symbol, "interval": _INTERVAL, "limit": limit},
        )

    def _fetch_klines_bulk(self, symbol: str, total: int) -> list:
        """1500개 한도를 넘는 경우 startTime 기반으로 페이지네이션해서 시계열 순 반환."""
        if total <= _BINANCE_MAX_LIMIT:
            return self._fetch_klines(symbol, total)

        all_rows: list = []
        now_ms   = int(time.time() * 1000)
        start_ms = now_ms - total * 60 * 1000  # total 분 전부터 시작

        while len(all_rows) < total:
            chunk = min(_BINANCE_MAX_LIMIT, total - len(all_rows))
            rows = self._http.get(
                "/fapi/v1/klines",
                params={
                    "symbol":    symbol,
                    "interval":  _INTERVAL,
                    "startTime": start_ms,
                    "limit":     chunk,
                },
            )
            if not rows:
                break
            all_rows.extend(rows)
            # 마지막 캔들 open_time + 1분 → 다음 배치 시작점
            start_ms = int(rows[-1][0]) + 60_000

        return all_rows
