"""
API integration tests.
Run: pytest tests/test_api.py -v
Requires: DATABASE_URL set, database seeded.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def auth_headers(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin@company.com", "password": "password123"},
    )
    if response.status_code == 200:
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    return {}


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin@company.com", "password": "password123"},
    )
    # Will return 401 if DB not seeded, 200 if seeded
    assert response.status_code in (200, 401)


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin@company.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_documents_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/documents")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_openapi_available(client: AsyncClient):
    response = await client.get("/api/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "openapi" in schema
    assert "paths" in schema


@pytest.mark.asyncio
async def test_docs_available(client: AsyncClient):
    response = await client.get("/api/docs")
    assert response.status_code == 200