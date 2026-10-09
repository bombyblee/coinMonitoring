from __future__ import annotations

import os
from typing import Optional

import duckdb

DEFAULT_DB_PATH = os.getenv("OHLCV_DB_PATH", "data/market_data.duckdb")
DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
INTERVAL = "5m"
INTERVAL_MS = 5 * 60 * 1000


class Ohlcv5mRepository:
    """DuckDB 기반 5분봉 OHLCV 영구 저장소 (백테스팅/분석용)."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.db_path)

    def init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ohlcv_5m (
                    symbol     VARCHAR NOT NULL,
                    open_time  BIGINT  NOT NULL,
                    open       DOUBLE  NOT NULL,
                    high       DOUBLE  NOT NULL,
                    low        DOUBLE  NOT NULL,
                    close      DOUBLE  NOT NULL,
                    volume     DOUBLE  NOT NULL,
                    close_time BIGINT  NOT NULL,
                    PRIMARY KEY (symbol, open_time)
                )
                """
            )
        finally:
            conn.close()

    def upsert_klines(self, symbol: str, raw_rows: list[list]) -> int:
        """Binance raw kline row 리스트를 upsert하고 적용된 row 수를 반환한다."""
        if not raw_rows:
            return 0
        records = [
            (
                symbol,
                int(row[0]),
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                float(row[5]),
                int(row[6]),
            )
            for row in raw_rows
        ]
        conn = self._connect()
        try:
            conn.executemany(
                """
                INSERT INTO ohlcv_5m (symbol, open_time, open, high, low, close, volume, close_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol, open_time) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume, close_time=excluded.close_time
                """,
                records,
            )
        finally:
            conn.close()
        return len(records)

    def get_latest_open_time(self, symbol: str) -> Optional[int]:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT MAX(open_time) FROM ohlcv_5m WHERE symbol = ?", [symbol]
            ).fetchone()
        finally:
            conn.close()
        return int(row[0]) if row and row[0] is not None else None

    def count(self, symbol: str) -> int:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM ohlcv_5m WHERE symbol = ?", [symbol]
            ).fetchone()
        finally:
            conn.close()
        return int(row[0]) if row else 0
