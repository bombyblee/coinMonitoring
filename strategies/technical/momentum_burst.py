from __future__ import annotations

from typing import Optional

import pandas as pd

from ..base import BaseStrategy, Signal


class MomentumBurst(BaseStrategy):
    """
    단기 모멘텀 버스트 전략.

    Long  : 3봉 상승 모멘텀 + 거래량 급증 + 상승 추세 + 과열 아님
    Short : 3봉 하락 모멘텀 + 거래량 급증 + 하락 추세 + 과매도 아님
    """

    name = "MomentumBurst"
    timeframe = "3min"
    tp_mult = 3.5
    sl_mult = 3.0

    def detect(self, symbol: str, df: pd.DataFrame) -> Optional[Signal]:
        if len(df) < 20:
            return None

        row = df.iloc[-1]

        # ── Long 조건 ──────────────────────────────────────────────────────────
        momentum_ok = row["ret_3"] > 0.0025                              # 3봉 +0.25% 이상
        volume_ok   = row["vol_ratio"] > 1.8                             # 거래량 20평균 1.8배 이상
        trend_ok    = (row["ema_5"] > row["ema_20"]
                       and row["close"] > row["ema_20"])                 # 단·중기 정배열
        not_too_hot = row["rsi_14"] < 78 and row["zscore_20"] < 2.2     # 과열 아님
        adx_ok      = row["adx_14"] >= 25                                # 추세 강도 확인

        if momentum_ok and volume_ok and trend_ok and not_too_hot and adx_ok:
            return Signal(
                symbol=symbol,
                direction="LONG",
                strategy=self.name,
                reason=(
                    f"ret3={row['ret_3']:.3%}  vol_ratio={row['vol_ratio']:.2f}\n"
                    f"ema5={row['ema_5']:.2f}  ema20={row['ema_20']:.2f}  close={row['close']:.2f}\n"
                    f"rsi={row['rsi_14']:.1f}  zscore={row['zscore_20']:.2f}"
                ),
                atr=float(row["atr_14"]),
                tp_mult=self.tp_mult,
                sl_mult=self.sl_mult,
            )

        # ── Short 조건 ─────────────────────────────────────────────────────────
        momentum_ok  = row["ret_3"] < -0.0025                            # 3봉 -0.25% 이하
        volume_ok    = row["vol_ratio"] > 1.8                            # 거래량 급증
        trend_ok     = row["ema_5"] < row["ema_20"]                      # 단기 < 중기 (역배열)
        not_too_cold = row["rsi_14"] > 22 and row["zscore_20"] > -2.2   # 과매도 아님
        adx_ok       = row["adx_14"] >= 25                               # 추세 강도 확인

        if momentum_ok and volume_ok and trend_ok and not_too_cold and adx_ok:
            return Signal(
                symbol=symbol,
                direction="SHORT",
                strategy=self.name,
                reason=(
                    f"ret3={row['ret_3']:.3%}  vol_ratio={row['vol_ratio']:.2f}\n"
                    f"ema5={row['ema_5']:.2f}  ema20={row['ema_20']:.2f}  close={row['close']:.2f}\n"
                    f"rsi={row['rsi_14']:.1f}  zscore={row['zscore_20']:.2f}"
                ),
                atr=float(row["atr_14"]),
                tp_mult=self.tp_mult,
                sl_mult=self.sl_mult,
            )

        return None
