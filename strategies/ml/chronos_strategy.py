from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np
import pandas as pd
import torch

from strategies.base import BaseStrategy, Signal

logger = logging.getLogger(__name__)

_MODEL_ID   = os.getenv("CHRONOS_MODEL",      "amazon/chronos-t5-small")
_MAX_CONTEXT = int(os.getenv("CHRONOS_CONTEXT",   "512"))   # 모델 최대 context (512 권장)
_HORIZON    = int(os.getenv("CHRONOS_HORIZON",    "12"))    # 예측 스텝 수 (5min봉 기준 1시간)
_THRESHOLD       = float(os.getenv("CHRONOS_THRESHOLD",       "0.005"))  # 시그널 발생 임계값 (0.5%)
_MAX_UNCERTAINTY = float(os.getenv("CHRONOS_MAX_UNCERTAINTY", "0.025"))  # 불확실도 상한 (2.5%)
_SAMPLES         = int(os.getenv("CHRONOS_SAMPLES",           "20"))     # 확률 샘플 수


def _select_dtype(device: str) -> torch.dtype:
    if device == "cpu":
        return torch.float32
    # bfloat16은 Ampere(RTX 3070 등, compute >= 8.0) 이상에서만 사용
    major = torch.cuda.get_device_capability()[0]
    return torch.bfloat16 if major >= 8 else torch.float16


class ChronosStrategy(BaseStrategy):
    """
    Amazon Chronos 시계열 예측 기반 전략.

    5분봉 close 가격 _CONTEXT개 → _HORIZON 스텝 앞을 확률적으로 예측,
    중앙값 기준 현재가 대비 _THRESHOLD 이상 움직임이 예측되면 시그널 발생.
    모델은 첫 detect() 호출 시 한 번만 로드 (lazy loading).
    """

    name      = "Chronos"
    timeframe = "5min"
    tp_mult   = 3.0
    sl_mult   = 2.5

    def __init__(self, tp_mult: float = None, sl_mult: float = None):
        super().__init__(tp_mult=tp_mult, sl_mult=sl_mult)
        self._pipeline = None

    # ── model ────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        from chronos import ChronosPipeline  # lazy import — chronos 미설치 시 에러를 여기서만 발생

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype  = _select_dtype(device)
        logger.info("Chronos 모델 로딩: %s  device=%s  dtype=%s", _MODEL_ID, device, dtype)

        self._pipeline = ChronosPipeline.from_pretrained(
            _MODEL_ID,
            device_map=device,
            torch_dtype=dtype,
        )
        logger.info("Chronos 모델 로딩 완료")

    # ── detect ────────────────────────────────────────────────────────────────

    def detect(self, symbol: str, df: pd.DataFrame) -> Optional[Signal]:
        if len(df) < 20:
            return None

        if self._pipeline is None:
            try:
                self._load()
            except Exception as e:
                logger.error("Chronos 로딩 실패 (chronos-forecasting 설치 필요): %s", e)
                return None

        # 가용 데이터 전부 사용, 최대 _MAX_CONTEXT(512)로 제한
        context_len = min(len(df), _MAX_CONTEXT)
        close = df["close"].values[-context_len:].astype(float)
        current_price = close[-1]

        try:
            context  = torch.tensor(close, dtype=torch.float32).unsqueeze(0)
            forecast = self._pipeline.predict(
                context,
                prediction_length=_HORIZON,
                num_samples=_SAMPLES,
            )
            # forecast shape: (1, num_samples, horizon) → squeeze batch dim
            samples = forecast[0].numpy()  # (num_samples, horizon)
        except Exception as e:
            logger.warning("Chronos 추론 실패 (%s): %s", symbol, e)
            return None

        # 마지막 예측 스텝의 분포
        last_step  = samples[:, -1]                     # (num_samples,)
        median_val = float(np.median(last_step))
        p10        = float(np.percentile(last_step, 10))
        p90        = float(np.percentile(last_step, 90))

        pct_change       = (median_val - current_price) / current_price
        confidence_range = (p90 - p10) / current_price  # 불확실도 (좁을수록 확실)

        if confidence_range > _MAX_UNCERTAINTY:
            logger.debug(
                "Chronos 불확실도 초과 차단 (%s): %.3f%% > %.3f%%",
                symbol, confidence_range * 100, _MAX_UNCERTAINTY * 100,
            )
            return None

        row = df.iloc[-1]
        atr = float(row.get("atr_14", 0))

        reason = (
            f"현재가={current_price:.4f}  예측={median_val:.4f}\n"
            f"예측변화={pct_change:.3%}  불확실도={confidence_range:.3%}\n"
            f"모델={_MODEL_ID.split('/')[-1]}  ctx={context_len}봉  horizon={_HORIZON}봉"
        )

        if pct_change >= _THRESHOLD:
            return Signal(
                symbol=symbol,
                direction="LONG",
                strategy=self.name,
                reason=reason,
                atr=atr,
                tp_mult=self.tp_mult,
                sl_mult=self.sl_mult,
            )

        if pct_change <= -_THRESHOLD:
            return Signal(
                symbol=symbol,
                direction="SHORT",
                strategy=self.name,
                reason=reason,
                atr=atr,
                tp_mult=self.tp_mult,
                sl_mult=self.sl_mult,
            )

        return None
