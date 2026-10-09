from __future__ import annotations

import logging
import time

from crypto.binance.http_client import HttpClient
from .ohlcv_db import Ohlcv5mRepository

logger = logging.getLogger(__name__)

_MAX_LIMIT = 1500
_SLEEP_BETWEEN_REQ = 0.3  # 레이트리밋 여유


def fetch_and_store_range(
    http: HttpClient,
    db: Ohlcv5mRepository,
    symbol: str,
    interval: str,
    interval_ms: int,
    start_ms: int,
    end_ms: int | None = None,
    log_progress: bool = True,
) -> int:
    """
    [start_ms, end_ms) 구간의 klines를 startTime 페이지네이션으로 받아 DB에 upsert한다.
    아직 마감되지 않은(forming) 캔들은 저장하지 않는다. 저장된 행 수를 반환한다.
    """
    end_ms = end_ms if end_ms is not None else int(time.time() * 1000)
    cursor = start_ms
    total = 0

    while cursor < end_ms:
        rows = http.get(
            "/fapi/v1/klines",
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "limit": _MAX_LIMIT,
            },
        )
        if not rows:
            break

        closed = [r for r in rows if int(r[0]) + interval_ms <= end_ms]
        if closed:
            total += db.upsert_klines(symbol, closed)

        next_cursor = int(rows[-1][0]) + interval_ms
        if next_cursor <= cursor:
            break  # 진행이 없으면 중단 (안전장치)
        cursor = next_cursor

        if log_progress:
            logger.info(
                "%s: %s 까지 수집 (누적 %d행, DB 전체 %d행)",
                symbol,
                time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(cursor / 1000)),
                total,
                db.count(symbol),
            )

        if len(rows) < _MAX_LIMIT:
            break
        time.sleep(_SLEEP_BETWEEN_REQ)

    return total
