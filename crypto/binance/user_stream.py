import os, json, asyncio
import requests
import websockets

_FINAL = {"FILLED", "CANCELED", "REJECTED", "EXPIRED"}

class UserDataStream:
    """
    Binance USD-M Futures user data stream:
    - POST /fapi/v1/listenKey
    - PUT  /fapi/v1/listenKey (keepalive)
    - WS: wss://fstream.binance.com/ws/<listenKey>
    """
    def __init__(self, api_key: str, rest_base: str = "https://fapi.binance.com",
                 ws_base: str = "wss://fstream.binance.com/ws"):
        self.api_key = api_key
        self.rest_base = rest_base.rstrip("/")
        self.ws_base = ws_base.rstrip("/")
        self.listen_key: str | None = None

        self._ws_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def _headers(self):
        return {"X-MBX-APIKEY": self.api_key}

    def create_listen_key(self) -> str:
        r = requests.post(f"{self.rest_base}/fapi/v1/listenKey", headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()["listenKey"]

    def keepalive(self):
        r = requests.put(f"{self.rest_base}/fapi/v1/listenKey", headers=self._headers(), timeout=10)
        r.raise_for_status()

    async def start(self, on_message):
        """
        on_message: async callable that receives parsed json dict
        """
        self._stop.clear()
        self.listen_key = await asyncio.to_thread(self.create_listen_key)

        async def keepalive_loop():
            # 권장: 30분~50분마다. 여기선 30분.
            while not self._stop.is_set():
                await asyncio.sleep(30 * 60)
                try:
                    await asyncio.to_thread(self.keepalive)
                except Exception:
                    # keepalive 실패해도 ws가 살아있으면 계속 돌고,
                    # 만료되면 ws에서 이벤트/끊김으로 감지 가능
                    pass

        async def ws_loop():
            url = f"{self.ws_base}/{self.listen_key}"
            while not self._stop.is_set():
                try:
                    async with websockets.connect(url, ping_interval=180, ping_timeout=600) as ws:
                        async for raw in ws:
                            if self._stop.is_set():
                                break
                            try:
                                msg = json.loads(raw)
                            except Exception:
                                continue
                            await on_message(msg)
                except Exception:
                    # 재연결 백오프
                    await asyncio.sleep(2)

        self._keepalive_task = asyncio.create_task(keepalive_loop())
        self._ws_task = asyncio.create_task(ws_loop())

    async def stop(self):
        self._stop.set()
        for t in (self._ws_task, self._keepalive_task):
            if t:
                t.cancel()
        await asyncio.sleep(0)  # cancellation yield
