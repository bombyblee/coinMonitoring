from telegram import Update
from telegram.ext import ContextTypes

def make_handlers(state, messenger):
    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        state.start()
        await messenger.post_message(
            str(update.effective_chat.id),
            "▶️ 리포트 재개"
        )

    async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        state.stop()
        await messenger.post_message(
            str(update.effective_chat.id),
            "⏸ 리포트 중지"
        )

    return start_cmd, stop_cmd
