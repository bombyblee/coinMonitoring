_FINAL = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}

async def handle_user_stream_message(
    msg: dict,
    messenger,
    chat_id: str,
):
    # 주문/체결 이벤트는 보통 ORDER_TRADE_UPDATE로 옴
    if msg.get("e") != "ORDER_TRADE_UPDATE":
        return

    o = msg.get("o", {})
    symbol = o.get("s")
    side = o.get("S")
    status = o.get("X")  # 주문상태
    order_id = o.get("i")
    order_type = o.get("o")
    avg_price = o.get("ap")
    filled_qty = o.get("z")  # 누적 체결 수량
    last_fill_px = o.get("L")
    last_fill_qty = o.get("l")

    # "최종 상태" 또는 "부분체결"도 알림
    if status in _FINAL or status == "PARTIALLY_FILLED":
        text = (
            f"📣 체결/주문 업데이트\n"
            f"{symbol} {side} {order_type}\n"
            f"status={status} orderId={order_id}\n"
            f"filled={filled_qty} avg={avg_price}\n"
            f"last={last_fill_qty}@{last_fill_px}"
        )
        await messenger.post_message(chat_id, text)
