"""Pytest configuration and shared fixtures for CiteVerify tests."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base, get_db
import app.models.tables  # noqa: F401 - ensure models registered in Base.metadata
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


@pytest_asyncio.fixture(scope="function", autouse=True)
async def setup_test_database():
    """Create all database tables before each test and drop after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncSession:
    """Provide clean database session for each test."""
    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def async_client(db_session: AsyncSession) -> AsyncClient:
    """Provide AsyncClient wired with test database session override."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def protect_gemini_api_quota(request, monkeypatch):
    """Prevent automated tests from burning user Gemini API quota.

    Permits live API calls only when test is marked with @pytest.mark.live_gemini
    or when RUN_LIVE_GEMINI=true is set in the environment.
    """
    import os
    if request.node.get_closest_marker("live_gemini"):
        return
    if os.getenv("RUN_LIVE_GEMINI", "").lower() in ("true", "1"):
        return
    # Tests that explicitly mock httpx.AsyncClient at the network layer don't need _post_generate mocked
    if "TestGeminiLLMClient" in request.node.nodeid:
        return

    from app.core.llm import GeminiLLMClient

    async def mock_post(self, payload):
        return {
            "_status": "provider_error",
            "fallback_reason": "provider_error",
            "error": "Automated test sandbox: live API disabled to conserve quota",
            "model": self.model,
        }

    monkeypatch.setattr(GeminiLLMClient, "_post_generate", mock_post)
