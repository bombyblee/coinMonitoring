import os
from dotenv import load_dotenv
from binance.um_futures import UMFutures

load_dotenv()

api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

client = UMFutures(
    key=api_key,
    secret=api_secret,
    base_url="https://fapi.binance.com"  # USDT-M Futures
)

# 1️⃣ 계좌 정보
account = client.account()
print("Account OK")
print("Can Trade:", account.get("canTrade"))
print("Assets (USDT):")
for a in account["assets"]:
    if a["asset"] == "USDT":
        print(a)

# 2️⃣ 현재 포지션 요약
positions = client.get_position_risk(symbol="BTCUSDT")
print(positions)
for p in positions:
    if float(p["positionAmt"]) != 0:
        print(p)
