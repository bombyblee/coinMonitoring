import asyncio
from telegram import Bot

from crypto.config import load_config
from messenger_bot.TelegramBot import TelegramBot
from crypto.jobs.reporter_job import FuturesReporterJob

async def main():
    cfg = load_config()

    tg_client = Bot(cfg.telegram_token)
    messenger = TelegramBot(tg_client)

    job = FuturesReporterJob(
        symbol=cfg.symbol,
        interval_sec=cfg.interval_sec,
        messenger=messenger,
    )
    await messenger.post_message(cfg.telegram_chat_id, "✅ Reporter started")
    await job.run_forever(cfg.telegram_chat_id)

asyncio.run(main())