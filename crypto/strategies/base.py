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
    tp_mult: float = 3.5   # ATR 배수: 익절 (전략별 오버라이드)
    sl_mult: float = 3.0   # ATR 배수: 손절 (전략별 오버라이드)


class BaseStrategy:
    name: str = "base"

    def detect(self, symbol: str, df: pd.DataFrame) -> Optional[Signal]:
        """
        Inspect the latest row of df and return a Signal if conditions are met,
        or None otherwise.
        """
        raise NotImplementedError
