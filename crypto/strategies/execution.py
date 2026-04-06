from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from crypto.orders.parser import OrderIntent
from strategies.base import Signal

_SNAPSHOT_DIR = Path("marketSnapshots")


def _save_snapshot(signal: Signal, store, timeframe: str) -> None:
    """실제 진입 시점의 market data snapshot을 CSV로 저장."""
    try:
        from crypto.market_data.ohlcv_store import _compute as _compute_indicators

        df_1m = store.get(signal.symbol)
        if df_1m is None or len(df_1m) < 2:
            return

        if timeframe != "1min":
            base_df = df_1m[["open", "high", "low", "close", "volume"]].resample(timeframe).agg(
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                volume=("volume", "sum"),
            ).dropna()
            df_s = _compute_indicators(base_df)
        else:
            df_s = df_1m

        _SNAPSHOT_DIR.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        base = f"{ts}_{signal.symbol}_{signal.strategy}_{signal.direction}"

        # 전략 timeframe 데이터 (파일명에 timeframe 명시)
        df_s.tail(100).to_csv(_SNAPSHOT_DIR / f"{base}_{timeframe}.csv", encoding="utf-8-sig")

        # 1분봉 원본은 전략이 1min이 아닐 때만 추가 저장
        if timeframe != "1min":
            df_1m.tail(100).to_csv(_SNAPSHOT_DIR / f"{base}_1min.csv", encoding="utf-8-sig")

        row = df_s.iloc[-1]
        meta = {
            "timestamp":  ts,
            "symbol":     signal.symbol,
            "strategy":   signal.strategy,
            "direction":  signal.direction,
            "timeframe":  timeframe,
            "reason":     signal.reason,
            "atr":        signal.atr,
            "tp_mult":    signal.tp_mult,
            "sl_mult":    signal.sl_mult,
            "close":      row.get("close"),
            "rsi_14":     row.get("rsi_14"),
            "adx_14":     row.get("adx_14"),
            "ema_5":      row.get("ema_5"),
            "ema_20":     row.get("ema_20"),
            "vol_ratio":  row.get("vol_ratio"),
            "bb_upper":   row.get("bb_upper"),
            "bb_lower":   row.get("bb_lower"),
            "zscore_20":  row.get("zscore_20"),
        }
        pd.Series(meta).to_csv(_SNAPSHOT_DIR / f"{base}_meta.csv", header=False, encoding="utf-8-sig")
    except Exception as e:
        logging.getLogger(__name__).warning("Snapshot 저장 실패: %s", e)

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
    timeframe: str = "1min"
    signal_id: str = ""


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
        trade_logger=None,    # TradeLogger (optional)
    ):
        self.order_service = order_service
        self.trader = trader
        self.store = store
        self.messenger = messenger
        self.chat_id = chat_id
        self.auto_usdt = auto_usdt
        self.trade_logger = trade_logger

        self._pending: dict[str, PendingSignal] = {}   # symbol → PendingSignal
        self._swings: list[SwingMonitor] = []
        self._id_counter: int = 0

    def get_open_usdt(self, symbol: str, direction: str) -> float:
        """열린 포지션의 총 USDT 규모 반환 (trade_logger 기준, add 여부 판단용)."""
        if not self.trade_logger:
            return 0.0
        return sum(
            r.usdt_size
            for r in self.trade_logger._records
            if r.symbol == symbol and r.direction == direction and r.status == "OPEN"
        )

    async def get_conflicting_position(self, symbol: str, signal_direction: str) -> str | None:
        """
        해당 심볼에 시그널 반대 방향 포지션이 있으면 포지션 방향 반환, 없으면 None.
        """
        try:
            import asyncio
            pos_list = await asyncio.to_thread(self.trader.client.get_position_risk)
            for p in pos_list:
                if p.get("symbol") != symbol:
                    continue
                amt = float(p.get("positionAmt", 0))
                if abs(amt) < 1e-12:
                    continue
                pos_direction = "LONG" if amt > 0 else "SHORT"
                if pos_direction != signal_direction:
                    return pos_direction
        except Exception:
            pass
        return None

    # ── 시그널 등록 (StrategyRunner가 호출) ──────────────────────────────────

    def add_pending(self, signal: Signal, timeframe: str = "1min") -> str:
        """시그널을 대기열에 등록하고 signal_id를 반환."""
        df = self.store.get(signal.symbol)
        if df is None or len(df) < 1:
            return ""
        row = df.iloc[-1]
        atr = signal.atr if signal.atr > 0 else float(row["atr_14"])
        self._id_counter = (self._id_counter % 26) + 1
        signal_id = chr(ord("a") + self._id_counter - 1)  # a, b, c, ...
        self._pending[signal.symbol] = PendingSignal(
            signal=signal,
            atr=atr,
            close=float(row["close"]),
            expires_at=time.time() + CONFIRM_WINDOW,
            timeframe=timeframe,
            signal_id=signal_id,
        )
        logger.debug("Pending signal added: [%s] %s %s (ATR=%.4f)", signal_id, signal.symbol, signal.direction, atr)
        return signal_id

    # ── 사용자 확인 처리 ──────────────────────────────────────────────────────

    async def on_confirm(self, mode: str, usdt_override: float | None = None, reverse: bool = False, signal_id: str | None = None) -> str:
        """
        mode: 'full'  → TP + SL
              'swing' → SL만 + 추세 반전 모니터링
        reverse: True → 시그널 반대 방향 진입, TP↔SL 교체
        signal_id: 특정 시그널 지정 (None이면 단일 대기 시 자동 선택)
        """
        now = time.time()
        valid = {sym: p for sym, p in self._pending.items() if p.expires_at > now}
        self._pending = valid

        if not valid:
            return "❌ 유효한 대기 시그널 없음 (2분 초과)"

        if signal_id:
            # ID로 특정 시그널 선택
            matched = {sym: p for sym, p in valid.items() if p.signal_id == signal_id.lower()}
            if not matched:
                lines = [f"  [{p.signal_id}] {sym} {p.signal.direction} ({p.signal.strategy})" for sym, p in valid.items()]
                return f"❌ 시그널 ID '{signal_id}' 없음. 대기 중:\n" + "\n".join(lines)
            sym, pending = next(iter(matched.items()))
        elif len(valid) == 1:
            sym, pending = next(iter(valid.items()))
        else:
            lines = [f"  [{p.signal_id}] {sym} {p.signal.direction} ({p.signal.strategy})" for sym, p in valid.items()]
            return "⚠️ 대기 중인 시그널이 여러 개입니다. ID를 지정하세요:\n" + "\n".join(lines)

        del self._pending[sym]

        signal = pending.signal
        direction = ("SHORT" if signal.direction == "LONG" else "LONG") if reverse else signal.direction
        side = "BUY" if direction == "LONG" else "SELL"
        close_side = "SELL" if direction == "LONG" else "BUY"

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

        # ── 진입 확정 시점에 snapshot 저장 ──────────────────────────────────
        _save_snapshot(signal, self.store, pending.timeframe)

        if direction == "LONG":
            tp_price = _round_price(avg_price + tp_mult * atr)
            sl_price = _round_price(avg_price - sl_mult * atr)
        else:
            tp_price = _round_price(avg_price - tp_mult * atr)
            sl_price = _round_price(avg_price + sl_mult * atr)

        # ── 체결 수량 확보 (SL/TP quantity로 사용) ──────────────────────────
        qty = float(order_resp.get("executedQty") or 0)

        # ── 진입 기록 ────────────────────────────────────────────────────────
        if self.trade_logger:
            self.trade_logger.on_entry(
                signal    = signal,
                avg_price = avg_price,
                quantity  = qty,
                usdt_size = usdt,
                tp_price  = tp_price if mode == "full" else None,
                sl_price  = sl_price,
                mode      = mode,
            )

        # ── SL 주문 (공통) ───────────────────────────────────────────────────
        sl_id = "?"
        try:
            sl_resp = await self.trader.new_stop_loss_order(sym, close_side, sl_price, quantity=qty or None)
            sl_id = sl_resp.get("algoId") or sl_resp.get("orderId", "?")
        except Exception as e:
            return (
                f"⚠️ 진입 완료, SL 실패 — 수동 설정 필요\n"
                f"{sym} {direction}  entry≈{avg_price:.2f}  ATR={atr:.2f}\n"
                f"권장 SL: {sl_price}  오류: {e}"
            )

        # ── full: TP까지 ─────────────────────────────────────────────────────
        reverse_tag = " [REVERSE]" if reverse else ""
        if mode == "full":
            tp_id = "?"
            try:
                tp_resp = await self.trader.new_take_profit_order(sym, close_side, tp_price, quantity=qty or None)
                tp_id = tp_resp.get("algoId") or tp_resp.get("orderId", "?")
            except Exception as e:
                return (
                    f"⚠️ 진입+SL 완료, TP 실패 — 수동 설정 필요\n"
                    f"{sym} {direction}  entry≈{avg_price:.2f}\n"
                    f"SL={sl_price}(id={sl_id})  권장 TP: {tp_price}  오류: {e}"
                )
            return (
                f"✅ {direction} 진입{reverse_tag} [{signal.strategy}]\n"
                f"{sym}  entry≈{avg_price:.2f}  ATR={atr:.2f}\n"
                f"TP={tp_price} (id={tp_id})\n"
                f"SL={sl_price} (id={sl_id})\n"
                f"R:R = {tp_mult}:{sl_mult}"
            )

        # ── swing: SL만, 추세 반전 모니터링 등록 ────────────────────────────
        self._swings.append(SwingMonitor(
            symbol=sym,
            direction=direction,
            entry=avg_price,
            sl_algo_id=sl_id,
        ))
        return (
            f"✅ {direction} 스윙 진입{reverse_tag} [{signal.strategy}]\n"
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
