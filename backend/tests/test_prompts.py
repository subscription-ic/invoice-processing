"""
Tests for Phase 9 Prompt Registry endpoints.

Unauthenticated requests must always return 401.
Authenticated CRUD tests require a live DB (auto-skipped if not seeded).
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Unauthenticated — 401
# ---------------------------------------------------------------------------

class TestPromptsRequireAuth:

    async def test_list_prompts_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/v1/prompts")
        assert resp.status_code == 401

    async def test_create_prompt_requires_auth(self, client: AsyncClient):
        resp = await client.post("/api/v1/prompts", json={
            "name": "test_prompt",
            "version": "1.0",
            "content": "Test content",
        })
        assert resp.status_code == 401

    async def test_get_content_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/v1/prompts/classification/content")
        assert resp.status_code == 401

    async def test_activate_requires_auth(self, client: AsyncClient):
        resp = await client.post("/api/v1/prompts/classification/activate", json={"version": "1.0"})
        assert resp.status_code == 401

    async def test_history_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/v1/prompts/classification/history")
        assert resp.status_code == 401

    async def test_delete_requires_auth(self, client: AsyncClient):
        resp = await client.delete("/api/v1/prompts/classification/1.0")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# OpenAPI schema — routes registered
# ---------------------------------------------------------------------------

class TestPromptsSchemaRegistered:

    async def test_prompts_in_openapi(self, client: AsyncClient):
        resp = await client.get("/api/openapi.json")
        assert resp.status_code == 200
        paths = resp.json().get("paths", {})
        assert any("/prompts" in p for p in paths), "Prompts endpoints not in OpenAPI"
        assert any("/activate" in p for p in paths), "Prompt activate endpoint not in OpenAPI"
        assert any("/history" in p for p in paths), "Prompt history endpoint not in OpenAPI"
        assert any("/content" in p for p in paths), "Prompt content endpoint not in OpenAPI"


# ---------------------------------------------------------------------------
# Authenticated CRUD — requires live DB
# ---------------------------------------------------------------------------

class TestPromptsCRUD:

    async def test_list_returns_list(self, client: AsyncClient, require_auth: dict):
        resp = await client.get("/api/v1/prompts", headers=require_auth)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_and_retrieve_prompt(self, client: AsyncClient, require_auth: dict):
        unique_name = f"test_prompt_{uuid.uuid4().hex[:8]}"
        create_resp = await client.post(
            "/api/v1/prompts",
            json={
                "name": unique_name,
                "version": "1.0",
                "content": "You are an AP automation assistant.",
                "description": "Test prompt",
                "activate_immediately": True,
            },
            headers=require_auth,
        )
        assert create_resp.status_code == 201
        data = create_resp.json()
        assert data["name"] == unique_name
        assert data["version"] == "1.0"
        assert data["is_active"] is True

        # Retrieve content
        content_resp = await client.get(
            f"/api/v1/prompts/{unique_name}/content",
            headers=require_auth,
        )
        assert content_resp.status_code == 200
        assert content_resp.json()["content"] == "You are an AP automation assistant."

    async def test_duplicate_version_returns_409(self, client: AsyncClient, require_auth: dict):
        unique_name = f"dup_{uuid.uuid4().hex[:8]}"
        payload = {"name": unique_name, "version": "1.0", "content": "First content"}
        await client.post("/api/v1/prompts", json=payload, headers=require_auth)
        resp = await client.post("/api/v1/prompts", json=payload, headers=require_auth)
        assert resp.status_code == 409

    async def test_activate_nonexistent_returns_404(self, client: AsyncClient, require_auth: dict):
        resp = await client.post(
            "/api/v1/prompts/nonexistent_prompt/activate",
            json={"version": "99.0"},
            headers=require_auth,
        )
        assert resp.status_code == 404

    async def test_delete_active_version_returns_409(self, client: AsyncClient, require_auth: dict):
        unique_name = f"del_{uuid.uuid4().hex[:8]}"
        await client.post(
            "/api/v1/prompts",
            json={"name": unique_name, "version": "1.0", "content": "X", "activate_immediately": True},
            headers=require_auth,
        )
        resp = await client.delete(f"/api/v1/prompts/{unique_name}/1.0", headers=require_auth)
        # Active version must not be deletable
        assert resp.status_code == 409

    async def test_history_returns_versions(self, client: AsyncClient, require_auth: dict):
        unique_name = f"hist_{uuid.uuid4().hex[:8]}"
        await client.post(
            "/api/v1/prompts",
            json={"name": unique_name, "version": "1.0", "content": "v1", "activate_immediately": True},
            headers=require_auth,
        )
        await client.post(
            "/api/v1/prompts",
            json={"name": unique_name, "version": "2.0", "content": "v2"},
            headers=require_auth,
        )
        resp = await client.get(f"/api/v1/prompts/{unique_name}/history", headers=require_auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_versions"] == 2
        version_nums = {v["version"] for v in data["versions"]}
        assert {"1.0", "2.0"} == version_nums
