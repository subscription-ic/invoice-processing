"""
Tests for Phase 9 Config Engine and Feature Flags endpoints.

Unauthenticated requests must return 401.
Authenticated tests require a live DB (auto-skipped if not seeded).
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Unauthenticated — 401
# ---------------------------------------------------------------------------

class TestConfigRequiresAuth:

    async def test_get_config_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/v1/config")
        assert resp.status_code == 401

    async def test_patch_config_requires_auth(self, client: AsyncClient):
        resp = await client.patch("/api/v1/config", json={"updates": {"max_upload_mb": 20}})
        assert resp.status_code == 401

    async def test_list_flags_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/v1/config/feature-flags")
        assert resp.status_code == 401

    async def test_create_flag_requires_auth(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/config/feature-flags",
            json={"flag_name": "new_feature", "is_enabled": False},
        )
        assert resp.status_code == 401

    async def test_patch_flag_requires_auth(self, client: AsyncClient):
        resp = await client.patch(
            "/api/v1/config/feature-flags/use_langgraph",
            json={"is_enabled": True},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# OpenAPI schema — routes registered
# ---------------------------------------------------------------------------

class TestConfigSchemaRegistered:

    async def test_config_paths_in_openapi(self, client: AsyncClient):
        resp = await client.get("/api/openapi.json")
        assert resp.status_code == 200
        paths = resp.json().get("paths", {})
        assert any("/config" in p for p in paths), "Config endpoint not in OpenAPI"
        assert any("feature-flags" in p for p in paths), "Feature flags endpoint not in OpenAPI"


# ---------------------------------------------------------------------------
# Security: forbidden patterns in config keys
# ---------------------------------------------------------------------------

class TestConfigSecretRejection:

    async def test_secret_key_rejected(self, client: AsyncClient, require_auth: dict):
        resp = await client.patch(
            "/api/v1/config",
            json={"updates": {"openai_api_key": "sk-xxxx"}},
            headers=require_auth,
        )
        assert resp.status_code == 400
        assert "forbidden" in resp.json()["detail"].lower()

    async def test_password_key_rejected(self, client: AsyncClient, require_auth: dict):
        resp = await client.patch(
            "/api/v1/config",
            json={"updates": {"smtp_password": "mypassword"}},
            headers=require_auth,
        )
        assert resp.status_code == 400

    async def test_token_key_rejected(self, client: AsyncClient, require_auth: dict):
        resp = await client.patch(
            "/api/v1/config",
            json={"updates": {"bearer_token": "abc123"}},
            headers=require_auth,
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Authenticated config CRUD — live DB required
# ---------------------------------------------------------------------------

class TestConfigCRUD:

    async def test_get_config_returns_dict(self, client: AsyncClient, require_auth: dict):
        resp = await client.get("/api/v1/config", headers=require_auth)
        assert resp.status_code == 200
        data = resp.json()
        assert "tenant_id" in data
        assert "pipeline" in data
        assert "thresholds" in data

    async def test_patch_safe_key_persisted(self, client: AsyncClient, require_auth: dict):
        resp = await client.patch(
            "/api/v1/config",
            json={"updates": {"max_upload_mb": 25, "custom_note": "test"}},
            headers=require_auth,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["persisted"] is True
        assert "max_upload_mb" in data["updated_keys"]

    async def test_patch_reflects_in_get(self, client: AsyncClient, require_auth: dict):
        unique_key = f"cfg_{uuid.uuid4().hex[:8]}"
        await client.patch(
            "/api/v1/config",
            json={"updates": {unique_key: "hello_world"}},
            headers=require_auth,
        )
        get_resp = await client.get("/api/v1/config", headers=require_auth)
        assert get_resp.status_code == 200
        assert get_resp.json().get(unique_key) == "hello_world"


# ---------------------------------------------------------------------------
# Authenticated feature flag CRUD — live DB required
# ---------------------------------------------------------------------------

class TestFeatureFlagCRUD:

    async def test_list_flags_returns_dict(self, client: AsyncClient, require_auth: dict):
        resp = await client.get("/api/v1/config/feature-flags", headers=require_auth)
        assert resp.status_code == 200
        data = resp.json()
        assert "flags" in data
        assert "total" in data

    async def test_create_flag(self, client: AsyncClient, require_auth: dict):
        flag_name = f"flag_{uuid.uuid4().hex[:8]}"
        resp = await client.post(
            "/api/v1/config/feature-flags",
            json={"flag_name": flag_name, "is_enabled": False, "description": "Test flag"},
            headers=require_auth,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["flag_name"] == flag_name
        assert data["is_enabled"] is False

    async def test_duplicate_flag_returns_409(self, client: AsyncClient, require_auth: dict):
        flag_name = f"dup_flag_{uuid.uuid4().hex[:8]}"
        payload = {"flag_name": flag_name, "is_enabled": False}
        await client.post("/api/v1/config/feature-flags", json=payload, headers=require_auth)
        resp = await client.post("/api/v1/config/feature-flags", json=payload, headers=require_auth)
        assert resp.status_code == 409

    async def test_toggle_flag_enabled(self, client: AsyncClient, require_auth: dict):
        flag_name = f"toggle_{uuid.uuid4().hex[:8]}"
        await client.post(
            "/api/v1/config/feature-flags",
            json={"flag_name": flag_name, "is_enabled": False},
            headers=require_auth,
        )
        toggle_resp = await client.patch(
            f"/api/v1/config/feature-flags/{flag_name}",
            json={"is_enabled": True},
            headers=require_auth,
        )
        assert toggle_resp.status_code == 200
        assert toggle_resp.json()["is_enabled"] is True

    async def test_patch_nonexistent_flag_returns_404(self, client: AsyncClient, require_auth: dict):
        resp = await client.patch(
            "/api/v1/config/feature-flags/nonexistent_flag_xyz",
            json={"is_enabled": True},
            headers=require_auth,
        )
        assert resp.status_code == 404

    async def test_delete_flag(self, client: AsyncClient, require_auth: dict):
        flag_name = f"del_{uuid.uuid4().hex[:8]}"
        await client.post(
            "/api/v1/config/feature-flags",
            json={"flag_name": flag_name, "is_enabled": False},
            headers=require_auth,
        )
        del_resp = await client.delete(
            f"/api/v1/config/feature-flags/{flag_name}",
            headers=require_auth,
        )
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "deleted"
