import os
from telegram import Update
from telegram.ext import ContextTypes
from crypto.orders.sl_tp_parser import parse_sl_tp_intent


def _allowed_user(update: Update) -> bool:
    allowed = os.getenv("ALLOWED_USER_IDS", "").strip()
    if not allowed:
        return False
    allowset = {int(x) for x in allowed.split(",") if x.strip()}
    return update.effective_user and update.effective_user.id in allowset


def make_sl_tp_handler(sl_tp_monitor, messenger):
    """
    SL/TP 명령어 핸들러 팩토리.

    지원 명령:
      <번호> tp <타겟> <기준>   예) 1 tp 100 usdt
      <번호> sl <타겟> <기준>   예) 2 sl 66000 btc
      sltp list                 현재 등록된 트리거 목록
      sltp cancel <id>          트리거 취소
    """
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _allowed_user(update):
            return

        chat_id = str(update.effective_chat.id)
        text = (update.message.text or "").strip()
        lowered = text.lower()

        # --- sltp 관리 명령 ---
        if lowered.startswith("sltp"):
            parts = text.split()
            sub = parts[1].lower() if len(parts) > 1 else ""

            if sub == "list":
                msg = sl_tp_monitor.list_triggers(chat_id)
                await messenger.post_message(chat_id, msg)
                return

            if sub == "cancel":
                if len(parts) < 3:
                    await messenger.post_message(
                        chat_id, "❌ 형식: sltp cancel <트리거ID>\n예) sltp cancel 3"
                    )
                    return
                try:
                    trigger_id = int(parts[2])
                    msg = await sl_tp_monitor.cancel(trigger_id, chat_id)
                    await messenger.post_message(chat_id, msg)
                except ValueError as e:
                    await messenger.post_message(chat_id, f"❌ 취소 실패: {e}")
                return

            await messenger.post_message(
                chat_id,
                "sltp 명령:\n  sltp list\n  sltp cancel <ID>",
            )
            return

        # --- SL/TP 등록 명령 ---
        try:
            intent = parse_sl_tp_intent(text)
        except ValueError as e:
            await messenger.post_message(chat_id, f"❌ 파싱 오류: {e}")
            return

        try:
            confirm = await sl_tp_monitor.register(intent, chat_id)
            await messenger.post_message(chat_id, confirm)
        except Exception as e:
            await messenger.post_message(chat_id, f"❌ 등록 실패: {e}")

    return handler
