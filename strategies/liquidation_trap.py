from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field

from .base import Signal

logger = logging.getLogger(__name__)

# 기본값
_BOOK_RATIO      = 0.3     # 누적 청산 / 호가 depth 비율 임계값
_BOOK_LEVELS     = 20      # 호가 몇 레벨 합산할지
_MIN_DEPTH_USDT  = 50_000  # depth 하한 — 이보다 얇으면 비율 무시 (허수/유동성 회수 방어)
_WINDOW_SEC      = 30      # 청산 누적 롤링 윈도우 (초)
_COOLDOWN_SEC    = 300     # 심볼+방향 재신호 쿨다운 (초)
_TP_MULT         = 2.0
_SL_MULT         = 1.5


@dataclass
class _LiqEvent:
    usdt: float
    ts: float


@dataclass
class _Accumulator:
    events: list[_LiqEvent] = field(default_factory=list)

    def add(self, usdt: float) -> None:
        self.events.append(_LiqEvent(usdt=usdt, ts=time.time()))

    def total(self, window_sec: float) -> float:
        cutoff = time.time() - window_sec
        self.events = [e for e in self.events if e.ts >= cutoff]
        return sum(e.usdt for e in self.events)

    def clear(self) -> None:
        self.events.clear()


class LiquidationTrap:
    """
    대규모 청산 감지 → 반대 방향(평균회귀) 신호 생성.

    Binance forceOrder 이벤트:
      S="SELL" → long 포지션 청산 → 가격 급락 → LONG 반전 신호
      S="BUY"  → short 포지션 청산 → 가격 급등 → SHORT 반전 신호

    임계값: 고정 USDT 대신 호가창 depth 대비 비율 사용.
      - SELL 청산(long liq) → bid side depth 대비
      - BUY  청산(short liq) → ask side depth 대비
      예) book_ratio=0.3: 누적 청산액이 해당 호가 depth의 30% 이상이면 신호

    파라미터:
      book_ratio  : 누적청산 / 호가depth 임계 비율 (기본 0.3)
      book_levels : 호가 레벨 수 (기본 20)
      window_sec  : 청산 누적 롤링 윈도우 (기본 30초)
      cooldown_sec: 심볼+방향 재신호 쿨다운 (기본 5분)
      autolist    : 지정 시 해당 심볼만 처리 (None이면 전체)
    """

    name    = "LiquidationTrap"
    tp_mult = _TP_MULT
    sl_mult = _SL_MULT

    def __init__(
        self,
        executor,
        trader,            # BinanceFuturesTrader (depth 조회용)
        store,
        messenger,
        chat_id: str,
        book_ratio: float = _BOOK_RATIO,
        book_levels: int = _BOOK_LEVELS,
        min_depth_usdt: float = _MIN_DEPTH_USDT,
        window_sec: float = _WINDOW_SEC,
        cooldown_sec: float = _COOLDOWN_SEC,
        autolist=None,
        state=None,
    ):
        self.executor    = executor
        self.trader      = trader
        self.store       = store
        self.messenger   = messenger
        self.chat_id     = chat_id
        self.book_ratio     = book_ratio
        self.book_levels    = book_levels
        self.min_depth_usdt = min_depth_usdt
        self.window_sec     = window_sec
        self.cooldown_sec = cooldown_sec
        self.autolist    = autolist
        self.state       = state

        self._acc: dict[tuple, _Accumulator] = defaultdict(_Accumulator)
        self._last_signal: dict[tuple, float] = {}

    # ── public ───────────────────────────────────────────────────────────────

    async def on_liquidation(self, msg: dict) -> None:
        if self.state and self.state.trading_paused:
            return

        o = msg.get("o", {})
        symbol     = o.get("s", "")
        side       = o.get("S", "")
        avg_price  = float(o.get("ap", 0) or 0)
        filled_qty = float(o.get("z", 0) or 0)

        if not symbol or avg_price <= 0 or filled_qty <= 0:
            return

        if self.autolist and symbol not in self.autolist:
            return

        usdt = avg_price * filled_qty
        # SELL=long 청산 → LONG 반전, BUY=short 청산 → SHORT 반전
        direction = "LONG" if side == "SELL" else "SHORT"
        key = (symbol, direction)

        self._acc[key].add(usdt)
        total = self._acc[key].total(self.window_sec)

        # 쿨다운 체크 (depth 조회 전에 먼저 걸러냄)
        now = time.time()
        if now - self._last_signal.get(key, 0) < self.cooldown_sec:
            return

        # 호가 depth 조회 후 비율 체크
        depth_usdt = await self._fetch_depth_usdt(symbol, side)
        if depth_usdt < self.min_depth_usdt:
            # 호가가 너무 얇음 — 유동성 회수 또는 잡코인 허수 가능성
            logger.debug(
                "depth too thin, skip %s %s  depth=%.0f < min=%.0f",
                symbol, direction, depth_usdt, self.min_depth_usdt,
            )
            return

        ratio = total / depth_usdt
        if ratio < self.book_ratio:
            return

        self._last_signal[key] = now
        self._acc[key].clear()

        await self._emit(symbol, direction, total, depth_usdt, ratio)

    # ── 호가 depth 조회 ──────────────────────────────────────────────────────

    async def _fetch_depth_usdt(self, symbol: str, liq_side: str) -> float:
        """
        liq_side="SELL"(long liq) → bid 잠식 → bid depth 조회
        liq_side="BUY"(short liq) → ask 잠식 → ask depth 조회
        """
        try:
            book = await asyncio.to_thread(
                self.trader.client.depth, symbol=symbol, limit=self.book_levels
            )
            levels = book["bids"] if liq_side == "SELL" else book["asks"]
            return sum(float(p) * float(q) for p, q in levels)
        except Exception as e:
            logger.warning("depth fetch failed for %s: %s", symbol, e)
            return 0.0

    # ── signal emit ──────────────────────────────────────────────────────────

    async def _emit(
        self, symbol: str, direction: str,
        liq_usdt: float, depth_usdt: float, ratio: float
    ) -> None:
        atr = 0.0
        df = self.store.get(symbol)
        if df is not None and len(df) > 0:
            atr = float(df.iloc[-1].get("atr_14", 0.0))

        signal = Signal(
            symbol    = symbol,
            direction = direction,
            strategy  = self.name,
            reason    = (
                f"[LIQUIDATION] {symbol} {'long' if direction == 'LONG' else 'short'} 대규모 청산\n"
                f"청산규모: ${liq_usdt:,.0f}  호가depth: ${depth_usdt:,.0f}  비율: {ratio:.1%}\n"
                f"반전 방향: {direction}"
            ),
            atr     = atr,
            tp_mult = self.tp_mult,
            sl_mult = self.sl_mult,
        )

        auto_usdt = getattr(self.executor, "auto_usdt", None)

        if auto_usdt:
            self.executor.add_pending(signal)
            result = await self.executor.on_confirm("full", usdt_override=auto_usdt)
            msg = (
                f"🤖 [{self.name}] {symbol} {direction} 자동 진입\n"
                f"{signal.reason}\n─\n{result}"
            )
        else:
            signal_id = self.executor.add_pending(signal)
            id_tag = f" [{signal_id}]" if signal_id else ""
            msg = (
                f"🔴 [{self.name}] {symbol} {direction} 신호{id_tag}\n"
                f"{signal.reason}\n─\n"
                f"'positive{id_tag}' → TP×{self.tp_mult} + SL×{self.sl_mult}\n"
                f"'swing{id_tag}' → SL만 + 추세 반전 알림\n"
                f"(2분 이내 답장)"
            )

        try:
            await self.messenger.post_message(self.chat_id, msg)
        except Exception as e:
            logger.warning("LiquidationTrap notify failed: %s", e)
