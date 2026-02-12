import abc
from custom_logger.CustomLogger import Logger
from messenger_bot.Singleton import Singleton


class MessengerBot(metaclass=Singleton):
    def set_logger(self):
        if self.logger is None:
            self.logger = Logger()
        self.logger = self.logger.use_logger()

    @abc.abstractmethod
    def post_message(self):
        pass

    @abc.abstractmethod
    def post_link(self):
        pass

    @abc.abstractmethod
    def upload_file(self):
        pass


