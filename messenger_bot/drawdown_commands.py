from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes


def make_drawdown_handler(state, messenger):
    """
    drawdown on   — 드로우다운 가드 활성화
    drawdown off  — 드로우다운 가드 비활성화
    drawdown      — 현재 상태 조회
    """

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        chat_id = str(update.effective_chat.id)
        parts = (update.message.text or "").strip().split()

        if len(parts) == 1:
            status = "🟢 활성화" if state.drawdown_enabled else "🔴 비활성화"
            await messenger.post_message(chat_id, f"드로우다운 가드: {status}")
            return

        action = parts[1].lower()
        if action == "on":
            state.drawdown_enabled = True
            await messenger.post_message(chat_id, "🟢 드로우다운 가드 활성화됨")
        elif action == "off":
            state.drawdown_enabled = False
            await messenger.post_message(chat_id, "🔴 드로우다운 가드 비활성화됨")
        else:
            await messenger.post_message(chat_id, "사용법: drawdown on / drawdown off")

    return handler
