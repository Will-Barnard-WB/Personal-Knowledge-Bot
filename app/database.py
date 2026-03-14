"""
Database connection, session management, and table creation.

Uses SQLAlchemy async engine + asyncpg driver.
pgvector extension is enabled on first startup.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.config import get_settings

log = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base — all models inherit from this."""
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database sessions."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """
    Initialise the database:
      1. Enable pgvector extension
      2. Create all tables (if they don't exist)
    Safe to call on every startup.
    """
    engine = get_engine()

    async with engine.begin() as conn:
        # Enable pgvector
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        log.info("pgvector extension enabled")

        # Import models here to ensure they are registered with Base.metadata
        from app.models import note, article  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
        log.info("Database tables created / verified")


async def close_db() -> None:
    """Dispose of the engine connection pool (called on app shutdown)."""
    if _engine:
        await _engine.dispose()
        log.info("Database engine disposed")
