from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Level:
    price: float
    strength: int  # 해당 레벨에 포함된 pivot 터치 수
    kind: str      # "support" | "resistance"


def find_levels(
    df: pd.DataFrame,
    n_side: int = 3,
    cluster_atr_mult: float = 0.5,
    max_levels: int = 5,
) -> list[Level]:
    """
    Pivot High/Low 기반으로 지지/저항 레벨을 탐지한다.

    Args:
        df:               지표가 계산된 OHLCV DataFrame (atr_14 필요)
        n_side:           pivot 판단 시 양쪽으로 비교할 봉 수
        cluster_atr_mult: 이 배수 * ATR 이내면 같은 레벨로 묶음
        max_levels:       반환할 최대 레벨 수 (강도 내림차순)

    Returns:
        지지/저항 Level 리스트 (강도 내림차순)
    """
    min_bars = n_side * 2 + 1
    if len(df) < min_bars or "atr_14" not in df.columns:
        return []

    atr = float(df["atr_14"].iloc[-1])
    if atr == 0:
        return []

    highs = df["high"].values
    lows  = df["low"].values

    pivot_highs: list[float] = []
    pivot_lows:  list[float] = []

    for i in range(n_side, len(df) - n_side):
        if (all(highs[i] > highs[i - j] for j in range(1, n_side + 1))
                and all(highs[i] > highs[i + j] for j in range(1, n_side + 1))):
            pivot_highs.append(float(highs[i]))

        if (all(lows[i] < lows[i - j] for j in range(1, n_side + 1))
                and all(lows[i] < lows[i + j] for j in range(1, n_side + 1))):
            pivot_lows.append(float(lows[i]))

    cluster_gap = atr * cluster_atr_mult

    def _cluster(pivots: list[float], kind: str) -> list[Level]:
        if not pivots:
            return []
        sorted_p = sorted(pivots)
        groups: list[list[float]] = [[sorted_p[0]]]
        for p in sorted_p[1:]:
            if p - groups[-1][-1] <= cluster_gap:
                groups[-1].append(p)
            else:
                groups.append([p])
        levels = [
            Level(price=float(np.mean(g)), strength=len(g), kind=kind)
            for g in groups
        ]
        return sorted(levels, key=lambda l: -l.strength)[:max_levels]

    return _cluster(pivot_lows, "support") + _cluster(pivot_highs, "resistance")
