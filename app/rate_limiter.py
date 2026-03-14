"""
Redis-backed sliding-window rate limiter.

Algorithm: sorted-set (ZSET) with timestamps as scores.
  1. ZADD — add current request timestamp
  2. ZREMRANGEBYSCORE — remove items older than the window
  3. ZCARD — count remaining items
  4. EXPIRE — auto-clean key after window expires
Operations are wrapped in a Lua script for atomicity (no race conditions).

Usage:
    limiter = RateLimiter(redis_client)
    allowed, count = await limiter.check("447700900000@c.us")
"""
import time
from dataclasses import dataclass

import redis.asyncio as aioredis
import structlog

log = structlog.get_logger(__name__)

# Lua script — runs atomically on the Redis server
_SLIDING_WINDOW_SCRIPT = """
local key       = KEYS[1]
local now       = tonumber(ARGV[1])
local window    = tonumber(ARGV[2])
local max_req   = tonumber(ARGV[3])
local window_ms = window * 1000

-- Remove entries outside the current window
redis.call('ZREMRANGEBYSCORE', key, 0, now - window_ms)

-- Count remaining entries
local count = redis.call('ZCARD', key)

if count < max_req then
    -- Allow: record this request
    redis.call('ZADD', key, now, now)
    redis.call('PEXPIRE', key, window_ms)
    return {1, count + 1}
else
    -- Deny: do NOT add, just return current count
    return {0, count}
end
"""


@dataclass
class RateLimitResult:
    allowed: bool
    count: int  # requests in current window


class RateLimiter:
    """
    Sliding-window rate limiter backed by Redis sorted sets.

    Parameters
    ----------
    redis : aioredis.Redis
        Async Redis client.
    max_requests : int
        Maximum number of requests permitted per window.
    window_seconds : int
        Length of the sliding window in seconds.
    key_prefix : str
        Redis key prefix — allows multiple limiters to coexist.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        max_requests: int = 10,
        window_seconds: int = 60,
        key_prefix: str = "pkb:ratelimit",
    ) -> None:
        self._redis = redis
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._key_prefix = key_prefix
        # Register the Lua script once; Redis caches it by SHA1
        self._script = self._redis.register_script(_SLIDING_WINDOW_SCRIPT)

    async def check(self, user_id: str) -> RateLimitResult:
        """
        Check whether `user_id` is within the rate limit.

        Returns a RateLimitResult with:
          - allowed: True if the request should be processed
          - count:   Current number of requests this window
        """
        key = f"{self._key_prefix}:{user_id}"
        now_ms = int(time.time() * 1000)  # milliseconds for sub-second precision

        result = await self._script(
            keys=[key],
            args=[now_ms, self._window_seconds, self._max_requests],
        )
        allowed = bool(result[0])
        count = int(result[1])

        if not allowed:
            log.warning("rate_limit_exceeded", user_id=user_id, count=count)

        return RateLimitResult(allowed=allowed, count=count)
