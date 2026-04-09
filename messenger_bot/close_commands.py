from __future__ import annotations

import asyncio
from telegram import Update
from telegram.ext import ContextTypes


def make_close_handler(trader, messenger):
    """
    close <번호>  — PnL 리포트의 포지션 번호로 시장가 전량 청산
    close <심볼>  — 심볼 직접 지정 청산 (예: close BTCUSDT)
    """

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        chat_id = str(update.effective_chat.id)
        parts = (update.message.text or "").strip().split()

        if len(parts) < 2:
            await messenger.post_message(chat_id, "사용법: close <번호> 또는 close <심볼>")
            return

        arg = parts[1]

        # 포지션 목록 조회
        try:
            pos_list = await asyncio.to_thread(trader.client.get_position_risk)
        except Exception as e:
            await messenger.post_message(chat_id, f"❌ 포지션 조회 실패: {e}")
            return

        live = [
            (p["symbol"], float(p["positionAmt"]))
            for p in pos_list
            if abs(float(p.get("positionAmt", 0))) > 1e-12
        ]

        if not live:
            await messenger.post_message(chat_id, "📭 현재 오픈 포지션 없음")
            return

        # 번호 또는 심볼로 대상 특정
        if arg.isdigit():
            idx = int(arg) - 1
            if idx < 0 or idx >= len(live):
                await messenger.post_message(
                    chat_id,
                    f"❌ 번호 {arg} 없음 (현재 포지션 {len(live)}개)"
                )
                return
            symbol, amt = live[idx]
        else:
            symbol = arg.upper()
            matched = [(s, a) for s, a in live if s == symbol]
            if not matched:
                await messenger.post_message(chat_id, f"❌ {symbol} 포지션 없음")
                return
            symbol, amt = matched[0]

        side = "SELL" if amt > 0 else "BUY"
        qty = abs(amt)

        try:
            await trader.new_close_market_order(symbol, side, qty)
            direction = "LONG" if amt > 0 else "SHORT"
            await messenger.post_message(
                chat_id,
                f"✅ {symbol} {direction} 청산 완료\n"
                f"side={side}  qty={qty}"
            )
        except Exception as e:
            await messenger.post_message(chat_id, f"❌ {symbol} 청산 실패: {e}")

    return handler
