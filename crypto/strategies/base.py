from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class Signal:
    symbol: str
    direction: str   # "LONG" or "SHORT"
    strategy: str    # strategy name
    reason: str      # condition summary for Telegram message
    atr: float = 0.0       # detect() 시점 해당 timeframe ATR (executor에서 우선 사용)
    tp_mult: float = 3.5   # ATR 배수: 익절 (전략별 오버라이드)
    sl_mult: float = 3.0   # ATR 배수: 손절 (전략별 오버라이드)


class BaseStrategy:
    name: str = "base"
    timeframe: str = "1min"   # runner가 리샘플링에 사용 ("1min" = 원본 그대로)

    def detect(self, symbol: str, df: pd.DataFrame) -> Optional[Signal]:
        """
        Inspect the latest row of df and return a Signal if conditions are met,
        or None otherwise.
        """
        raise NotImplementedError
