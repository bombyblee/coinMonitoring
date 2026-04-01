from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import pandas as pd

from crypto.market_data import OhlcvStore
from crypto.market_data.ohlcv_store import _compute as _compute_indicators
from .base import BaseStrategy, Signal

logger = logging.getLogger(__name__)

_COOLDOWN_SEC = 300   # 같은 심볼+방향 시그널 재알림 최소 간격 (5분)
_START_OFFSET = 10    # OhlcvJob 업데이트 후 데이터 준비 대기 (초)


def _resample(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """1분봉 df를 지정 timeframe으로 리샘플링하고 지표 재계산."""
    base = df[["open", "high", "low", "close", "volume"]].resample(timeframe).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna()
    return _compute_indicators(base)


class StrategyRunner:
    """
    OhlcvStore를 매 1분마다 읽어 전략 시그널을 체크하고 Telegram으로 알림.

    - 동일 심볼+방향은 cooldown_sec(기본 5분) 동안 중복 알림 없음.
    - OhlcvJob 보다 _START_OFFSET 초 뒤에 실행해 데이터가 갱신된 뒤 체크.
    """

    def __init__(
        self,
        store: OhlcvStore,
        strategies: list[BaseStrategy],
        messenger,
        chat_id: str,
        cooldown_sec: int = _COOLDOWN_SEC,
        executor=None,   # SignalExecutor (optional)
    ):
        self.store = store
        self.strategies = strategies
        self.messenger = messenger
        self.chat_id = chat_id
        self.cooldown_sec = cooldown_sec
        self.executor = executor
        self._last_signal: dict[tuple[str, str], float] = {}
        self._auto: dict[str, float] = {}   # strategy name → auto USDT amount
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    # ── public ───────────────────────────────────────────────────────────────

    def set_auto(self, strategy_name: str, usdt: float) -> bool:
        """전략 자동 진입 활성화. 전략이 없으면 False 반환."""
        if not any(s.name == strategy_name for s in self.strategies):
            return False
        self._auto[strategy_name] = usdt
        return True

    def unset_auto(self, strategy_name: str) -> bool:
        """전략 자동 진입 비활성화. 등록돼 있지 않으면 False 반환."""
        return self._auto.pop(strategy_name, None) is not None

    def add_strategy(self, strategy: BaseStrategy) -> bool:
        """이름이 중복되지 않으면 추가. 성공 여부 반환."""
        if any(s.name == strategy.name for s in self.strategies):
            return False
        self.strategies.append(strategy)
        return True

    def remove_strategy(self, name: str) -> bool:
        """이름으로 전략 제거. 성공 여부 반환."""
        before = len(self.strategies)
        self.strategies = [s for s in self.strategies if s.name != name]
        return len(self.strategies) < before

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="strategy_runner")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            await asyncio.sleep(0)

    # ── loop ─────────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        # OhlcvJob 보다 _START_OFFSET 초 뒤에 첫 실행
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=_START_OFFSET)
        except asyncio.TimeoutError:
            pass

        while not self._stop.is_set():
            await self._tick()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        for symbol in self.store.symbols():
            df = self.store.get(symbol)
            if df is None or len(df) < 20:
                continue
            for strategy in self.strategies:
                try:
                    df_s = _resample(df, strategy.timeframe) if strategy.timeframe != "1min" else df
                    signal = strategy.detect(symbol, df_s)
                    if signal:
                        await self._maybe_notify(signal, strategy.timeframe)
                except Exception as e:
                    logger.warning(
                        "Strategy %s failed for %s: %s", strategy.name, symbol, e
                    )

        # 스윙 포지션 추세 반전 체크
        if self.executor:
            await self.executor.check_swing_exits()

    async def _maybe_notify(self, signal: Signal, timeframe: str = "1min") -> None:
        key = (signal.symbol, signal.direction)
        now = time.time()
        if now - self._last_signal.get(key, 0) < self.cooldown_sec:
            return
        self._last_signal[key] = now

        emoji = "🟢" if signal.direction == "LONG" else "🔴"
        auto_usdt = self._auto.get(signal.strategy)

        if auto_usdt is not None and self.executor:
            # ── 자동 진입 모드 ────────────────────────────────────────────────
            self.executor.add_pending(signal, timeframe=timeframe)
            result = await self.executor.on_confirm("full", usdt_override=auto_usdt)
            msg = (
                f"🤖 [{signal.strategy}] {signal.symbol} {signal.direction} 자동 진입\n"
                f"{signal.reason}\n"
                f"─\n"
                f"{result}"
            )
        else:
            # ── 수동 확인 모드 ────────────────────────────────────────────────
            if self.executor:
                signal_id = self.executor.add_pending(signal, timeframe=timeframe)
                pending_count = len(self.executor._pending)
                id_tag = f" [{signal_id}]" if pending_count > 1 else ""
                confirm_hint = (
                    f"'positive{id_tag}' → TP(x{signal.tp_mult}) + SL(x{signal.sl_mult}) 자동 주문\n"
                    f"'swing{id_tag}' → SL(x{signal.sl_mult})만 + 추세 반전 알림"
                )
            else:
                id_tag = ""
                confirm_hint = (
                    f"'positive' → TP(x{signal.tp_mult}) + SL(x{signal.sl_mult}) 자동 주문\n"
                    f"'swing' → SL(x{signal.sl_mult})만 + 추세 반전 알림"
                )
            msg = (
                f"{emoji} [{signal.strategy}] {signal.symbol} {signal.direction} 시그널\n"
                f"{signal.reason}\n"
                f"─\n"
                f"{confirm_hint}\n"
                f"(2분 이내 답장)"
            )

        try:
            await self.messenger.post_message(self.chat_id, msg)
        except Exception as e:
            logger.warning("Signal notification failed: %s", e)
