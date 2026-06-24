"""
Tenant configuration endpoints — Phase 9 (full implementation).

Replaces the Phase 5 in-memory store with a DB-backed configuration engine:
  - `Configuration` table stores key/value pairs per tenant
  - `FeatureFlag` table stores per-tenant feature flag toggles

Endpoints:
  GET    /config                        — non-secret config (base + DB overrides)
  PATCH  /config                        — persist updates to Configuration table
  GET    /config/feature-flags          — list all feature flags for tenant
  POST   /config/feature-flags          — create a feature flag
  PATCH  /config/feature-flags/{name}   — toggle / update a feature flag

Security rule: keys containing 'key', 'secret', 'password', 'token', 'credential'
               are rejected at the API boundary — secrets belong in Key Vault.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.security import get_current_user
from app.middleware.tenant_middleware import get_tenant_id
from app.models.models import Configuration, FeatureFlag, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/config", tags=["Configuration"])

FORBIDDEN_PATTERNS = ("key", "secret", "password", "token", "credential")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ConfigPatchRequest(BaseModel):
    updates: Dict[str, Any]


class FeatureFlagCreate(BaseModel):
    flag_name: str
    is_enabled: bool = False
    description: Optional[str] = None


class FeatureFlagPatch(BaseModel):
    is_enabled: Optional[bool] = None
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_no_secrets(keys: List[str]) -> None:
    for k in keys:
        if any(p in k.lower() for p in FORBIDDEN_PATTERNS):
            raise HTTPException(
                status_code=400,
                detail=f"Key '{k}' contains a forbidden pattern — secrets cannot be configured via this endpoint",
            )


def _coerce(value_type: str, raw: str) -> Any:
    if value_type == "JSON":
        return json.loads(raw)
    if value_type == "BOOL":
        return raw.lower() in ("true", "1", "yes")
    if value_type == "INT":
        return int(raw)
    if value_type == "FLOAT":
        return float(raw)
    return raw


async def _load_db_overrides(tenant_id: str, db: AsyncSession) -> Dict[str, Any]:
    """Load Configuration rows that belong to this tenant into a flat dict."""
    rows = (await db.execute(
        select(Configuration).where(Configuration.key.startswith(f"{tenant_id}:"))
    )).scalars().all()

    # Also load global rows (key does NOT contain a colon — shared baseline)
    global_rows = (await db.execute(
        select(Configuration).where(~Configuration.key.contains(":"))
    )).scalars().all()

    overrides: Dict[str, Any] = {}
    for row in global_rows:
        try:
            overrides[row.key] = _coerce(row.value_type or "STRING", row.value or "")
        except Exception:
            overrides[row.key] = row.value

    prefix = f"{tenant_id}:"
    for row in rows:
        bare_key = row.key[len(prefix):]
        try:
            overrides[bare_key] = _coerce(row.value_type or "STRING", row.value or "")
        except Exception:
            overrides[bare_key] = row.value

    return overrides


def _build_base_config(tenant_id: str) -> Dict[str, Any]:
    from app.core.config import settings
    return {
        "tenant_id": tenant_id,
        "pipeline": "langgraph" if settings.USE_LANGGRAPH_PIPELINE else "celery",
        "thresholds": {
            "ocr_confidence_pass": settings.OCR_CONFIDENCE_PASS,
            "ocr_confidence_warning": settings.OCR_CONFIDENCE_WARNING,
            "price_tolerance_percent": settings.PRICE_TOLERANCE_PERCENT,
            "quantity_tolerance_percent": settings.QUANTITY_TOLERANCE_PERCENT,
            "tax_tolerance_percent": settings.TAX_TOLERANCE_PERCENT,
        },
        "sla_hours": {
            "ap_team": settings.SLA_AP_TEAM_HOURS,
            "finance": settings.SLA_FINANCE_HOURS,
            "procurement": settings.SLA_PROCUREMENT_HOURS,
            "compliance": settings.SLA_COMPLIANCE_HOURS,
            "warehouse": settings.SLA_WAREHOUSE_HOURS,
        },
        "upload": {
            "max_file_size_mb": settings.MAX_UPLOAD_SIZE_MB,
            "allowed_extensions": settings.allowed_extensions_list,
        },
        "ai": {
            "model": settings.OPENAI_MODEL,
            "max_tokens": settings.OPENAI_MAX_TOKENS,
        },
    }


# ---------------------------------------------------------------------------
# GET /config
# ---------------------------------------------------------------------------

@router.get("", summary="Tenant configuration (non-secret fields only)")
async def get_config(
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    base = _build_base_config(tenant_id)
    db_overrides = await _load_db_overrides(tenant_id, db)
    base.update(db_overrides)
    return base


# ---------------------------------------------------------------------------
# PATCH /config
# ---------------------------------------------------------------------------

@router.patch("", summary="Update tenant configuration (persisted to DB)")
async def patch_config(
    body: ConfigPatchRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    _assert_no_secrets(list(body.updates.keys()))

    upserted: List[str] = []
    for k, v in body.updates.items():
        db_key = f"{tenant_id}:{k}"
        existing = (await db.execute(
            select(Configuration).where(Configuration.key == db_key)
        )).scalar_one_or_none()

        raw = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
        vtype = (
            "JSON" if isinstance(v, (dict, list))
            else "BOOL" if isinstance(v, bool)
            else "INT" if isinstance(v, int)
            else "FLOAT" if isinstance(v, float)
            else "STRING"
        )

        if existing:
            existing.value = raw
            existing.value_type = vtype
        else:
            db.add(Configuration(key=db_key, value=raw, value_type=vtype, category="tenant_override"))

        upserted.append(k)

    await db.commit()
    return {
        "status": "updated",
        "tenant_id": tenant_id,
        "updated_keys": upserted,
        "persisted": True,
    }


# ---------------------------------------------------------------------------
# GET /config/feature-flags
# ---------------------------------------------------------------------------

@router.get("/feature-flags", summary="List feature flags for tenant")
async def list_feature_flags(
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    rows = (await db.execute(
        select(FeatureFlag)
        .where(FeatureFlag.tenant_id == tenant_id)
        .order_by(FeatureFlag.flag_name)
    )).scalars().all()

    return {
        "tenant_id": tenant_id,
        "total": len(rows),
        "flags": [
            {
                "id": str(r.id),
                "flag_name": r.flag_name,
                "is_enabled": r.is_enabled,
                "description": r.description,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# POST /config/feature-flags
# ---------------------------------------------------------------------------

@router.post("/feature-flags", status_code=201, summary="Create a feature flag")
async def create_feature_flag(
    body: FeatureFlagCreate,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    existing = (await db.execute(
        select(FeatureFlag).where(
            FeatureFlag.tenant_id == tenant_id,
            FeatureFlag.flag_name == body.flag_name,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Feature flag '{body.flag_name}' already exists for this tenant",
        )

    flag = FeatureFlag(
        tenant_id=tenant_id,
        flag_name=body.flag_name,
        is_enabled=body.is_enabled,
        description=body.description,
    )
    db.add(flag)
    await db.commit()
    await db.refresh(flag)

    return {
        "status": "created",
        "id": str(flag.id),
        "flag_name": flag.flag_name,
        "is_enabled": flag.is_enabled,
        "tenant_id": tenant_id,
    }


# ---------------------------------------------------------------------------
# PATCH /config/feature-flags/{name}
# ---------------------------------------------------------------------------

@router.patch("/feature-flags/{name}", summary="Toggle or update a feature flag")
async def patch_feature_flag(
    name: str,
    body: FeatureFlagPatch,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    flag = (await db.execute(
        select(FeatureFlag).where(
            FeatureFlag.tenant_id == tenant_id,
            FeatureFlag.flag_name == name,
        )
    )).scalar_one_or_none()
    if not flag:
        raise HTTPException(status_code=404, detail=f"Feature flag '{name}' not found")

    if body.is_enabled is not None:
        flag.is_enabled = body.is_enabled
    if body.description is not None:
        flag.description = body.description

    await db.commit()

    return {
        "status": "updated",
        "flag_name": flag.flag_name,
        "is_enabled": flag.is_enabled,
        "tenant_id": tenant_id,
        "updated_at": flag.updated_at.isoformat() if flag.updated_at else None,
    }


# ---------------------------------------------------------------------------
# DELETE /config/feature-flags/{name}
# ---------------------------------------------------------------------------

@router.delete("/feature-flags/{name}", summary="Delete a feature flag")
async def delete_feature_flag(
    name: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    flag = (await db.execute(
        select(FeatureFlag).where(
            FeatureFlag.tenant_id == tenant_id,
            FeatureFlag.flag_name == name,
        )
    )).scalar_one_or_none()
    if not flag:
        raise HTTPException(status_code=404, detail=f"Feature flag '{name}' not found")
    await db.delete(flag)
    await db.commit()
    return {"status": "deleted", "flag_name": name}
