from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class DrawdownGuard:
    """
    프로그램 시작 시점의 marginBalance를 기준으로,
    threshold USDT 이상 감소하면 모든 포지션을 강제 청산하고 Telegram 알림.

    - 발동 후에는 재발동하지 않음 (1회성 안전장치)
    - TP/SL 알고 주문은 포지션 청산 시 Binance가 자동 취소
    """

    def __init__(
        self,
        trader,
        messenger,
        chat_id: str,
        threshold_usdt: float = 200.0,
        poll_interval: float = 30.0,
        state=None,               # ReportState (optional, trading_paused 체크용)
    ):
        self.trader         = trader
        self.messenger      = messenger
        self.chat_id        = chat_id
        self.threshold_usdt = threshold_usdt
        self.poll_interval  = poll_interval
        self.state          = state

        self._initial_margin: Optional[float] = None
        self._triggered = False
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    # ── public ───────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """시작 시 초기 마진 스냅샷 후 모니터링 루프 시작."""
        acc = await asyncio.to_thread(self.trader.client.account)
        self._initial_margin = float(acc.get("totalMarginBalance", 0.0))
        logger.info(
            "DrawdownGuard started — initial_margin=%.2f USDT  threshold=%.2f USDT",
            self._initial_margin, self.threshold_usdt,
        )
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="drawdown_guard")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            await asyncio.sleep(0)

    # ── loop ─────────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        while not self._stop.is_set() and not self._triggered:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass

            if self._stop.is_set() or self._triggered:
                break

            await self._check()

    async def _check(self) -> None:
        if self.state and self.state.trading_paused:
            return

        try:
            acc            = await asyncio.to_thread(self.trader.client.account)
            current_margin = float(acc.get("totalMarginBalance", 0.0))
            drawdown       = self._initial_margin - current_margin

            logger.debug(
                "DrawdownGuard check — initial=%.2f  current=%.2f  drawdown=%.2f",
                self._initial_margin, current_margin, drawdown,
            )

            if drawdown >= self.threshold_usdt:
                await self._emergency_close_all(drawdown, current_margin)
        except Exception as e:
            logger.warning("DrawdownGuard check failed: %s", e)

    # ── 긴급 청산 ─────────────────────────────────────────────────────────────

    async def _emergency_close_all(self, drawdown: float, current_margin: float) -> None:
        self._triggered = True
        logger.warning("DrawdownGuard triggered! drawdown=%.2f USDT", drawdown)

        # 포지션 조회
        try:
            positions = await asyncio.to_thread(self.trader.client.get_position_risk)
            live = [
                (p["symbol"], float(p["positionAmt"]))
                for p in positions
                if abs(float(p.get("positionAmt", 0))) > 1e-12
            ]
        except Exception as e:
            live = []
            logger.error("DrawdownGuard: position fetch failed: %s", e)

        # 포지션 청산
        results: list[str] = []
        for symbol, amt in live:
            side = "SELL" if amt > 0 else "BUY"   # LONG→SELL, SHORT→BUY
            qty  = abs(amt)
            try:
                await self.trader.new_close_market_order(symbol, side, qty)
                results.append(f"✅ {symbol} {side} {qty} 청산 완료")
                logger.info("Emergency closed: %s %s qty=%s", symbol, side, qty)
            except Exception as e:
                results.append(f"❌ {symbol} 청산 실패: {e}")
                logger.error("Emergency close failed for %s: %s", symbol, e)

        # Telegram 알림
        lines = [
            "🚨 드로우다운 가드 발동 — 전체 포지션 강제 청산",
            f"시작 마진:  {self._initial_margin:.2f} USDT",
            f"현재 마진:  {current_margin:.2f} USDT",
            f"감소폭:    -{drawdown:.2f} USDT  (기준: -{self.threshold_usdt:.0f} USDT)",
            "─",
        ]
        if not live:
            lines.append("청산할 포지션 없음")
        else:
            lines += results

        try:
            await self.messenger.post_message(self.chat_id, "\n".join(lines))
        except Exception as e:
            logger.error("DrawdownGuard notification failed: %s", e)
