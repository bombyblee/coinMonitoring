import os
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from crypto.orders.parser import parse_order_intent

def _allowed_user(update: Update) -> bool:
    allowed = os.getenv("ALLOWED_USER_IDS", "").strip()
    if not allowed:
        return False  # 기본 거부 (안전)
    allowset = {int(x) for x in allowed.split(",") if x.strip()}
    return update.effective_user and update.effective_user.id in allowset

def make_trade_text_handler(order_service, messenger, state=None):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _allowed_user(update):
            return

        chat_id = str(update.effective_chat.id)
        text = (update.message.text or "").strip()

        # 주문 포맷이 아니면 무시(리포트/대화랑 섞일 수 있으니)
        try:
            intent = parse_order_intent(text)
        except Exception:
            return

        if state and state.trading_paused:
            await messenger.post_message(chat_id, "⏸ 시스템 중지 중 — /start 로 재개 후 주문하세요.")
            return

        try:
            # 1) 주문 접수 알림
            await messenger.post_message(
                chat_id,
                f"🧾 주문 접수\nside={intent.side}\nsymbol={intent.symbol}\nUSDT={intent.usdt_amount}\n"
                + (f"price={intent.price}" if intent.price else "type=MARKET")
            )

            # 2) 주문 전송
            resp = await order_service.place(intent)
            order_id = int(resp["orderId"])
            status = resp.get("status", "UNKNOWN")

            await messenger.post_message(
                chat_id,
                f"✅ 주문 전송 성공\norderId={order_id}\nstatus={status}"
            )

            # 3) 체결/최종 상태 추적 task
            async def _track():
                final = await order_service.wait_final(intent.symbol, order_id, timeout_sec=3600, interval_sec=2.0)
                st = final.get("status", "UNKNOWN")
                # 체결 평균가/체결수량 필드가 응답마다 다를 수 있어 간단히 raw도 같이 보내자
                msg = f"📌 주문 최종 상태: {st}\norderId={order_id}\n{final}"
                await messenger.post_message(chat_id, msg)

            asyncio.create_task(_track())

        except Exception as e:
            await messenger.post_message(chat_id, f"❌ 주문 실패: {e}")

    return handler
