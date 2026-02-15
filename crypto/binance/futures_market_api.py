from .http_client import HttpClient
from .models import FuturesSnapshot, ms_to_dt

class BinanceFuturesMarketApi:
    """
    USDT-M Futures public market data
    """
    def __init__(self):
        self.http = HttpClient(base_url="https://fapi.binance.com")

    def fetch_snapshot(self, symbol: str) -> FuturesSnapshot:
        # last price
        t = self.http.get("/fapi/v1/ticker/price", params={"symbol": symbol})
        last_price = float(t["price"])

        # mark / funding
        p = self.http.get("/fapi/v1/premiumIndex", params={"symbol": symbol})
        mark_price = float(p["markPrice"]) if "markPrice" in p else None
        index_price = float(p["indexPrice"]) if "indexPrice" in p else None
        funding_rate = float(p["lastFundingRate"]) if "lastFundingRate" in p else None
        nft = ms_to_dt(int(p["nextFundingTime"])) if p.get("nextFundingTime") else None

        return FuturesSnapshot(
            symbol=symbol,
            last_price=last_price,
            mark_price=mark_price,
            index_price=index_price,
            funding_rate=funding_rate,
            next_funding_time=nft,
        )
    
    def fetch_last_price(self, symbol: str) -> float:
        """
        last/lastPrice만 가져오는 함수로 래핑.
        네가 쓰는 실제 client 메서드명에 맞춰 수정해.
        """
        t = self.http.get("/fapi/v1/ticker/price", params={"symbol": symbol})
        last_price = float(t["price"])
        return last_price
