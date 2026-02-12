from messenger_bot.interface import MessengerBot
from telegram import Bot
from telegram.error import TelegramError
from custom_logger import Logger


class TelegramBot(MessengerBot):
    def __init__(self, client: Bot, logger: Logger = None):
        self.client = client
        self.logger = logger
        self.set_logger()

    async def post_message(self, chat_id: str, text: str):
        try:
            response = await self.client.send_message(chat_id=chat_id, text=text)
            self.logger.debug(response)
        except TelegramError as e:
            self.logger.error(str(e))

    async def post_link(self, chat_id: str, link: str, title: str):
        try:
            response = await self.client.send_message(
                chat_id=chat_id,
                text=f"[{title}]({link})",
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
            self.logger.debug(response)
        except TelegramError as e:
            self.logger.error(str(e))

    async def upload_file(self, chat_id: str, file_path: str, file_name: str = None, caption=None):
        try:
            with open(file_path, "rb") as f:
                response = await self.client.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=file_name,
                    caption=caption,
                )
            self.logger.debug(response)
        except TelegramError as e:
            self.logger.error(str(e))