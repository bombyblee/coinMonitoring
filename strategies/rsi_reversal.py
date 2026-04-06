from __future__ import annotations

from typing import Optional

import pandas as pd

from .base import BaseStrategy, Signal


# ATR 최소값 필터: 이보다 낮으면 TP/SL 범위가 너무 좁아 노이즈에 즉시 hit됨
_ATR_MIN: dict[str, float] = {
    "BTCUSDT": 50.0,
    "ETHUSDT": 3.0,
}
_ATR_MIN_DEFAULT = 1.0


class RsiReversal(BaseStrategy):
    """
    RSI 반전 전략 (Mean Reversion).

    Long  : RSI가 과매도(30) 아래에서 위로 크로스 + zscore 충분히 낮음 + 거래량 확인
    Short : RSI가 과매수(70) 위에서 아래로 크로스 + zscore 충분히 높음 + 거래량 확인
    """

    name = "RsiReversal"
    tp_mult = 2.5
    sl_mult = 2.5

    def detect(self, symbol: str, df: pd.DataFrame) -> Optional[Signal]:
        if len(df) < 21:
            return None

        atr_min = _ATR_MIN.get(symbol, _ATR_MIN_DEFAULT)
        if float(df.iloc[-1]["atr_14"]) < atr_min:
            return None

        prev = df.iloc[-2]
        row  = df.iloc[-1]

        # ── Long 조건 ──────────────────────────────────────────────────────────
        rsi_cross_up  = prev["rsi_14"] < 30 and row["rsi_14"] >= 30   # 과매도 탈출
        zscore_low    = prev["zscore_20"] < -1.5                       # 가격 충분히 떨어진 상태
        volume_ok     = row["vol_ratio"] > 1.2                         # 거래량 확인

        if rsi_cross_up and zscore_low and volume_ok:
            return Signal(
                symbol=symbol,
                direction="LONG",
                strategy=self.name,
                reason=(
                    f"RSI {prev['rsi_14']:.1f} → {row['rsi_14']:.1f} (과매도 탈출)\n"
                    f"zscore={prev['zscore_20']:.2f}  vol_ratio={row['vol_ratio']:.2f}\n"
                    f"close={row['close']:.4f}  bb_lower={row['bb_lower']:.4f}"
                ),
                atr=float(row["atr_14"]),
                tp_mult=self.tp_mult,
                sl_mult=self.sl_mult,
            )

        # ── Short 조건 ─────────────────────────────────────────────────────────
        rsi_cross_down = prev["rsi_14"] > 70 and row["rsi_14"] <= 70  # 과매수 탈출
        zscore_high    = prev["zscore_20"] > 1.5                       # 가격 충분히 올라간 상태
        volume_ok      = row["vol_ratio"] > 1.2

        if rsi_cross_down and zscore_high and volume_ok:
            return Signal(
                symbol=symbol,
                direction="SHORT",
                strategy=self.name,
                reason=(
                    f"RSI {prev['rsi_14']:.1f} → {row['rsi_14']:.1f} (과매수 탈출)\n"
                    f"zscore={prev['zscore_20']:.2f}  vol_ratio={row['vol_ratio']:.2f}\n"
                    f"close={row['close']:.4f}  bb_upper={row['bb_upper']:.4f}"
                ),
                atr=float(row["atr_14"]),
                tp_mult=self.tp_mult,
                sl_mult=self.sl_mult,
            )

        return None
