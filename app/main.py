"""
Personal Knowledge Bot — FastAPI application entry point.

Startup sequence:
  1. Configure structured logging
  2. Initialise PostgreSQL (create tables, enable pgvector)
  3. Connect to Redis (ARQ pool + rate limiter)
  4. Mount routers

Shutdown:
  1. Close ARQ Redis pool
  2. Dispose SQLAlchemy engine
"""
import contextlib
import logging

import redis.asyncio as aioredis
import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, close_db
from app.rate_limiter import RateLimiter
from app.routers.webhook import router as webhook_router


def _configure_logging(log_level: str) -> None:
    """Set up structlog with timestamps and log level filtering."""
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
    """FastAPI lifespan context — runs startup then yields for shutdown."""
    settings = get_settings()
    _configure_logging(settings.log_level)

    log = structlog.get_logger(__name__)
    log.info("startup_begin", version="1.0.0")

    # ── Database ──────────────────────────────────────────────────────────────
    await init_db()

    # ── Redis for ARQ jobs ────────────────────────────────────────────────────
    import re
    m = re.match(r"redis://([^:/]+):(\d+)", settings.redis_url)
    redis_host = m.group(1) if m else "localhost"
    redis_port = int(m.group(2)) if m else 6379

    arq_pool = await create_pool(RedisSettings(host=redis_host, port=redis_port))
    app.state.arq_pool = arq_pool

    # ── Redis for rate limiter ────────────────────────────────────────────────
    rate_redis = aioredis.from_url(settings.redis_url, decode_responses=False)
    app.state.rate_limiter = RateLimiter(
        redis=rate_redis,
        max_requests=settings.rate_limit_max_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )

    log.info(
        "startup_complete",
        model=settings.claude_fast_model,
        arq_max_jobs=settings.arq_max_jobs,
        rate_limit=f"{settings.rate_limit_max_requests}/{settings.rate_limit_window_seconds}s",
    )

    yield  # ← app runs here

    # ── Shutdown ──────────────────────────────────────────────────────────────
    log.info("shutdown_begin")
    await arq_pool.close()
    await rate_redis.aclose()
    await close_db()
    log.info("shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Personal Knowledge Bot",
        description=(
            "WhatsApp AI agent that captures multi-modal content "
            "(voice, images, links, text) and organises it into structured knowledge articles. "
            "Demonstrates: Claude agent orchestration, parallel subagents, "
            "ARQ message queuing, and Redis rate limiting."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(webhook_router, tags=["webhook"])

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok", "service": "personal-knowledge-bot"}

    return app


app = create_app()
