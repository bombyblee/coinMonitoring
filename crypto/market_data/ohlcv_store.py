from __future__ import annotations

import numpy as np
import pandas as pd


# ── Binance kline row parser ────────────────────────────────────────────────

def _klines_to_df(raw_rows: list[list]) -> pd.DataFrame:
    """Convert raw Binance kline rows to a DataFrame indexed by open_time (UTC)."""
    records = []
    index = []
    for row in raw_rows:
        index.append(pd.Timestamp(int(row[0]), unit="ms", tz="UTC"))
        records.append({
            "open":   float(row[1]),
            "high":   float(row[2]),
            "low":    float(row[3]),
            "close":  float(row[4]),
            "volume": float(row[5]),
        })
    df = pd.DataFrame(records, index=pd.DatetimeIndex(index, name="open_time"))
    return df


def _kline_row_to_series(raw_row: list) -> pd.Series:
    ts = pd.Timestamp(int(raw_row[0]), unit="ms", tz="UTC")
    return pd.Series(
        {
            "open":   float(raw_row[1]),
            "high":   float(raw_row[2]),
            "low":    float(raw_row[3]),
            "close":  float(raw_row[4]),
            "volume": float(raw_row[5]),
        },
        name=ts,
    )


# ── Indicator computation ────────────────────────────────────────────────────

def _compute(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all indicators in-place and return the DataFrame."""
    c = df["close"]
    h = df["high"]
    lo = df["low"]
    v = df["volume"]

    # Returns
    df["ret_1"] = c.pct_change(1)
    df["ret_3"] = c.pct_change(3)

    # EMAs
    df["ema_5"]  = c.ewm(span=5,  adjust=False).mean()
    df["ema_20"] = c.ewm(span=20, adjust=False).mean()

    # Volume
    df["vol_ma_20"] = v.rolling(20, min_periods=1).mean()
    df["vol_ratio"] = v / df["vol_ma_20"].replace(0, np.nan)

    # RSI 14 — Wilder's smoothing (com = period - 1)
    delta     = c.diff()
    gain      = delta.clip(lower=0)
    loss      = (-delta).clip(lower=0)
    avg_gain  = gain.ewm(com=13, adjust=False).mean()
    avg_loss  = loss.ewm(com=13, adjust=False).mean()
    rs        = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi_14"] = 100 - 100 / (1 + rs)

    # ATR 14 — Wilder's smoothing
    prev_c    = c.shift(1)
    tr        = pd.concat(
        [h - lo, (h - prev_c).abs(), (lo - prev_c).abs()], axis=1
    ).max(axis=1)
    df["atr_14"] = tr.ewm(com=13, adjust=False).mean()

    # Rolling 20-bar high / low
    df["high_20"] = h.rolling(20, min_periods=1).max()
    df["low_20"]  = lo.rolling(20, min_periods=1).min()

    # Bollinger Bands (20, 2σ)
    bb_mid         = c.rolling(20, min_periods=1).mean()
    bb_std         = c.rolling(20, min_periods=1).std()
    df["bb_mid"]   = bb_mid
    df["bb_std"]   = bb_std
    df["bb_upper"] = bb_mid + 2 * bb_std
    df["bb_lower"] = bb_mid - 2 * bb_std

    # Z-score (20)
    df["zscore_20"] = (c - bb_mid) / bb_std.replace(0, np.nan)

    # ADX 14 + DI (Wilder smoothing, com=13)
    high_diff  = h.diff()
    low_diff   = lo.shift(1) - lo
    plus_dm    = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0.0)
    minus_dm   = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0.0)
    s_plus_dm  = plus_dm.ewm(com=13, adjust=False).mean()
    s_minus_dm = minus_dm.ewm(com=13, adjust=False).mean()
    plus_di    = 100 * s_plus_dm  / df["atr_14"].replace(0, np.nan)
    minus_di   = 100 * s_minus_dm / df["atr_14"].replace(0, np.nan)
    dx         = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["adx_14"]   = dx.ewm(com=13, adjust=False).mean()
    df["plus_di"]  = plus_di
    df["minus_di"] = minus_di

    return df


# ── Store ────────────────────────────────────────────────────────────────────

class OhlcvStore:
    """
    In-memory rolling OHLCV + indicator store.

    One DataFrame per symbol, capped at `max_len` rows.
    Indicators are recomputed after every update.
    """

    def __init__(self, max_len: int = 1000):
        self.max_len = max_len
        self._data: dict[str, pd.DataFrame] = {}

    # ── write ────────────────────────────────────────────────────────────────

    def init_symbol(self, symbol: str, raw_rows: list[list]) -> None:
        """Initialize (or re-initialize) a symbol from a list of raw kline rows."""
        df = _klines_to_df(raw_rows)
        if len(df) > self.max_len:
            df = df.iloc[-self.max_len :]
        self._data[symbol] = _compute(df)

    def append(self, symbol: str, raw_row: list) -> bool:
        """
        Append a single completed kline row.
        Skips the row if its timestamp already exists.
        Returns True if a new row was added.
        """
        if symbol not in self._data:
            return False

        new_series = _kline_row_to_series(raw_row)
        ts = new_series.name
        df = self._data[symbol]

        if ts in df.index:
            return False

        new_df = pd.concat([df, new_series.to_frame().T])
        new_df.index.name = "open_time"
        if len(new_df) > self.max_len:
            new_df = new_df.iloc[-self.max_len :]

        self._data[symbol] = _compute(new_df)
        return True

    def remove(self, symbol: str) -> None:
        self._data.pop(symbol, None)

    # ── read ─────────────────────────────────────────────────────────────────

    def get(self, symbol: str) -> pd.DataFrame | None:
        """Return the DataFrame for a symbol, or None if not loaded."""
        return self._data.get(symbol)

    def get_last(self, symbol: str) -> pd.Series | None:
        """Return the most recent row as a Series, or None."""
        df = self._data.get(symbol)
        return df.iloc[-1] if df is not None and len(df) > 0 else None

    def symbols(self) -> list[str]:
        return list(self._data.keys())

    def __contains__(self, symbol: str) -> bool:
        return symbol in self._data

    def __repr__(self) -> str:
        parts = {s: len(df) for s, df in self._data.items()}
        return f"OhlcvStore({parts})"
