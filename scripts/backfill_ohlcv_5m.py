"""
BTC/ETH/XRP 5개년치 5분봉(klines)을 바이낸스 선물 API에서 받아 로컬 SQLite DB에 저장한다.

사용법:
    python scripts/backfill_ohlcv_5m.py                  # 기본 심볼(BTCUSDT,ETHUSDT,XRPUSDT)
    python scripts/backfill_ohlcv_5m.py BTCUSDT ETHUSDT   # 심볼 지정

이미 저장된 데이터가 있으면 마지막으로 저장된 open_time 다음부터 이어받는다 (재실행 안전).
"""
from __future__ import annotations

import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crypto.binance.http_client import HttpClient
from crypto.market_data.ohlcv_db import DEFAULT_DB_PATH, DEFAULT_SYMBOLS, Ohlcv5mRepository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_ohlcv_5m")

_INTERVAL = "5m"
_INTERVAL_MS = 5 * 60 * 1000
_MAX_LIMIT = 1500
_YEARS = 5
_SLEEP_BETWEEN_REQ = 0.3  # 레이트리밋 여유


def backfill_symbol(http: HttpClient, db: Ohlcv5mRepository, symbol: str) -> None:
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - _YEARS * 365 * 24 * 60 * 60 * 1000

    latest = db.get_latest_open_time(symbol)
    if latest is not None:
        start_ms = max(start_ms, latest + _INTERVAL_MS)
        logger.info("%s: 기존 DB 데이터 이후부터 이어받기 (open_time=%d)", symbol, latest)

    cursor = start_ms
    total = 0
    while cursor < now_ms:
        rows = http.get(
            "/fapi/v1/klines",
            params={
                "symbol": symbol,
                "interval": _INTERVAL,
                "startTime": cursor,
                "limit": _MAX_LIMIT,
            },
        )
        if not rows:
            break

        # 아직 마감되지 않은(forming) 캔들은 저장하지 않음
        closed = [r for r in rows if int(r[0]) + _INTERVAL_MS <= now_ms]
        if closed:
            total += db.upsert_klines(symbol, closed)

        next_cursor = int(rows[-1][0]) + _INTERVAL_MS
        if next_cursor <= cursor:
            break  # 진행이 없으면 중단 (안전장치)
        cursor = next_cursor

        logger.info(
            "%s: %s 까지 수집 (누적 %d행, DB 전체 %d행)",
            symbol,
            time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(cursor / 1000)),
            total,
            db.count(symbol),
        )
        time.sleep(_SLEEP_BETWEEN_REQ)

    logger.info("%s: 완료 (DB 전체 %d행)", symbol, db.count(symbol))


def main() -> None:
    symbols = sys.argv[1:] or DEFAULT_SYMBOLS
    logger.info("DB 경로: %s", os.path.abspath(DEFAULT_DB_PATH))
    logger.info("대상 심볼: %s", ", ".join(symbols))

    http = HttpClient(base_url="https://fapi.binance.com")
    db = Ohlcv5mRepository(DEFAULT_DB_PATH)
    db.init_schema()

    for sym in symbols:
        logger.info("=== %s 백필 시작 (최근 %d년) ===", sym, _YEARS)
        try:
            backfill_symbol(http, db, sym)
        except Exception:
            logger.exception("%s 백필 중 오류 발생", sym)


if __name__ == "__main__":
    main()
