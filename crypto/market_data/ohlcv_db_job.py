from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from crypto.binance.http_client import HttpClient
from .ohlcv_db import INTERVAL, INTERVAL_MS, Ohlcv5mRepository
from .kline_fetch import fetch_and_store_range

logger = logging.getLogger(__name__)

_INTERVAL   = INTERVAL
_TICK_SEC   = 300    # 5분 polling interval
_FETCH_LIMIT = 3     # 마지막 캔들은 forming 중일 수 있어 여유 있게 조회
_CATCH_UP_DAYS = 90  # 기동 시 다시 받아와 구멍을 메울 최근 구간
_TAIL_TOPUP_DAYS = 1  # 심볼별 캐치업을 순차 처리하는 동안 흐른 시간만큼의 꼬리 공백 마무리


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
        self._catchup_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    # ── public ───────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        캐치업은 백그라운드 태스크로 돌리고 바로 반환한다 — 캐치업이 오래 걸려도
        main.py의 나머지 기동 순서(전략 러너, Telegram 폴링 등)를 막지 않는다.
        5분 polling 루프도 캐치업과 별개로 바로 시작된다.
        """
        self._stop.clear()
        await asyncio.to_thread(self.db.init_schema)
        self._catchup_task = asyncio.create_task(self._catch_up_all(), name="ohlcv_5m_catchup")
        self._task = asyncio.create_task(self._run(), name="ohlcv_5m_db_job")

    async def stop(self) -> None:
        self._stop.set()
        if self._catchup_task:
            self._catchup_task.cancel()
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

    # ── startup catch-up ─────────────────────────────────────────────────────

    async def _catch_up_all(self) -> None:
        """
        기동 시 최근 _CATCH_UP_DAYS일 구간 전체를 다시 받아 upsert한다.
        (마지막 저장 시점 이후뿐 아니라, 그 구간 중간에 생긴 결측 캔들도 함께 메워진다)

        심볼을 순차로 처리하므로, 전체 캐치업이 오래 걸리면 먼저 처리된 심볼에는
        그 사이 흐른 시간만큼 꼬리 공백이 생길 수 있다 — 모든 심볼의 1차 캐치업이
        끝난 뒤 짧은 구간(1일)으로 한 번 더 돌려서 그 꼬리를 마무리로 메운다.
        """
        for sym in self.symbols:
            try:
                await asyncio.to_thread(self._catch_up_symbol, sym, _CATCH_UP_DAYS)
            except Exception as e:
                logger.warning("Ohlcv5mDbJob: catch-up failed for %s: %s", sym, e)

        for sym in self.symbols:
            try:
                await asyncio.to_thread(self._catch_up_symbol, sym, _TAIL_TOPUP_DAYS)
            except Exception as e:
                logger.warning("Ohlcv5mDbJob: tail top-up failed for %s: %s", sym, e)

    def _catch_up_symbol(self, symbol: str, days: int) -> None:
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - days * 24 * 60 * 60 * 1000

        logger.info("Ohlcv5mDbJob: %s catch-up (최근 %d일 재조회)", symbol, days)
        n = fetch_and_store_range(
            self._http, self.db, symbol, _INTERVAL, INTERVAL_MS, start_ms, now_ms,
            log_progress=False,
        )
        logger.info(
            "Ohlcv5mDbJob: %s catch-up done (%d rows upserted, DB 전체 %d행)",
            symbol, n, self.db.count(symbol),
        )

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
