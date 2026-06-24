"""
Shared pytest fixtures for all test modules.

asyncio_mode=auto (see pytest.ini) — all async fixtures / tests run automatically.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


# ---------------------------------------------------------------------------
# HTTP client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def client() -> AsyncClient:
    """Unauthenticated ASGI test client."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def auth_headers(client: AsyncClient) -> dict:
    """
    Returns Bearer auth headers using the seeded admin account.
    Returns empty dict when the database is not seeded (CI without DB).
    """
    response = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin@company.com", "password": "password123"},
    )
    if response.status_code == 200:
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return {}


# ---------------------------------------------------------------------------
# Helper: skip when not authenticated (DB not seeded)
# ---------------------------------------------------------------------------

@pytest.fixture
def require_auth(auth_headers: dict):
    """
    Skip the test if we could not obtain an auth token.
    Use as a fixture dependency in tests that need a live DB.
    """
    if not auth_headers:
        pytest.skip("DB not seeded — skipping authenticated test")
    return auth_headers
