from __future__ import annotations

from typing import Optional

import pandas as pd

from crypto.market_data.ohlcv_store import _compute as _compute_indicators
from .base import BaseStrategy, Signal
from .regime_detector import detect_regime
from .level_finder import find_levels, Level

_RESAMPLE_TF           = "15min"
_NEAR_ATR_MULT         = 0.8   # 현재가 기준 ±ATR*0.8 이내 레벨만 유효 (1.2 → 0.8 타이트하게)
_VOL_THRESHOLD         = 2.0   # vol_ratio 최소 기준 (1.5 → 2.0 강화)
_MIN_STRENGTH          = 2     # 최소 pivot 터치 수 (REVERSION용)
_MOMENTUM_MIN_STRENGTH = 4     # MOMENTUM 진입 시 최소 레벨 강도 (강도:2~3은 신뢰도 낮음)
_MOMENTUM_ADX          = 28    # MOMENTUM 레짐 최소 ADX (regime 25 위에 추가 필터)


def _resample_15m(df: pd.DataFrame) -> pd.DataFrame:
    """1min df → 15min 리샘플 + 지표 재계산."""
    base = df[["open", "high", "low", "close", "volume"]].resample(_RESAMPLE_TF).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna()
    return _compute_indicators(base)


class LevelAware(BaseStrategy):
    """
    레짐 인식 + 지지/저항 레벨 기반 전략.

    데이터 흐름:
      - 1min df 원본: 1min 진입 지표(RSI, 거래량) 사용
      - 15min 리샘플: 레짐(ADX) + 레벨(pivot) 탐지에 사용

    시그널 로직:
      MOMENTUM (+DI > -DI, ADX≥25):
        저항 위로 돌파 (close > level + 거래량) → LONG
        지지 아래로 붕괴 (-DI > +DI)           → SHORT

      REVERSION (ADX≤20):
        지지 근접 + RSI < 40                  → LONG
        저항 근접 + RSI > 60                  → SHORT
    """

    name      = "LevelAware"
    timeframe = "1min"
    tp_mult   = 3.0
    sl_mult   = 2.5

    def detect(self, symbol: str, df: pd.DataFrame) -> Optional[Signal]:
        if len(df) < 90:   # 15min 6봉 이상 확보 가능한 최소치
            return None

        # ── 1min 기준 진입 지표 ──────────────────────────────────────────────
        row   = df.iloc[-1]
        close = float(row["close"])
        rsi   = float(row["rsi_14"])
        vol_r = float(row["vol_ratio"])

        # ── 15min 리샘플: 레짐 + 레벨 + ATR ─────────────────────────────────
        df_15m = _resample_15m(df)
        if len(df_15m) < 10:
            return None

        # TP/SL은 15min ATR 기준 (레벨 간격과 스케일 일치)
        atr = float(df_15m["atr_14"].iloc[-1])
        if atr == 0:
            return None

        regime = detect_regime(df_15m)
        levels = find_levels(df_15m)
        if not levels:
            return None

        # 현재가에서 ATR*_NEAR_ATR_MULT 이내 레벨만 필터
        near_atr = atr * _NEAR_ATR_MULT
        nearby   = [l for l in levels if abs(l.price - close) <= near_atr]
        if not nearby:
            return None

        # 가장 가까운 레벨 (강도 최소 기준 필터 적용)
        nearby = [l for l in nearby if l.strength >= _MIN_STRENGTH]
        if not nearby:
            return None

        nearest: Level = min(nearby, key=lambda l: abs(l.price - close))
        vol_ok = vol_r >= _VOL_THRESHOLD

        # ── MOMENTUM 레짐: 돌파/붕괴 전략 ───────────────────────────────────
        if regime.mode == "MOMENTUM" and regime.adx >= _MOMENTUM_ADX:
            # 저항 상향 돌파 → LONG (레벨 강도 최소 4 이상)
            if (nearest.kind == "resistance"
                    and close > nearest.price
                    and vol_ok
                    and regime.trend_up
                    and nearest.strength >= _MOMENTUM_MIN_STRENGTH):
                return Signal(
                    symbol=symbol,
                    direction="LONG",
                    strategy=self.name,
                    reason=(
                        f"[MOMENTUM] 저항 돌파\n"
                        f"close={close:.4f}  level={nearest.price:.4f} (강도:{nearest.strength})\n"
                        f"ADX={regime.adx:.1f}  vol_ratio={vol_r:.2f}  rsi={rsi:.1f}"
                    ),
                    atr=atr,
                    tp_mult=self.tp_mult,
                    sl_mult=self.sl_mult,
                    level_price=nearest.price,
                    adx=regime.adx,
                )

            # 지지 하향 붕괴 → SHORT (레벨 강도 최소 4 이상)
            if (nearest.kind == "support"
                    and close < nearest.price
                    and vol_ok
                    and not regime.trend_up
                    and nearest.strength >= _MOMENTUM_MIN_STRENGTH):
                return Signal(
                    symbol=symbol,
                    direction="SHORT",
                    strategy=self.name,
                    reason=(
                        f"[MOMENTUM] 지지 붕괴\n"
                        f"close={close:.4f}  level={nearest.price:.4f} (강도:{nearest.strength})\n"
                        f"ADX={regime.adx:.1f}  vol_ratio={vol_r:.2f}  rsi={rsi:.1f}"
                    ),
                    atr=atr,
                    tp_mult=self.tp_mult,
                    sl_mult=self.sl_mult,
                    level_price=nearest.price,
                    adx=regime.adx,
                )

        # ── REVERSION 레짐: 반전 전략 ────────────────────────────────────────
        elif regime.mode == "REVERSION":
            # 지지 반등 → LONG (RSI 35 미만으로 강화)
            if nearest.kind == "support" and rsi < 35 and vol_ok:
                return Signal(
                    symbol=symbol,
                    direction="LONG",
                    strategy=self.name,
                    reason=(
                        f"[REVERSION] 지지 반등\n"
                        f"close={close:.4f}  level={nearest.price:.4f} (강도:{nearest.strength})\n"
                        f"ADX={regime.adx:.1f}  rsi={rsi:.1f}  vol_ratio={vol_r:.2f}"
                    ),
                    atr=atr,
                    tp_mult=self.tp_mult,
                    sl_mult=self.sl_mult,
                    level_price=nearest.price,
                    adx=regime.adx,
                )

            # 저항 거부 → SHORT (RSI 65 초과로 강화)
            if nearest.kind == "resistance" and rsi > 65 and vol_ok:
                return Signal(
                    symbol=symbol,
                    direction="SHORT",
                    strategy=self.name,
                    reason=(
                        f"[REVERSION] 저항 거부\n"
                        f"close={close:.4f}  level={nearest.price:.4f} (강도:{nearest.strength})\n"
                        f"ADX={regime.adx:.1f}  rsi={rsi:.1f}  vol_ratio={vol_r:.2f}"
                    ),
                    atr=atr,
                    tp_mult=self.tp_mult,
                    sl_mult=self.sl_mult,
                    level_price=nearest.price,
                    adx=regime.adx,
                )

        return None
