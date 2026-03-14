from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from crypto.orders.parser import OrderIntent
from .base import Signal

logger = logging.getLogger(__name__)

CONFIRM_WINDOW = 120   # 초: 시그널 후 사용자 확인 대기 시간


def _round_price(price: float) -> float:
    """가격 크기에 맞게 소수점 자리 조정."""
    if price >= 1000:
        return round(price, 2)
    elif price >= 10:
        return round(price, 3)
    elif price >= 1:
        return round(price, 4)
    return round(price, 6)


@dataclass
class PendingSignal:
    signal: Signal
    atr: float
    close: float         # 시그널 시점 close (entry 추정용 fallback)
    expires_at: float


@dataclass
class SwingMonitor:
    symbol: str
    direction: str       # "LONG" or "SHORT"
    entry: float
    sl_algo_id: Any


class SignalExecutor:
    """
    시그널 대기 → 사용자 확인 → 자동 주문 실행.

    ┌─ 'positive'       → 시장가 진입 + ATR TP + ATR SL (Binance 알고 주문)
    └─ 'swing' → 시장가 진입 + ATR SL만 + 추세 반전 시 Telegram 알림
    """

    def __init__(
        self,
        order_service,        # OrderService (진입용)
        trader,               # BinanceFuturesTrader (TP/SL 주문용)
        store,                # OhlcvStore
        messenger,
        chat_id: str,
        auto_usdt: float = 50.0,
    ):
        self.order_service = order_service
        self.trader = trader
        self.store = store
        self.messenger = messenger
        self.chat_id = chat_id
        self.auto_usdt = auto_usdt

        self._pending: dict[str, PendingSignal] = {}   # symbol → PendingSignal
        self._swings: list[SwingMonitor] = []

    # ── 시그널 등록 (StrategyRunner가 호출) ──────────────────────────────────

    def add_pending(self, signal: Signal) -> None:
        df = self.store.get(signal.symbol)
        if df is None or len(df) < 1:
            return
        row = df.iloc[-1]
        # signal.atr: detect() 시점의 해당 timeframe ATR (5분봉 전략은 5분봉 ATR)
        # 0이면 fallback으로 1분봉 store ATR 사용
        atr = signal.atr if signal.atr > 0 else float(row["atr_14"])
        self._pending[signal.symbol] = PendingSignal(
            signal=signal,
            atr=atr,
            close=float(row["close"]),
            expires_at=time.time() + CONFIRM_WINDOW,
        )
        logger.debug("Pending signal added: %s %s (ATR=%.4f)", signal.symbol, signal.direction, atr)

    # ── 사용자 확인 처리 ──────────────────────────────────────────────────────

    async def on_confirm(self, mode: str, usdt_override: float | None = None) -> str:
        """
        mode: 'full'  → TP + SL
              'swing' → SL만 + 추세 반전 모니터링
        """
        now = time.time()
        valid = {sym: p for sym, p in self._pending.items() if p.expires_at > now}
        self._pending = valid

        if not valid:
            return "❌ 유효한 대기 시그널 없음 (2분 초과)"

        # 가장 최근 시그널 선택
        sym, pending = max(valid.items(), key=lambda x: x[1].expires_at)
        del self._pending[sym]

        signal = pending.signal
        side = "BUY" if signal.direction == "LONG" else "SELL"
        close_side = "SELL" if signal.direction == "LONG" else "BUY"

        # ── 시장가 진입 ──────────────────────────────────────────────────────
        usdt = usdt_override if usdt_override is not None else self.auto_usdt
        intent = OrderIntent(side=side, symbol=sym, usdt_amount=usdt)
        try:
            order_resp = await self.order_service.place(intent)
        except Exception as e:
            return f"❌ 진입 주문 실패: {e}"

        avg_price = float(order_resp.get("avgPrice") or 0) or pending.close
        atr = pending.atr
        tp_mult = signal.tp_mult
        sl_mult = signal.sl_mult

        if signal.direction == "LONG":
            tp_price = _round_price(avg_price + tp_mult * atr)
            sl_price = _round_price(avg_price - sl_mult * atr)
        else:
            tp_price = _round_price(avg_price - tp_mult * atr)
            sl_price = _round_price(avg_price + sl_mult * atr)

        # ── SL 주문 (공통) ───────────────────────────────────────────────────
        sl_id = "?"
        try:
            sl_resp = await self.trader.new_stop_loss_order(sym, close_side, sl_price)
            sl_id = sl_resp.get("algoId") or sl_resp.get("orderId", "?")
        except Exception as e:
            return (
                f"⚠️ 진입 완료, SL 실패 — 수동 설정 필요\n"
                f"{sym} {signal.direction}  entry≈{avg_price:.2f}  ATR={atr:.2f}\n"
                f"권장 SL: {sl_price}  오류: {e}"
            )

        # ── full: TP까지 ─────────────────────────────────────────────────────
        if mode == "full":
            tp_id = "?"
            try:
                tp_resp = await self.trader.new_take_profit_order(sym, close_side, tp_price)
                tp_id = tp_resp.get("algoId") or tp_resp.get("orderId", "?")
            except Exception as e:
                return (
                    f"⚠️ 진입+SL 완료, TP 실패 — 수동 설정 필요\n"
                    f"{sym} {signal.direction}  entry≈{avg_price:.2f}\n"
                    f"SL={sl_price}(id={sl_id})  권장 TP: {tp_price}  오류: {e}"
                )
            return (
                f"✅ {signal.direction} 진입 [{signal.strategy}]\n"
                f"{sym}  entry≈{avg_price:.2f}  ATR={atr:.2f}\n"
                f"TP={tp_price} (id={tp_id})\n"
                f"SL={sl_price} (id={sl_id})\n"
                f"R:R = {tp_mult}:{sl_mult}"
            )

        # ── swing: SL만, 추세 반전 모니터링 등록 ────────────────────────────
        self._swings.append(SwingMonitor(
            symbol=sym,
            direction=signal.direction,
            entry=avg_price,
            sl_algo_id=sl_id,
        ))
        return (
            f"✅ {signal.direction} 스윙 진입 [{signal.strategy}]\n"
            f"{sym}  entry≈{avg_price:.2f}  ATR={atr:.2f}\n"
            f"SL={sl_price} (id={sl_id})\n"
            f"추세 반전 시 알림 (EMA 이탈 기준)"
        )

    # ── 스윙 추세 반전 체크 (StrategyRunner._tick 에서 호출) ──────────────────

    async def check_swing_exits(self) -> None:
        if not self._swings:
            return

        remaining = []
        for sw in self._swings:
            df = self.store.get(sw.symbol)
            if df is None or len(df) < 2:
                remaining.append(sw)
                continue

            row = df.iloc[-1]
            if sw.direction == "LONG":
                reversal = (
                    row["ema_5"] < row["ema_20"]
                    or row["close"] < row["ema_20"]
                )
            else:
                reversal = (
                    row["ema_5"] > row["ema_20"]
                    or row["close"] > row["ema_20"]
                )

            if reversal:
                pnl_pct = (
                    (row["close"] - sw.entry) / sw.entry
                    if sw.direction == "LONG"
                    else (sw.entry - row["close"]) / sw.entry
                )
                try:
                    await self.messenger.post_message(
                        self.chat_id,
                        f"🔔 스윙 추세 반전 [{sw.symbol} {sw.direction}]\n"
                        f"entry={sw.entry:.2f}  현재={row['close']:.2f}"
                        f"  수익≈{pnl_pct:.2%}\n"
                        f"SL 주문(id={sw.sl_algo_id}) 유지 중 — 청산 여부를 결정하세요.",
                    )
                except Exception:
                    pass
                # 알림 발송 후 모니터링 제거 (한 번만 알림)
            else:
                remaining.append(sw)

        self._swings = remaining
