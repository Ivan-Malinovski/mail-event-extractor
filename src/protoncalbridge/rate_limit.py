"""Simple in-memory rate limiter."""

import time
from collections import defaultdict
from collections.abc import Callable


class RateLimiter:
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        minute_ago = now - 60

        self.requests[key] = [t for t in self.requests[key] if t > minute_ago]

        if len(self.requests[key]) >= self.requests_per_minute:
            return False

        self.requests[key].append(now)
        return True

    def cleanup(self) -> None:
        now = time.time()
        minute_ago = now - 60
        for key in list(self.requests.keys()):
            self.requests[key] = [t for t in self.requests[key] if t > minute_ago]
            if not self.requests[key]:
                del self.requests[key]


rate_limiter = RateLimiter(requests_per_minute=60)


async def rate_limit_middleware(request, call_next: Callable):
    from fastapi import HTTPException

    client_ip = request.client.host if request.client else "unknown"

    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests")

    return await call_next(request)
