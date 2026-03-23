"""FastAPI entrypoint for the Telegram-only stack."""
import contextlib
import logging

import redis.asyncio as aioredis
import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import close_db, init_db
from app.rate_limiter import RateLimiter
from app.routers.webhook_telegram import router as telegram_router


def _configure_logging(log_level: str) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
    )


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _configure_logging(settings.log_level)

    log = structlog.get_logger(__name__)
    log.info("telegram_startup_begin")

    await init_db()

    import re

    m = re.match(r"redis://([^:/]+):(\d+)", settings.redis_url)
    redis_host = m.group(1) if m else "localhost"
    redis_port = int(m.group(2)) if m else 6379

    arq_pool = await create_pool(RedisSettings(host=redis_host, port=redis_port))
    app.state.arq_pool = arq_pool

    rate_redis = aioredis.from_url(settings.redis_url, decode_responses=False)
    app.state.rate_limiter = RateLimiter(
        redis=rate_redis,
        max_requests=settings.rate_limit_max_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )

    log.info("telegram_startup_complete")

    yield

    log.info("telegram_shutdown_begin")
    await arq_pool.close()
    await rate_redis.aclose()
    await close_db()
    log.info("telegram_shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Personal Knowledge Bot — Telegram",
        description=(
            "Telegram AI agent that captures multi-modal content and funnels it "
            "into the same knowledge backend used by the WhatsApp stack."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(telegram_router, tags=["telegram-webhook"])

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok", "service": "personal-knowledge-bot-telegram"}

    return app


app = create_app()
