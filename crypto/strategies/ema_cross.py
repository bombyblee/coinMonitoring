from __future__ import annotations

from typing import Optional

import pandas as pd

from .base import BaseStrategy, Signal


class EmaCross(BaseStrategy):
    """
    EMA 골든/데드크로스 전략.

    Long  : ema_5가 ema_20을 상향 돌파 (골든크로스) + RSI 적정 구간 + 거래량 확인
    Short : ema_5가 ema_20을 하향 돌파 (데드크로스) + RSI 적정 구간 + 거래량 확인
    """

    name = "EmaCross"

    def detect(self, symbol: str, df: pd.DataFrame) -> Optional[Signal]:
        if len(df) < 21:
            return None

        prev = df.iloc[-2]
        row  = df.iloc[-1]

        # ── Long 조건 (골든크로스) ─────────────────────────────────────────────
        golden_cross = (
            prev["ema_5"] <= prev["ema_20"]
            and row["ema_5"] > row["ema_20"]
        )
        rsi_ok    = 40 <= row["rsi_14"] <= 70     # 상승 모멘텀 구간, 과열 아님
        volume_ok = row["vol_ratio"] > 1.3

        if golden_cross and rsi_ok and volume_ok:
            return Signal(
                symbol=symbol,
                direction="LONG",
                strategy=self.name,
                reason=(
                    f"골든크로스: ema5={row['ema_5']:.4f} > ema20={row['ema_20']:.4f}\n"
                    f"rsi={row['rsi_14']:.1f}  vol_ratio={row['vol_ratio']:.2f}\n"
                    f"close={row['close']:.4f}"
                ),
                tp_mult=4.0,
                sl_mult=2.5,
            )

        # ── Short 조건 (데드크로스) ────────────────────────────────────────────
        dead_cross = (
            prev["ema_5"] >= prev["ema_20"]
            and row["ema_5"] < row["ema_20"]
        )
        rsi_ok    = 30 <= row["rsi_14"] <= 60     # 하락 모멘텀 구간, 과매도 아님
        volume_ok = row["vol_ratio"] > 1.3

        if dead_cross and rsi_ok and volume_ok:
            return Signal(
                symbol=symbol,
                direction="SHORT",
                strategy=self.name,
                reason=(
                    f"데드크로스: ema5={row['ema_5']:.4f} < ema20={row['ema_20']:.4f}\n"
                    f"rsi={row['rsi_14']:.1f}  vol_ratio={row['vol_ratio']:.2f}\n"
                    f"close={row['close']:.4f}"
                ),
                tp_mult=4.0,
                sl_mult=2.5,
            )

        return None
