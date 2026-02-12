from messenger_bot.SlackBot import SlackBot
from slack_sdk import WebClient

if __name__ == '__main__':
    slack_token = ''
    telegram_token = ''

    slack_channel_id = ''

    client = WebClient(token=slack_token)

    handler = SlackBot(client)
    handler2 = SlackBot(client)
    print(f"싱글톤 테스트: {handler2 == handler}")

    handler.check_and_join_channel(channel=slack_channel_id)

    handler.post_message(channel=slack_channel_id, text='슬랙 커스텀 모듈 file 전송 테스트1')
    handler.upload_file(channel=slack_channel_id, file='test_file.txt', title='test file upload')
    handler.post_link(channel=slack_channel_id, text='https://wavebridge.com')
