from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Regime:
    mode: str       # "MOMENTUM" | "REVERSION" | "NEUTRAL"
    adx: float
    trend_up: bool  # True if +DI > -DI (상승 방향 모멘텀)


def detect_regime(df: pd.DataFrame) -> Regime:
    """
    ADX 기반으로 시장 레짐을 판단한다.

    ADX >= 25 → MOMENTUM  (추세 강함, 돌파/추종 전략 유리)
    ADX <= 20 → REVERSION (횡보, 지지/저항 반전 전략 유리)
    20 < ADX < 25 → NEUTRAL
    """
    if len(df) < 30 or "adx_14" not in df.columns:
        return Regime(mode="NEUTRAL", adx=0.0, trend_up=True)

    row = df.iloc[-1]
    adx      = float(row["adx_14"])
    trend_up = float(row["plus_di"]) >= float(row["minus_di"])

    if adx >= 25:
        mode = "MOMENTUM"
    elif adx <= 20:
        mode = "REVERSION"
    else:
        mode = "NEUTRAL"

    return Regime(mode=mode, adx=adx, trend_up=trend_up)
