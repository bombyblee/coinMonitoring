from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Awaitable

import websockets

logger = logging.getLogger(__name__)

_WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"


class LiquidationStream:
    """
    Binance 전체 심볼 강제 청산 이벤트 스트림 (public, 인증 불필요).

    메시지 형식:
      e: "forceOrder"
      o.s: symbol
      o.S: "BUY" (short 청산) | "SELL" (long 청산)
      o.ap: average price (str)
      o.z:  cumulative filled qty (str)
      o.T:  trade time (ms)
    """

    def __init__(self, ws_url: str = _WS_URL):
        self._ws_url = ws_url
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self, on_liquidation: Callable[[dict], Awaitable[None]]) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(on_liquidation), name="liquidation_stream"
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            await asyncio.sleep(0)

    async def _run(self, on_liquidation: Callable[[dict], Awaitable[None]]) -> None:
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self._ws_url, ping_interval=180, ping_timeout=600
                ) as ws:
                    logger.info("LiquidationStream connected")
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        if msg.get("e") != "forceOrder":
                            continue
                        try:
                            await on_liquidation(msg)
                        except Exception as e:
                            logger.warning("on_liquidation error: %s", e)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("LiquidationStream disconnected: %s — reconnecting in 3s", e)
                await asyncio.sleep(3)
