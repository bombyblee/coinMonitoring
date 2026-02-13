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


async def main():
    cfg = load_config()

    # messenger (send용)
    tg_client = Bot(cfg.telegram_token)
    messenger = TelegramBot(tg_client)

    state = ReportState()
    reporter = FuturesReporterJob(
        symbol=cfg.symbol,
        interval_sec=cfg.interval_sec,
        messenger=messenger,
        state=state,
    )

    # command listener (receive용)
    app = Application.builder().token(cfg.telegram_token).build()
    start_cmd, stop_cmd = make_handlers(state, messenger)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))

    # 앱 초기화 & 폴링 시작 (async 방식)
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    await messenger.post_message(cfg.telegram_chat_id, "🤖 Reporter started")

    # 리포터는 별도 task로
    reporter_task = asyncio.create_task(reporter.run_forever(cfg.telegram_chat_id))

    trader = BinanceFuturesTrader(
    api_key=os.getenv("BINANCE_API_KEY"),
    api_secret=os.getenv("BINANCE_API_SECRET"),
    )

    risk = RiskConfig(
        max_usdt_per_order=float(os.getenv("MAX_USDT_PER_ORDER", "200")),
        allowed_symbols=set((os.getenv("ALLOWED_SYMBOLS", "BTCUSDT,ETHUSDT")).split(",")),
    )

    order_service = OrderService(trader, risk)

    trade_handler = make_trade_text_handler(order_service, messenger)
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), trade_handler))

    try:
        # 프로그램 계속 유지 (Ctrl+C로 종료)
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        reporter_task.cancel()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
