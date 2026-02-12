from messenger_bot.interface import MessengerBot
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from custom_logger import Logger


class SlackBot(MessengerBot):
    def __init__(self, client: WebClient, logger: Logger = None):
        self.client = client
        self.logger = logger
        self.set_logger()

    def check_and_join_channel(self, channel: str):
        try:
            is_joined = self.check_channel_participation(channel)
            self.logger.debug(f"채널 접속상태: {is_joined}")
            if is_joined is True:
                pass
            else:
                self.check_and_join_channel(channel)
        except SlackApiError as e:
            # You will get a SlackApiError if "ok" is False
            assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'
            self.logger.error(e.response)

    def check_channel_participation(self, channel: str):
        try:
            response = self.client.conversations_history(channel=channel, limit=1)
            self.logger.debug(response)
            return True
        except SlackApiError as e:
            error = str(e)
            if 'channel_not_found' in error:
                return False
            else:
                raise e

    def join_channel(self, channel: str):
        try:
            response = self.client.conversations_join(channel=channel)
            self.logger.debug(f"channel join: {response}")

        except SlackApiError as e:
            # You will get a SlackApiError if "ok" is False
            assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'
            self.logger.error(e.response)

    def post_message(self, channel: str, text: str):
        try:
            response = self.client.chat_postMessage(
                channel=channel,
                text=text
            )
            self.logger.debug(response)

        except SlackApiError as e:
            # You will get a SlackApiError if "ok" is False
            assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'
            self.logger.error(e.response)

    def post_link(self, channel: str, text: str):
        try:
            response = self.client.chat_postMessage(
                channel=channel,
                text=text,
                unfurl_links=True
            )
            self.logger.debug(response)

        except SlackApiError as e:
            # You will get a SlackApiError if "ok" is False
            assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'

    def upload_file(self,
                    channel: str,
                    file=None,
                    content=None,
                    filename=None,
                    filetype=None,
                    initial_comment=None,
                    thread_ts=None,
                    title=None,
                    ):
        try:
            response = self.client.files_upload_v2(channel=channel,
                                                   file=file,
                                                   content=content,
                                                   filename=filename,
                                                   filetype=filetype,
                                                   initial_comment=initial_comment,
                                                   thread_ts=thread_ts,
                                                   title=title)
            self.logger.debug(response)

        except SlackApiError as e:
            # You will get a SlackApiError if "ok" is False
            assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'
            self.logger.error(e.response)
