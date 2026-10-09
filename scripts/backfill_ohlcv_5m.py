"""
BTC/ETH/XRP 5개년치 5분봉(klines)을 바이낸스 선물 API에서 받아 로컬 DuckDB에 저장한다.

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
from crypto.market_data.ohlcv_db import DEFAULT_DB_PATH, DEFAULT_SYMBOLS, INTERVAL, INTERVAL_MS, Ohlcv5mRepository
from crypto.market_data.kline_fetch import fetch_and_store_range

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_ohlcv_5m")

_YEARS = 5


def backfill_symbol(http: HttpClient, db: Ohlcv5mRepository, symbol: str) -> None:
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - _YEARS * 365 * 24 * 60 * 60 * 1000

    latest = db.get_latest_open_time(symbol)
    if latest is not None:
        start_ms = max(start_ms, latest + INTERVAL_MS)
        logger.info("%s: 기존 DB 데이터 이후부터 이어받기 (open_time=%d)", symbol, latest)

    fetch_and_store_range(http, db, symbol, INTERVAL, INTERVAL_MS, start_ms, now_ms)
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
