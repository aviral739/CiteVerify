"""Database engine, session management, and Base model."""

from typing import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()


def configure_sqlite_engine(target_engine, busy_timeout_ms: int = 30000, enable_wal: bool = True) -> None:
    """Attach connection listeners for SQLite PRAGMAs (foreign keys, WAL mode, busy timeout)."""
    @event.listens_for(target_engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.execute(f"PRAGMA busy_timeout = {busy_timeout_ms};")
            if enable_wal:
                cursor.execute("PRAGMA journal_mode = WAL;")
        except Exception:
            pass
        finally:
            cursor.close()


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    connect_args={"check_same_thread": False, "timeout": 30.0} if "sqlite" in settings.DATABASE_URL else {},
)

if "sqlite" in settings.DATABASE_URL:
    configure_sqlite_engine(engine)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy database models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables and run idempotent migrations."""
    from app.core.migration import run_migrations

    async with engine.begin() as conn:
        await run_migrations(conn)


async def close_db() -> None:
    """Dispose of database engine connections."""
    await engine.dispose()
