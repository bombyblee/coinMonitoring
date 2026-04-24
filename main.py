import os
import asyncio

from telegram import Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from messenger_bot.telegram_commands import make_handlers, make_orders_handler, make_help_handler

from crypto.config import load_config
from crypto.binance.futures_market_api import BinanceFuturesMarketApi
from crypto.binance.futures_trader import BinanceFuturesTrader
from crypto.binance.user_stream import UserDataStream

from crypto.orders.service import OrderService, RiskConfig
from crypto.orders.fill_notifier import handle_user_stream_message

from crypto.jobs import ReportState, FuturesReporterJob, PnlReporterJob, DrawdownGuard

from messenger_bot import (
    TelegramBot,
    make_text_router,
    make_trade_text_handler,
    make_freq_text_handler,
    make_sl_tp_handler,
    make_watchlist_handler,
    make_signal_handler,
    make_strategy_handler,
    make_strategy_cmd,
    make_drawdown_handler,
    make_close_handler,
    make_autolist_handler,
)
from crypto.orders.sl_tp_monitor import SlTpMonitor
from crypto.market_data import Watchlist, OhlcvStore, OhlcvJob, LiquidationStream
from crypto.strategies import MomentumBurst, StrategyRunner, SignalExecutor, RsiReversal, EmaCross, LevelAware, LiquidationTrap
from crypto.strategies.trade_logger import TradeLogger

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
        max_usdt_per_order=float(os.getenv("MAX_USDT_PER_ORDER")),
        allowed_symbols=set((os.getenv("ALLOWED_SYMBOLS")).split(",")),
    )

    # trade logger (trader는 userTrades 폴링용)
    trade_logger = TradeLogger(trader=trader, messenger=messenger, chat_id=cfg.telegram_chat_id)
    await trade_logger.start()

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
    market_api = BinanceFuturesMarketApi()

    price_job = FuturesReporterJob(
        symbol=cfg.symbol,
        messenger=messenger,
        state=state,
        market_api=market_api
     ) 
    #await price_job.start(cfg.telegram_chat_id)
    
    pnl_job = PnlReporterJob(
        trader=trader,
        messenger=messenger,
        state=state,
        market_api=market_api,  # ✅ 추가
    )
    await pnl_job.start(cfg.telegram_chat_id)

    # (B-1) 드로우다운 가드
    drawdown_guard = DrawdownGuard(
        trader=trader,
        messenger=messenger,
        chat_id=cfg.telegram_chat_id,
        threshold_usdt=float(os.getenv("DRAWDOWN_THRESHOLD_USDT", "200")),
        state=state,
    )
    await drawdown_guard.start()

    # trade handler 생성
    order_service = OrderService(trader, risk)
    trade_handler = make_trade_text_handler(order_service, messenger, state=state)

    # freq 텍스트 핸들러 (주기 변경)
    freq_handler = make_freq_text_handler(
        state=state,
        price_job=None,  # price_job은 안씀
        pnl_job=pnl_job,
        messenger=messenger,
        chat_id_getter=lambda u: str(u.effective_chat.id),
    )

    # sl/tp 모니터 & 핸들러
    sl_tp_monitor = SlTpMonitor(trader=trader, messenger=messenger, poll_interval=5.0)
    await sl_tp_monitor.start()
    sl_tp_handler = make_sl_tp_handler(sl_tp_monitor, messenger)

    # (C) OHLCV 워치리스트 & 잡
    watchlist = Watchlist(
        os.getenv("WATCHLIST_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
    )
    # 전략 실행 대상 심볼 (워치리스트의 부분집합)
    autolist = Watchlist(
        os.getenv("AUTOLIST_SYMBOLS", "").split(",") if os.getenv("AUTOLIST_SYMBOLS") else []
    )
    ohlcv_store = OhlcvStore(max_len=1500)
    ohlcv_job = OhlcvJob(watchlist=watchlist, store=ohlcv_store)
    await ohlcv_job.start()
    wl_handler = make_watchlist_handler(watchlist, ohlcv_job, autolist=autolist)

    signal_executor = SignalExecutor(
        order_service=order_service,
        trader=trader,
        store=ohlcv_store,
        messenger=messenger,
        chat_id=cfg.telegram_chat_id,
        auto_usdt=float(os.getenv("AUTO_TRADE_USDT", "50")),
        trade_logger=trade_logger,
    )

    strategy_runner = StrategyRunner(
        store=ohlcv_store,
        strategies=[MomentumBurst(), RsiReversal(), EmaCross(), LevelAware()],
        messenger=messenger,
        chat_id=cfg.telegram_chat_id,
        executor=signal_executor,
        max_symbol_usdt=float(os.getenv("MAX_SYMBOL_USDT_TOTAL", "0")),
        state=state,
        autolist=autolist,
    )
    await strategy_runner.start()

    # 청산 추적 전략
    liq_trap = LiquidationTrap(
        executor=signal_executor,
        trader=trader,
        store=ohlcv_store,
        messenger=messenger,
        chat_id=cfg.telegram_chat_id,
        book_ratio=float(os.getenv("LIQ_TRAP_BOOK_RATIO", "0.3")),
        book_levels=int(os.getenv("LIQ_TRAP_BOOK_LEVELS", "20")),
        min_depth_usdt=float(os.getenv("LIQ_TRAP_MIN_DEPTH_USDT", "50000")),
        window_sec=float(os.getenv("LIQ_TRAP_WINDOW_SEC", "30")),
        cooldown_sec=float(os.getenv("LIQ_TRAP_COOLDOWN_SEC", "300")),
        autolist=autolist,
        state=state,
    )
    liq_stream = LiquidationStream()
    await liq_stream.start(liq_trap.on_liquidation)

    signal_hdl = make_signal_handler(signal_executor, messenger)
    strategy_hdl = make_strategy_handler(strategy_runner, messenger)
    drawdown_hdl = make_drawdown_handler(state, messenger)
    close_hdl = make_close_handler(trader, messenger)
    autolist_hdl = make_autolist_handler(autolist, watchlist, messenger)

    # /orders, /help, /strategy 커맨드 핸들러
    app.add_handler(CommandHandler("orders", make_orders_handler(trader, messenger)))
    app.add_handler(CommandHandler("help", make_help_handler(messenger)))
    app.add_handler(CommandHandler("strategy", make_strategy_cmd(strategy_runner, messenger)))

    # text_router 생성 (각 명령어 핸들러 라우팅)
    text_router = make_text_router(
        trade_handler=trade_handler,
        freq_handler=freq_handler,
        sl_tp_handler=sl_tp_handler,
        watchlist_handler=wl_handler,
        signal_handler=signal_hdl,
        strategy_handler=strategy_hdl,
        drawdown_handler=drawdown_hdl,
        close_handler=close_hdl,
        autolist_handler=autolist_hdl,
    )
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text_router))

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
        await trade_logger.stop()
        await uds.stop()
        await liq_stream.stop()
        await sl_tp_monitor.stop()
        await strategy_runner.stop()
        await ohlcv_job.stop()
        await pnl_job.stop()
        await drawdown_guard.stop()
        await price_job.stop()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
