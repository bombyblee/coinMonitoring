from messenger_bot.TelegramBot import TelegramBot
from telegram import Bot
import os, requests

if __name__ == '__main__':
 
    TOKEN = os.getenv("TELEGRAM_TOKEN")  # 환경변수에 넣어둔 토큰
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    print(requests.get(url).json())