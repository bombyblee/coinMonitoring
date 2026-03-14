from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from .base import Signal

logger = logging.getLogger(__name__)

TAKER_FEE_RATE = 0.0004   # Binance futures taker fee (0.04% per side)


# ── 레코드 ────────────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    record_id:     str
    symbol:        str
    direction:     str             # LONG / SHORT
    strategy:      str
    mode:          str             # full / swing
    entry_time:    datetime
    entry_price:   float
    quantity:      float
    usdt_size:     float
    atr:           float
    tp_price:      Optional[float]
    sl_price:      float
    tp_mult:       float
    sl_mult:       float
    signal_reason: str

    # 청산 후 채워짐
    exit_time:    Optional[datetime] = None
    exit_price:   Optional[float]   = None
    close_reason: Optional[str]     = None   # TP / SL
    gross_pnl:    Optional[float]   = None
    fee:          Optional[float]   = None
    net_pnl:      Optional[float]   = None


# ── TradeLogger ───────────────────────────────────────────────────────────────

class TradeLogger:
    """
    전략 진입~청산 전 과정 추적.

    흐름
    ────
    execution.on_confirm()  →  on_entry()         # 진입 직후
    fill_notifier           →  notify_close_if_match()  # TP/SL 체결 시
    매시간 + 종료 시         →  save_csv()
    """

    def __init__(
        self,
        messenger,
        chat_id: str,
        results_dir: str = "./tradingResults",
    ):
        self.messenger   = messenger
        self.chat_id     = chat_id
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self._open:   dict[str, TradeRecord] = {}   # symbol → 진행 중 거래
        self._closed: list[TradeRecord]      = []
        self._task:   Optional[asyncio.Task] = None
        self._stop    = asyncio.Event()

    # ── 진입 기록 ─────────────────────────────────────────────────────────────

    def on_entry(
        self,
        signal:    Signal,
        avg_price: float,
        quantity:  float,
        usdt_size: float,
        tp_price:  Optional[float],
        sl_price:  float,
        mode:      str,
    ) -> None:
        record = TradeRecord(
            record_id     = uuid.uuid4().hex[:8],
            symbol        = signal.symbol,
            direction     = signal.direction,
            strategy      = signal.strategy,
            mode          = mode,
            entry_time    = datetime.now(timezone.utc),
            entry_price   = avg_price,
            quantity      = quantity,
            usdt_size     = usdt_size,
            atr           = signal.atr,
            tp_price      = tp_price,
            sl_price      = sl_price,
            tp_mult       = signal.tp_mult,
            sl_mult       = signal.sl_mult,
            signal_reason = signal.reason,
        )
        self._open[signal.symbol] = record
        logger.info(
            "TradeLogger: entry [%s] %s %s @ %.4f qty=%.6f",
            record.record_id, signal.symbol, signal.direction, avg_price, quantity,
        )

    # ── TP/SL 체결 이벤트 처리 ────────────────────────────────────────────────

    async def notify_close_if_match(self, msg: dict) -> None:
        """
        fill_notifier 에서 ORDER_TRADE_UPDATE 이벤트마다 호출.
        open trade 와 매칭되는 TP/SL 체결이면 종료 처리 후 Telegram 알림.
        """
        o = msg.get("o", {})
        if o.get("X") != "FILLED":
            return

        order_type = o.get("o", "")
        if order_type not in ("STOP_MARKET", "TAKE_PROFIT_MARKET"):
            return

        symbol = o.get("s", "")
        record = self._open.pop(symbol, None)
        if record is None:
            return

        exit_price  = float(o.get("ap") or o.get("L") or 0)
        exit_ts     = int(o.get("T", 0))
        exit_time   = (
            datetime.fromtimestamp(exit_ts / 1000, tz=timezone.utc)
            if exit_ts else datetime.now(timezone.utc)
        )
        gross_pnl   = float(o.get("rp", 0))
        exit_fee    = abs(float(o.get("n", 0)))
        entry_fee   = record.entry_price * record.quantity * TAKER_FEE_RATE
        fee         = round(entry_fee + exit_fee, 6)
        net_pnl     = round(gross_pnl - fee, 4)
        close_reason = "TP" if order_type == "TAKE_PROFIT_MARKET" else "SL"

        record.exit_time    = exit_time
        record.exit_price   = exit_price
        record.close_reason = close_reason
        record.gross_pnl    = round(gross_pnl, 4)
        record.fee          = fee
        record.net_pnl      = net_pnl

        self._closed.append(record)
        logger.info(
            "TradeLogger: closed [%s] %s %s via %s  net=%.4f USDT",
            record.record_id, symbol, record.direction, close_reason, net_pnl,
        )
        await self._notify_close(record)

    # ── Telegram 알림 ─────────────────────────────────────────────────────────

    async def _notify_close(self, r: TradeRecord) -> None:
        result_emoji = "✅" if (r.net_pnl or 0) >= 0 else "❌"
        hold_secs    = (r.exit_time - r.entry_time).total_seconds()
        hold_str     = f"{int(hold_secs // 60)}분 {int(hold_secs % 60)}초"
        pnl_pct      = (r.net_pnl / r.usdt_size * 100) if r.usdt_size else 0.0

        msg = (
            f"{result_emoji} [{r.strategy}] {r.symbol} {r.direction} 종료\n"
            f"청산: {r.close_reason}  보유: {hold_str}\n"
            f"─\n"
            f"진입: {r.entry_price:.4f}  →  청산: {r.exit_price:.4f}\n"
            f"ATR={r.atr:.4f}  TP×{r.tp_mult} / SL×{r.sl_mult}\n"
            f"─\n"
            f"총손익: {r.gross_pnl:+.4f} USDT\n"
            f"수수료: -{r.fee:.4f} USDT\n"
            f"순손익: {r.net_pnl:+.4f} USDT  ({pnl_pct:+.2f}%)\n"
            f"─\n"
            f"[진입 근거]\n{r.signal_reason}"
        )
        try:
            await self.messenger.post_message(self.chat_id, msg)
        except Exception as e:
            logger.warning("TradeLogger: notify_close failed: %s", e)

    # ── CSV 저장 ──────────────────────────────────────────────────────────────

    def save_csv(self) -> None:
        if not self._closed:
            return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path  = self.results_dir / f"trades_{today}.csv"
        df    = pd.DataFrame([_to_row(r) for r in self._closed])
        df.to_csv(path, index=False)
        logger.info("TradeLogger: %d records → %s", len(self._closed), path)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._hourly_loop(), name="trade_logger")

    async def stop(self) -> None:
        self._stop.set()
        self.save_csv()
        if self._task:
            self._task.cancel()
            await asyncio.sleep(0)

    async def _hourly_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=3600)
            except asyncio.TimeoutError:
                self.save_csv()


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _to_row(r: TradeRecord) -> dict:
    return {
        "record_id":    r.record_id,
        "symbol":       r.symbol,
        "direction":    r.direction,
        "strategy":     r.strategy,
        "mode":         r.mode,
        "entry_time":   r.entry_time.isoformat() if r.entry_time else "",
        "entry_price":  r.entry_price,
        "quantity":     r.quantity,
        "usdt_size":    r.usdt_size,
        "atr":          r.atr,
        "tp_price":     r.tp_price if r.tp_price is not None else "",
        "sl_price":     r.sl_price,
        "tp_mult":      r.tp_mult,
        "sl_mult":      r.sl_mult,
        "exit_time":    r.exit_time.isoformat() if r.exit_time else "",
        "exit_price":   r.exit_price if r.exit_price is not None else "",
        "close_reason": r.close_reason or "",
        "gross_pnl":    r.gross_pnl if r.gross_pnl is not None else "",
        "fee":          r.fee if r.fee is not None else "",
        "net_pnl":      r.net_pnl if r.net_pnl is not None else "",
        "signal_reason": r.signal_reason.replace("\n", " | "),
    }
