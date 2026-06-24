"""
Tests for Phase 8 Explainable AI endpoints.

All endpoints require authentication; without it they must return 401.
Authenticated tests require a live DB (skipped when not seeded).
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Unauthenticated — should always return 401
# ---------------------------------------------------------------------------

class TestExplainEndpointsRequireAuth:

    async def test_document_explanation_requires_auth(self, client: AsyncClient):
        doc_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/documents/{doc_id}/explanation")
        assert resp.status_code == 401

    async def test_exception_explanation_requires_auth(self, client: AsyncClient):
        exc_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/exceptions/{exc_id}/explanation")
        assert resp.status_code == 401

    async def test_approval_recommendation_requires_auth(self, client: AsyncClient):
        appr_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/approvals/{appr_id}/recommendation")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# OpenAPI schema — routes registered
# ---------------------------------------------------------------------------

class TestExplainSchemaRegistered:

    async def test_explanation_paths_in_openapi(self, client: AsyncClient):
        resp = await client.get("/api/openapi.json")
        assert resp.status_code == 200
        paths = resp.json().get("paths", {})
        assert any("/explanation" in p for p in paths), (
            "Document explanation path not found in OpenAPI schema"
        )
        assert any("/recommendation" in p for p in paths), (
            "Approval recommendation path not found in OpenAPI schema"
        )


# ---------------------------------------------------------------------------
# Authenticated — 404 for non-existent documents (live DB required)
# ---------------------------------------------------------------------------

class TestExplainEndpointsAuthenticated:

    async def test_unknown_document_returns_404(self, client: AsyncClient, require_auth: dict):
        doc_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/documents/{doc_id}/explanation",
            headers=require_auth,
        )
        assert resp.status_code == 404

    async def test_unknown_exception_returns_404(self, client: AsyncClient, require_auth: dict):
        exc_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/exceptions/{exc_id}/explanation",
            headers=require_auth,
        )
        assert resp.status_code == 404

    async def test_unknown_approval_returns_404(self, client: AsyncClient, require_auth: dict):
        appr_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/approvals/{appr_id}/recommendation",
            headers=require_auth,
        )
        assert resp.status_code == 404
