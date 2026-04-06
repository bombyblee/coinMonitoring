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
    atr: float = 0.0         # detect() 시점 해당 timeframe ATR (executor에서 우선 사용)
    tp_mult: float = 3.5     # ATR 배수: 익절 (전략별 오버라이드)
    sl_mult: float = 3.0     # ATR 배수: 손절 (전략별 오버라이드)
    level_price: float = 0.0 # 기준 레벨 가격 (LevelAware: add 조건 검증용)
    adx: float = 0.0         # 신호 시점 ADX (REVERSION add 조건 검증용)


class BaseStrategy:
    name: str = "base"
    timeframe: str = "1min"   # runner가 리샘플링에 사용 ("1min" = 원본 그대로)
    tp_mult: float = 3.5      # 클래스 기본값 (서브클래스에서 오버라이드)
    sl_mult: float = 3.0

    def __init__(self, tp_mult: float = None, sl_mult: float = None):
        # 인자가 주어지면 인스턴스 속성으로 덮어씀, 아니면 클래스 기본값 사용
        if tp_mult is not None:
            self.tp_mult = tp_mult
        if sl_mult is not None:
            self.sl_mult = sl_mult

    def detect(self, symbol: str, df: pd.DataFrame) -> Optional[Signal]:
        """
        Inspect the latest row of df and return a Signal if conditions are met,
        or None otherwise.
        """
        raise NotImplementedError
