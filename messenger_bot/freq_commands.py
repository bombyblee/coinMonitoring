import os
from telegram import Update
from telegram.ext import ContextTypes

def _allowed(update: Update) -> bool:
    allowed = os.getenv("ALLOWED_USER_IDS", "").strip()
    if not allowed:
        return False
    allowset = {int(x) for x in allowed.split(",") if x.strip()}
    return update.effective_user and update.effective_user.id in allowset

def make_freq_text_handler(state, price_job, pnl_job, messenger, chat_id_getter):
    """
    - state.price_freq_sec / state.pnl_freq_sec 변경
    - job 재시작(즉시 반영)
    """
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _allowed(update):
            return

        chat_id = chat_id_getter(update)
        text = (update.message.text or "").strip().lower()

        if not text.startswith("freq"):
            return

        parts = text.split()
        try:
            # freq 600
            if len(parts) == 2:
                sec = int(parts[1])
                state.pnl_freq_sec = sec
                await pnl_job.stop()
                await pnl_job.start(chat_id)
                await messenger.post_message(chat_id, f"✅ pnl freq -> {sec}s")

            # freq price 60  / freq pnl 600
            elif len(parts) == 3:
                target = parts[1]
                sec = int(parts[2])
                if target == "price":
                    state.price_freq_sec = sec
                    await price_job.stop()
                    await price_job.start(chat_id)
                    await messenger.post_message(chat_id, f"✅ price freq -> {sec}s")
                elif target in ("pnl", "report"):
                    state.pnl_freq_sec = sec
                    await pnl_job.stop()
                    await pnl_job.start(chat_id)
                    await messenger.post_message(chat_id, f"✅ pnl freq -> {sec}s")
                else:
                    await messenger.post_message(chat_id, "형식: freq [price|pnl] <sec>")
            else:
                await messenger.post_message(chat_id, "형식: freq <sec>  또는  freq price <sec> / freq pnl <sec>")

        except Exception as e:
            await messenger.post_message(chat_id, f"❌ freq 변경 실패: {e}")

    return handler
