# text_router.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from telegram import Update
from telegram.ext import ContextTypes

HandlerFn = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]

@dataclass
class RouterDeps:
    freq_handler: Optional[HandlerFn] = None
    trade_handler: Optional[HandlerFn] = None
    sl_tp_handler: Optional[HandlerFn] = None
    watchlist_handler: Optional[HandlerFn] = None
    signal_handler: Optional[HandlerFn] = None
    strategy_handler: Optional[HandlerFn] = None
    drawdown_handler: Optional[HandlerFn] = None
    fallback_handler: Optional[HandlerFn] = None


def make_text_router(**kwargs) -> HandlerFn:
    """
    main.py에서 미리 만들어둔 핸들러들을 kwargs로 주입.
    순서 상관 없음.
    없는 건 None으로 두고, 해당 명령은 비활성화하거나 fallback으로 처리.
    """
    deps = RouterDeps(
        freq_handler=kwargs.get("freq_handler"),
        trade_handler=kwargs.get("trade_handler"),
        sl_tp_handler=kwargs.get("sl_tp_handler"),
        watchlist_handler=kwargs.get("watchlist_handler"),
        signal_handler=kwargs.get("signal_handler"),
        strategy_handler=kwargs.get("strategy_handler"),
        drawdown_handler=kwargs.get("drawdown_handler"),
        fallback_handler=kwargs.get("fallback_handler"),
    )

    async def _default_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message:
            await update.message.reply_text(
                "명령을 못 알아먹었어요 😅\n"
                "예) freq 60 / buy BTCUSDT 0.01 / sell ETHUSDT 0.02"
            )

    fallback = deps.fallback_handler or _default_fallback

    async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        text = (update.message.text or "").strip()
        if not text:
            return

        lowered = text.lower()

        # freq
        if lowered.startswith("freq"):
            if deps.freq_handler is None:
                await update.message.reply_text("freq 기능이 아직 초기화되지 않았어요. (freq_handler=None)")
                return
            await deps.freq_handler(update, context)
            return

        # trade
        if lowered.startswith(("buy", "sell")):
            if deps.trade_handler is None:
                await update.message.reply_text("주문 기능이 아직 초기화되지 않았어요. (trade_handler=None)")
                return
            await deps.trade_handler(update, context)
            return

        # watchlist
        if lowered.startswith("watchlist"):
            if deps.watchlist_handler is None:
                await update.message.reply_text("워치리스트 기능이 초기화되지 않았어요.")
                return
            await deps.watchlist_handler(update, context)
            return

        # strategy 관리
        if lowered.startswith("strategy"):
            if deps.strategy_handler is not None:
                await deps.strategy_handler(update, context)
            return

        # drawdown 가드 온/오프
        if lowered.startswith("drawdown"):
            if deps.drawdown_handler is not None:
                await deps.drawdown_handler(update, context)
            return

        # signal confirm: "positive [amount]" / "swing [amount]" / "reverse [amount]"
        if lowered.startswith("positive") or lowered.startswith("swing") or lowered.startswith("reverse"):
            if deps.signal_handler is not None:
                await deps.signal_handler(update, context)
            return

        # sl/tp: "sltp ..." 또는 "<숫자> tp|sl ..."
        import re as _re
        if lowered.startswith("sltp") or _re.match(r"^\d+\s+(tp|sl)\s+", lowered):
            if deps.sl_tp_handler is None:
                await update.message.reply_text("SL/TP 기능이 아직 초기화되지 않았어요. (sl_tp_handler=None)")
                return
            await deps.sl_tp_handler(update, context)
            return

        await fallback(update, context)

    return text_router