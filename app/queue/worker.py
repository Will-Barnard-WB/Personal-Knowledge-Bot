"""
ARQ Worker configuration.

Run with:
    arq app.queue.worker.WorkerSettings

Architecture notes:
  - max_jobs: Hard cap on simultaneous Claude API calls, acting as a rate limit
    against Claude model throughput and API budget limits
  - on_startup / on_shutdown: Manage shared resources (HTTP client, DB pool)
    injected into every task via the `ctx` dict
  - keep_result: Jobs are kept in Redis for 24h so you can inspect their status
  - retry_jobs: Failed jobs are retried up to 3 times
"""
import structlog
import httpx
from arq.connections import RedisSettings

from app.config import get_settings
from app.queue.tasks import process_message
from app.database import init_db, close_db

log = structlog.get_logger(__name__)


async def startup(ctx: dict) -> None:
    """
    Called once when the worker process starts.
    Initialise shared resources and inject them into the context dict —
    all tasks receive this ctx automatically.
    """
    settings = get_settings()
    ctx["settings"] = settings

    # Shared HTTP client (connection-pooled) for gateway send-back calls
    ctx["http_client"] = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )

    # Ensure DB tables exist (idempotent)
    await init_db()

    log.info("worker_started", max_jobs=settings.arq_max_jobs)


async def shutdown(ctx: dict) -> None:
    """Called once when the worker shuts down cleanly."""
    await ctx["http_client"].aclose()
    await close_db()
    log.info("worker_shutdown")


def _build_redis_settings() -> RedisSettings:
    settings = get_settings()
    # arq.RedisSettings accepts host/port separately
    import re
    m = re.match(r"redis://([^:/]+):(\d+)", settings.redis_url)
    host = m.group(1) if m else "localhost"
    port = int(m.group(2)) if m else 6379
    return RedisSettings(host=host, port=port)


class WorkerSettings:
    """
    ARQ worker settings class — discovered by `arq` CLI via dotted module path.

    Demonstrates:
      - Message Queue: ARQ + Redis for durable async job processing
      - Rate limiting via max_jobs: no more than N concurrent LLM calls
      - Lifecycle hooks: startup / shutdown for resource management
    """
    functions = [process_message]

    # Shared Redis connection settings
    redis_settings = _build_redis_settings()

    # Lifecycle hooks
    on_startup = startup
    on_shutdown = shutdown

    # Concurrency control — caps simultaneous Claude Agent SDK jobs
    max_jobs = get_settings().arq_max_jobs

    # Jobs are retried up to 3 times on failure before being marked failed
    max_tries = 3

    # Keep completed job results in Redis for 24h (useful for debugging)
    keep_result = 86_400

    # Poll Redis for new jobs every 0.5s
    poll_delay = 0.5

    # Job health check interval
    health_check_interval = 30
