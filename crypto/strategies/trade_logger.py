from __future__ import annotations

import asyncio
import csv
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .base import Signal

logger = logging.getLogger(__name__)

TAKER_FEE_RATE = 0.0004   # Binance futures taker fee (0.04% per side)
POLL_INTERVAL  = 60        # 청산 감지 폴링 주기 (초)


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
    status:        str = "OPEN"    # OPEN / CLOSED

    # 청산 후 채워짐
    exit_time:    Optional[datetime] = None
    exit_price:   Optional[float]   = None
    close_reason: Optional[str]     = None   # TP / SL / UNKNOWN
    gross_pnl:    Optional[float]   = None
    fee:          Optional[float]   = None
    net_pnl:      Optional[float]   = None


# ── TradeLogger ───────────────────────────────────────────────────────────────

class TradeLogger:
    """
    전략 진입~청산 전 과정 추적.

    흐름
    ────
    execution.on_confirm()  →  on_entry()         # 진입 직후 → CSV 즉시 저장
    백그라운드 폴링          →  _check_close()    # Binance userTrades API로 청산 감지
    청산 감지 시             →  Telegram 알림 + CSV 즉시 저장
    """

    def __init__(
        self,
        trader,                          # BinanceFuturesTrader (userTrades 조회용)
        messenger,
        chat_id: str,
        results_dir: str = "./tradingResults",
    ):
        self.trader      = trader
        self.messenger   = messenger
        self.chat_id     = chat_id
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self._records: list[TradeRecord] = []          # 전체 레코드 (open + closed)
        self._open:    dict[str, TradeRecord] = {}     # symbol → 진행 중 거래
        self._task:    Optional[asyncio.Task] = None
        self._stop     = asyncio.Event()

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
            status        = "OPEN",
        )
        self._open[signal.symbol] = record
        self._records.append(record)
        logger.info(
            "TradeLogger: entry [%s] %s %s @ %.4f qty=%.6f",
            record.record_id, signal.symbol, signal.direction, avg_price, quantity,
        )
        self.save_csv()   # 진입 즉시 저장

    # ── 청산 감지 (폴링) ──────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while not self._stop.is_set():
            for symbol in list(self._open.keys()):
                record = self._open.get(symbol)
                if record:
                    await self._check_close(symbol, record)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass

    async def _check_close(self, symbol: str, record: TradeRecord) -> None:
        """
        Binance userTrades API로 진입 이후 청산 체결(realizedPnl != 0)을 감지.
        찾으면 레코드를 닫고 Telegram 알림 + CSV 저장.
        """
        start_ms = int(record.entry_time.timestamp() * 1000) + 500  # 진입 시각 +0.5s
        try:
            trades = await self.trader.get_user_trades(symbol=symbol, start_time=start_ms)
        except Exception as e:
            logger.warning("TradeLogger: userTrades poll failed [%s]: %s", symbol, e)
            return

        if not trades or not isinstance(trades, list):
            return

        # 청산 방향 체결 중 realizedPnl != 0인 것 = 포지션 일부/전체 청산
        close_side = "SELL" if record.direction == "LONG" else "BUY"
        closing = [
            t for t in trades
            if t.get("side") == close_side and abs(float(t.get("realizedPnl", 0))) > 1e-9
        ]
        if not closing:
            return

        # 가장 최근 청산 체결 기준 (여러 번 분할 청산 시 마지막 기준)
        trade = max(closing, key=lambda t: int(t.get("time", 0)))

        exit_price  = float(trade.get("price", 0))
        gross_pnl   = float(trade.get("realizedPnl", 0))
        exit_fee    = abs(float(trade.get("commission", 0)))
        entry_fee   = record.entry_price * record.quantity * TAKER_FEE_RATE
        fee         = round(entry_fee + exit_fee, 6)
        net_pnl     = round(gross_pnl - entry_fee, 4)   # exit_fee는 gross_pnl에 이미 반영됨

        exit_ts     = int(trade.get("time", 0))
        exit_time   = (
            datetime.fromtimestamp(exit_ts / 1000, tz=timezone.utc)
            if exit_ts else datetime.now(timezone.utc)
        )

        # TP vs SL 추정 (진입가 대비 청산가 방향)
        if record.direction == "LONG":
            close_reason = "TP" if exit_price >= record.entry_price else "SL"
        else:
            close_reason = "TP" if exit_price <= record.entry_price else "SL"

        # 레코드 업데이트
        record.exit_time    = exit_time
        record.exit_price   = exit_price
        record.close_reason = close_reason
        record.gross_pnl    = round(gross_pnl, 4)
        record.fee          = fee
        record.net_pnl      = net_pnl
        record.status       = "CLOSED"

        del self._open[symbol]
        logger.info(
            "TradeLogger: closed [%s] %s %s via %s  net=%.4f USDT",
            record.record_id, symbol, record.direction, close_reason, net_pnl,
        )

        self.save_csv()                      # 청산 즉시 저장
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
        """전체 레코드(open + closed)를 단일 CSV에 즉시 덮어씀."""
        if not self._records:
            return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path  = self.results_dir / f"trades_{today}.csv"
        rows  = [_to_row(r) for r in self._records]
        fields = list(rows[0].keys())
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        logger.info("TradeLogger: saved %d records → %s", len(self._records), path)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._poll_loop(), name="trade_logger")

    async def stop(self) -> None:
        self._stop.set()
        self.save_csv()
        if self._task:
            self._task.cancel()
            await asyncio.sleep(0)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _to_row(r: TradeRecord) -> dict:
    return {
        "record_id":    r.record_id,
        "status":       r.status,
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
