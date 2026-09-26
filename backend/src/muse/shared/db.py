"""Async SQLAlchemy engine. Controllers take an `AsyncConnection` and run Core queries."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from muse.shared.settings import Settings


def create_engine(settings: Settings, *, pool_size: int = 5) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=pool_size,
        pool_pre_ping=True,
        connect_args={"timeout": settings.probe_timeout_seconds},
    )
