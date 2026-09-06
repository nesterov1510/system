"""Tiny in-memory rate limiter (single process MVP).

Публичные QR-страницы не требуют аутентификации, поэтому ограничиваем число
запросов по IP. Для развёртывания в несколько воркеров замените на Redis-backed
лимитер — точки вызова менять не нужно.

Словарь ключей очищается: без этого каждый новый IP навсегда оставался бы в
памяти (публичный эндпоинт => неограниченный рост).
"""
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int = 60, window: float = 60.0, sweep_every: int = 512):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque] = defaultdict(deque)
        # Сколько вызовов между полными очистками словаря.
        self._sweep_every = max(1, sweep_every)
        self._calls = 0

    def _prune(self, now: float) -> None:
        """Выбросить ключи, у которых не осталось свежих попаданий."""
        for key in [k for k, dq in self._hits.items() if not dq or now - dq[-1] > self.window]:
            self._hits.pop(key, None)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        self._calls += 1
        if self._calls % self._sweep_every == 0:
            self._prune(now)

        dq = self._hits[key]
        while dq and now - dq[0] > self.window:
            dq.popleft()
        if len(dq) >= self.limit:
            return False
        dq.append(now)
        return True

    def __len__(self) -> int:
        """Число отслеживаемых ключей (для диагностики/тестов)."""
        return len(self._hits)


# Общий экземпляр: 60 запросов в минуту с IP на публичных эндпоинтах.
public_limiter = RateLimiter(limit=60, window=60.0)
