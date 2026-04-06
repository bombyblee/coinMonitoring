from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import pandas as pd

from crypto.market_data import OhlcvStore
from crypto.market_data.ohlcv_store import _compute as _compute_indicators
from strategies.base import BaseStrategy, Signal

logger = logging.getLogger(__name__)

_COOLDOWN_SEC          = 300    # 같은 심볼+방향 시그널 재알림 최소 간격 (5분)
_START_OFFSET          = 10     # OhlcvJob 업데이트 후 데이터 준비 대기 (초)
_MOMENTUM_COOLDOWN_SEC = 7200   # MOMENTUM 신호 레벨별 쿨다운 (2시간)
_MAX_ADD_COUNT         = 3      # 심볼+방향별 최대 add 횟수


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

    필터 체계 (신호 발화 전 순서대로 적용):
      1. 기본 쿨다운 (5분, 모든 전략)
      2. MOMENTUM 쿨다운 (2시간) — add 상황에서만 적용, 포지션 청산 시 자동 해제
      3. Add 횟수 제한 (심볼+방향 최대 3회)
      4. MOMENTUM add 엄격 조건 (가격이 레벨+ATR 이상 + zscore 검증)
      5. REVERSION add ADX 조건 (추세 강화 중 add 금지)
      6. 누적 USDT 상한선 (심볼+방향 총 오픈 규모 제한)
    """

    def __init__(
        self,
        store: OhlcvStore,
        strategies: list[BaseStrategy],
        messenger,
        chat_id: str,
        cooldown_sec: int = _COOLDOWN_SEC,
        executor=None,            # SignalExecutor (optional)
        max_symbol_usdt: float = 0.0,  # 0이면 비활성 (심볼+방향별 누적 USDT 상한)
    ):
        self.store = store
        self.strategies = strategies
        self.messenger = messenger
        self.chat_id = chat_id
        self.cooldown_sec = cooldown_sec
        self.executor = executor
        self.max_symbol_usdt = max_symbol_usdt

        self._last_signal: dict[tuple[str, str], float] = {}
        self._auto: dict[str, float] = {}   # strategy name → auto USDT amount
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

        # ── 추가 필터 상태 ────────────────────────────────────────────────────
        # MOMENTUM 쿨다운: (symbol, direction) → 쿨다운 만료 timestamp
        self._momentum_cooldown: dict[tuple[str, str], float] = {}
        # Add 횟수: (symbol, direction) → 현재까지 add된 횟수
        self._add_count: dict[tuple[str, str], int] = {}
        # 첫 진입 ADX: (symbol, direction) → 최초 진입 시 ADX (REVERSION add 비교용)
        self._first_entry_adx: dict[tuple[str, str], float] = {}

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

        # ── 기본 쿨다운 (5분) ────────────────────────────────────────────────
        if now - self._last_signal.get(key, 0) < self.cooldown_sec:
            return

        # ── 현재 포지션 규모 확인 (add 여부 판단) ────────────────────────────
        open_usdt = self.executor.get_open_usdt(signal.symbol, signal.direction) if self.executor else 0.0
        is_add = open_usdt > 0

        # 포지션이 완전히 청산됐으면 누적 상태 초기화
        if not is_add:
            self._momentum_cooldown.pop(key, None)
            self._add_count.pop(key, None)
            self._first_entry_adx.pop(key, None)

        is_momentum = "[MOMENTUM]" in signal.reason

        # ── ① MOMENTUM 쿨다운 (2시간) — add 상황에서만 적용 ─────────────────
        if is_momentum and is_add:
            expires = self._momentum_cooldown.get(key, 0)
            if now < expires:
                logger.debug(
                    "MOMENTUM 쿨다운 중: %s %s (%.0f초 남음)",
                    signal.symbol, signal.direction, expires - now,
                )
                return

        # ── ② Add 횟수 제한 (최대 3회) ──────────────────────────────────────
        if is_add:
            count = self._add_count.get(key, 0)
            if count >= _MAX_ADD_COUNT:
                logger.debug(
                    "Add 횟수 초과 차단: %s %s (%d회 이미 추가됨)",
                    signal.symbol, signal.direction, count,
                )
                return

        # ── ④⑤⑦ Add 신호 엄격 조건 ─────────────────────────────────────────
        if is_add:
            df = self.store.get(signal.symbol)
            if df is not None and len(df) > 0:
                row = df.iloc[-1]
                close  = float(row["close"])
                zscore = float(row.get("zscore_20", 0))

                if is_momentum:
                    # MOMENTUM add: 가격이 레벨에서 ATR×1 이상 멀어진 상태여야 함
                    # (레벨 근처 횡보 중 재발화 방지)
                    if signal.level_price > 0 and signal.atr > 0:
                        if signal.direction == "LONG":
                            required = signal.level_price + signal.atr
                            if close < required:
                                logger.debug(
                                    "MOMENTUM LONG add 거부 (레벨+ATR 미달): close=%.4f < %.4f",
                                    close, required,
                                )
                                return
                        else:  # SHORT
                            required = signal.level_price - signal.atr
                            if close > required:
                                logger.debug(
                                    "MOMENTUM SHORT add 거부 (레벨-ATR 초과): close=%.4f > %.4f",
                                    close, required,
                                )
                                return

                    # ⑦ MOMENTUM add zscore 검증: 가격이 이미 되돌아간 경우 차단
                    if signal.direction == "LONG" and zscore < -1.5:
                        logger.debug(
                            "MOMENTUM LONG add 거부 (zscore 역전): zscore=%.2f < -1.5", zscore
                        )
                        return
                    if signal.direction == "SHORT" and zscore > 1.5:
                        logger.debug(
                            "MOMENTUM SHORT add 거부 (zscore 역전): zscore=%.2f > 1.5", zscore
                        )
                        return

                else:
                    # REVERSION add: ADX가 첫 진입 시점보다 높으면 추세 강화 → 차단
                    if signal.adx > 0 and key in self._first_entry_adx:
                        first_adx = self._first_entry_adx[key]
                        if signal.adx > first_adx:
                            logger.debug(
                                "REVERSION add 거부 (ADX 상승 = 추세 강화): %.1f > %.1f",
                                signal.adx, first_adx,
                            )
                            return

        # ── ⑥ 누적 USDT 상한선 ──────────────────────────────────────────────
        if self.max_symbol_usdt > 0 and open_usdt >= self.max_symbol_usdt:
            logger.debug(
                "USDT 상한 초과 차단: %s %s open=%.0f >= max=%.0f",
                signal.symbol, signal.direction, open_usdt, self.max_symbol_usdt,
            )
            return

        # ── 필터 통과 → 쿨다운·카운터 업데이트 후 알림 발송 ─────────────────
        self._last_signal[key] = now

        if is_momentum:
            self._momentum_cooldown[key] = now + _MOMENTUM_COOLDOWN_SEC

        if not is_add:
            # 첫 진입: ADX 기록, add 카운터 초기화
            if signal.adx > 0:
                self._first_entry_adx[key] = signal.adx
            self._add_count[key] = 0
        else:
            # add: 카운터 증가
            self._add_count[key] = self._add_count.get(key, 0) + 1

        # ── 알림 발송 ─────────────────────────────────────────────────────────
        emoji = "🟢" if signal.direction == "LONG" else "🔴"
        auto_usdt = self._auto.get(signal.strategy)

        if auto_usdt is not None and self.executor:
            # ── 반대 포지션 체크 ──────────────────────────────────────────────
            conflict = await self.executor.get_conflicting_position(signal.symbol, signal.direction)
            if conflict:
                msg = (
                    f"⚠️ [{signal.strategy}] {signal.symbol} {signal.direction} 시그널\n"
                    f"(자동 진입 보류 — {conflict} 포지션 보유 중)\n"
                    f"{signal.reason}\n"
                    f"─\n"
                    f"수동으로 처리하거나 기존 포지션 청산 후 진입하세요."
                )
            else:
                # ── 자동 진입 모드 ────────────────────────────────────────────
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
