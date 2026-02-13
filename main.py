import asyncio
from telegram import Bot
from telegram.ext import Application, CommandHandler
import os
from crypto.config import load_config
from crypto.jobs.report_state import ReportState
from crypto.jobs.reporter_job import FuturesReporterJob
from messenger_bot.TelegramBot import TelegramBot
from messenger_bot.telegram_commands import make_handlers
from crypto.binance.futures_trader import BinanceFuturesTrader
from crypto.orders.service import OrderService, RiskConfig
from messenger_bot.trade_commands import make_trade_text_handler
from telegram.ext import MessageHandler, filters
from crypto.binance.user_stream import UserDataStream
from crypto.orders.fill_notifier import handle_user_stream_message
from messenger_bot.freq_commands import make_freq_text_handler
from crypto.jobs.pnl_reporter import PnlReporterJob


async def main():
    cfg = load_config()

    # messenger (send용)
    tg_client = Bot(cfg.telegram_token)
    messenger = TelegramBot(tg_client)

    state = ReportState()
    
    # command listener (receive용)
    app = Application.builder().token(cfg.telegram_token).build()
    start_cmd, stop_cmd = make_handlers(state, messenger)
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))

    await messenger.post_message(cfg.telegram_chat_id, "🤖 Reporter started")

    trader = BinanceFuturesTrader(
    api_key=os.getenv("BINANCE_API_KEY"),
    api_secret=os.getenv("BINANCE_API_SECRET"),
    )

    risk = RiskConfig(
        max_usdt_per_order=float(os.getenv("MAX_USDT_PER_ORDER", "200")),
        allowed_symbols=set((os.getenv("ALLOWED_SYMBOLS", "BTCUSDT,ETHUSDT")).split(",")),
    )

    # (A) 체결 알림: user stream
    uds = UserDataStream(
        api_key=os.getenv("BINANCE_API_KEY"),
        rest_base=os.getenv("BINANCE_BASE_URL", "https://fapi.binance.com"),
        ws_base="wss://fstream.binance.com/ws",
    )

    async def on_user_stream(msg: dict):
        await handle_user_stream_message(msg, messenger, cfg.telegram_chat_id)

    await uds.start(on_user_stream)

    # (B) 가격/리포트 잡
    price_job = FuturesReporterJob(
        symbol=cfg.symbol,
        messenger=messenger,
        state=state,
    )
    await price_job.start(cfg.telegram_chat_id)
    
    pnl_job = PnlReporterJob(trader=trader, messenger=messenger, state=state)
    await pnl_job.start(cfg.telegram_chat_id)

    # trade handler 생성
    order_service = OrderService(trader, risk)
    trade_handler = make_trade_text_handler(order_service, messenger)
    

    # freq 텍스트 핸들러 (주기 변경)
    freq_handler = make_freq_text_handler(
        state=state,
        price_job=price_job,
        pnl_job=pnl_job,
        messenger=messenger,
        chat_id_getter=lambda u: str(u.effective_chat.id),
    )
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), freq_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), trade_handler))

    # 앱 초기화 & 폴링 시작 (async 방식)
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    try:
        # 프로그램 계속 유지 (Ctrl+C로 종료)
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await uds.stop()
        await pnl_job.stop()
        await price_job.stop()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
