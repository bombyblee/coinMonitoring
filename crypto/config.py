import os
from dataclasses import dataclass
from dotenv import load_dotenv

@dataclass(frozen=True)
class AppConfig:
    telegram_token: str
    telegram_chat_id: str
    symbol: str = "BTCUSDT"
    interval_sec: int = 600  # 10분

def load_config() -> AppConfig:
    load_dotenv()
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token:
        raise RuntimeError("TELEGRAM_TOKEN missing")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID missing")

    symbol = os.getenv("BINANCE_SYMBOL", "BTCUSDT")
    interval_sec = int(os.getenv("REPORT_INTERVAL_SEC", "600"))

    return AppConfig(
        telegram_token=token,
        telegram_chat_id=chat_id,
        symbol=symbol,
        interval_sec=interval_sec,
    )