from __future__ import annotations
import asyncio
import time
from collections import deque


class AsyncRateLimiter:
    """보수적 호출 제어용 비동기 레이트리미터.

    - 초당 최대 호출 수를 제한한다(토큰버킷 유사 동작).
    - 분당 최대 호출 수 제한도 선택 적용 가능.
    """

    def __init__(self, per_second: int = 5, per_minute: int | None = None):
        self.per_second = max(1, int(per_second))
        self.per_minute = int(per_minute) if per_minute else None
        self._sec_window = deque()
        self._min_window = deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        while True:
            async with self._lock:
                now = time.monotonic()
                # 1초 창 비우기
                one_sec_ago = now - 1.0
                while self._sec_window and self._sec_window[0] <= one_sec_ago:
                    self._sec_window.popleft()
                # 60초 창 비우기
                if self.per_minute is not None:
                    one_min_ago = now - 60.0
                    while self._min_window and self._min_window[0] <= one_min_ago:
                        self._min_window.popleft()

                can_sec = len(self._sec_window) < self.per_second
                can_min = True if self.per_minute is None else (len(self._min_window) < self.per_minute)

                if can_sec and can_min:
                    self._sec_window.append(now)
                    if self.per_minute is not None:
                        self._min_window.append(now)
                    return

                # 대기 시간 계산
                wait_sec = (self._sec_window[0] + 1.0 - now) if self._sec_window else 0.01
                wait_min = (self._min_window[0] + 60.0 - now) if (self.per_minute and self._min_window) else 0.01
                wait_for = max(wait_sec, wait_min)
            await asyncio.sleep(max(wait_for, 0.01))


