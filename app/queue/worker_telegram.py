"""Telegram ARQ worker configuration."""
import httpx
import structlog
from arq.connections import RedisSettings

from app.config import get_settings
from app.database import close_db, init_db
from app.queue.tasks_telegram import process_telegram_message

log = structlog.get_logger(__name__)


async def startup(ctx: dict) -> None:
    settings = get_settings()
    ctx["settings"] = settings
    ctx["http_client"] = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    await init_db()
    log.info("telegram_worker_started", max_jobs=settings.arq_max_jobs)


async def shutdown(ctx: dict) -> None:
    await ctx["http_client"].aclose()
    await close_db()
    log.info("telegram_worker_shutdown")


def _build_redis_settings() -> RedisSettings:
    settings = get_settings()
    import re

    m = re.match(r"redis://([^:/]+):(\d+)", settings.redis_url)
    host = m.group(1) if m else "localhost"
    port = int(m.group(2)) if m else 6379
    return RedisSettings(host=host, port=port)


class WorkerTelegramSettings:
    functions = [process_telegram_message]
    redis_settings = _build_redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = get_settings().arq_max_jobs
    max_tries = 3
    keep_result = 86_400
    poll_delay = 0.5
    health_check_interval = 30
