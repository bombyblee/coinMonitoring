from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes


def make_signal_handler(executor, messenger):
    """
    'positive [USDT]' → ATR TP+SL 자동 주문 (USDT 미입력 시 기본값)
    'swing [USDT]'    → SL만 + 추세 반전 모니터링
    """

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        parts = (update.message.text or "").strip().lower().split()
        chat_id = str(update.effective_chat.id)

        # positive [amount]
        if parts[:1] == ["positive"]:
            mode = "full"
            reverse = False
            amount_parts = parts[1:]
        # swing [amount]
        elif parts[:1] == ["swing"]:
            mode = "swing"
            reverse = False
            amount_parts = parts[1:]
        # reverse [amount]
        elif parts[:1] == ["reverse"]:
            mode = "full"
            reverse = True
            amount_parts = parts[1:]
        else:
            return

        # amount_parts에서 signal_id(알파벳)와 usdt(숫자) 분리
        # 예) ["A", "500"] / ["500"] / ["A"] / []
        signal_id = None
        usdt_override = None
        for part in amount_parts:
            if part.isalpha() and len(part) == 1:
                signal_id = part.lower()
            else:
                try:
                    usdt_override = float(part)
                except ValueError:
                    await messenger.post_message(chat_id, f"❌ 파싱 실패: {part}")
                    return

        result = await executor.on_confirm(mode, usdt_override=usdt_override, reverse=reverse, signal_id=signal_id)
        await messenger.post_message(chat_id, result)

    return handler
