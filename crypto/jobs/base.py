# jobs/base.py
from __future__ import annotations
import asyncio
from typing import Optional

class ReporterJobBase:
    """
    공통 Reporter Job 베이스
    - start/stop/task 관리
    - enabled 체크
    - interval(초) 가져오기
    - _tick()만 자식이 구현
    """

    def __init__(self, messenger, state):
        self.messenger = messenger
        self.state = state
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    async def start(self, chat_id: str):
        self._stop.clear()
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(chat_id))

    async def stop(self):
        self._stop.set()
        if self._task:
            self._task.cancel()
            # cancel이 이벤트루프에 반영되도록 한 틱 양보
            await asyncio.sleep(0)

    def is_enabled(self) -> bool:
        return bool(getattr(self.state, "enabled", True))

    def interval_sec(self) -> int:
        """
        자식이 override해서 state에서 각자 freq를 읽게 만들기.
        """
        return 60

    async def _tick(self, chat_id: str) -> None:
        """
        자식이 구현: 1회 리포트 동작
        """
        raise NotImplementedError

    async def _run(self, chat_id: str):
        while not self._stop.is_set():
            try:
                if self.is_enabled():
                    await self._tick(chat_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                try:
                    await self.messenger.post_message(chat_id, f"⚠️ report failed: {e}")
                except Exception:
                    pass

            await asyncio.sleep(self.interval_sec())
