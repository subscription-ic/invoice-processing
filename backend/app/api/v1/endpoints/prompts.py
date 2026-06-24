"""
Prompt Registry endpoints — Phase 9 (full implementation).

Replaces Phase 5 stubs with a DB-backed versioned prompt registry.
Each (tenant_id, prompt_name, version) triple is a unique row in the
prompt_versions table.  Only ONE version per (tenant, name) is active
at a time; activation deactivates all other versions for that pair.

Endpoints:
  GET    /prompts                    — list all prompts (latest active per name)
  POST   /prompts                    — create a new prompt version
  GET    /prompts/{name}/content     — get active content for agents to load
  POST   /prompts/{name}/activate    — activate a specific version
  GET    /prompts/{name}/history     — full version history for a prompt
  DELETE /prompts/{name}/{version}   — soft-delete a specific version
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_session
from app.core.security import get_current_user
from app.middleware.tenant_middleware import get_tenant_id
from app.models.models import PromptVersion, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/prompts", tags=["Prompts"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PromptVersionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    version: str = Field(..., min_length=1, max_length=20)
    content: str = Field(..., min_length=1)
    description: Optional[str] = None
    activate_immediately: bool = False


class PromptVersionOut(BaseModel):
    id: str
    name: str
    version: str
    description: Optional[str]
    is_active: bool
    tenant_id: str
    created_at: Optional[str]
    activated_at: Optional[str]


class PromptActivateRequest(BaseModel):
    version: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_out(pv: PromptVersion) -> PromptVersionOut:
    return PromptVersionOut(
        id=str(pv.id),
        name=pv.prompt_name,
        version=pv.version,
        description=pv.description,
        is_active=pv.is_active,
        tenant_id=pv.tenant_id,
        created_at=pv.created_at.isoformat() if pv.created_at else None,
        activated_at=pv.activated_at.isoformat() if pv.activated_at else None,
    )


async def _seed_from_yaml(tenant_id: str, db: AsyncSession) -> None:
    """
    Seed DB from YAML files in core/prompts/ on first access.
    Only runs if the tenant has zero prompt records.
    """
    existing = (await db.execute(
        select(PromptVersion).where(PromptVersion.tenant_id == tenant_id).limit(1)
    )).scalar_one_or_none()
    if existing:
        return

    try:
        from pathlib import Path
        import re

        prompts_base = Path(__file__).parents[5] / "core" / "prompts"
        alt_base = Path(__file__).parents[5] / "app" / "prompts"
        base = prompts_base if prompts_base.exists() else alt_base

        for yaml_file in sorted(base.glob("**/*.yaml")):
            try:
                content = yaml_file.read_text(encoding="utf-8")
            except Exception:
                content = f"# Prompt: {yaml_file.stem}\n# Add content here."
            pv = PromptVersion(
                tenant_id=tenant_id,
                prompt_name=yaml_file.stem,
                version="1.0",
                content=content,
                description=f"Seeded from {yaml_file.name}",
                is_active=True,
                activated_at=datetime.now(timezone.utc),
            )
            db.add(pv)
        await db.flush()
    except Exception as exc:
        logger.debug("Prompt YAML seed skipped: %s", exc)


# ---------------------------------------------------------------------------
# GET /prompts  — list active prompts per name
# ---------------------------------------------------------------------------

@router.get("", response_model=List[PromptVersionOut], summary="List active prompt versions")
async def list_prompts(
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    await _seed_from_yaml(tenant_id, db)
    rows = (await db.execute(
        select(PromptVersion)
        .where(PromptVersion.tenant_id == tenant_id, PromptVersion.is_active == True)  # noqa: E712
        .order_by(PromptVersion.prompt_name)
    )).scalars().all()
    return [_to_out(r) for r in rows]


# ---------------------------------------------------------------------------
# POST /prompts  — create a new version
# ---------------------------------------------------------------------------

@router.post("", response_model=PromptVersionOut, status_code=201, summary="Create prompt version")
async def create_prompt(
    body: PromptVersionCreate,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    # Check uniqueness
    existing = (await db.execute(
        select(PromptVersion).where(
            PromptVersion.tenant_id == tenant_id,
            PromptVersion.prompt_name == body.name,
            PromptVersion.version == body.version,
        )
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Prompt '{body.name}' version '{body.version}' already exists for this tenant",
        )

    if body.activate_immediately:
        # Deactivate all existing versions for this name
        await db.execute(
            update(PromptVersion)
            .where(PromptVersion.tenant_id == tenant_id, PromptVersion.prompt_name == body.name)
            .values(is_active=False)
        )

    pv = PromptVersion(
        tenant_id=tenant_id,
        prompt_name=body.name,
        version=body.version,
        content=body.content,
        description=body.description,
        is_active=body.activate_immediately,
        created_by=str(current_user.id),
        activated_at=datetime.now(timezone.utc) if body.activate_immediately else None,
    )
    db.add(pv)
    await db.commit()
    await db.refresh(pv)
    return _to_out(pv)


# ---------------------------------------------------------------------------
# GET /prompts/{name}/content  — load active content (used by agents)
# ---------------------------------------------------------------------------

@router.get("/{name}/content", summary="Get active prompt content")
async def get_prompt_content(
    name: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    await _seed_from_yaml(tenant_id, db)
    row = (await db.execute(
        select(PromptVersion).where(
            PromptVersion.tenant_id == tenant_id,
            PromptVersion.prompt_name == name,
            PromptVersion.is_active == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"No active prompt '{name}' for this tenant")
    return {
        "name": row.prompt_name,
        "version": row.version,
        "content": row.content,
        "tenant_id": row.tenant_id,
        "activated_at": row.activated_at.isoformat() if row.activated_at else None,
    }


# ---------------------------------------------------------------------------
# POST /prompts/{name}/activate  — activate a specific version
# ---------------------------------------------------------------------------

@router.post("/{name}/activate", summary="Activate a prompt version")
async def activate_prompt(
    name: str,
    body: PromptActivateRequest,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    target = (await db.execute(
        select(PromptVersion).where(
            PromptVersion.tenant_id == tenant_id,
            PromptVersion.prompt_name == name,
            PromptVersion.version == body.version,
        )
    )).scalar_one_or_none()
    if not target:
        raise HTTPException(
            status_code=404,
            detail=f"Prompt '{name}' version '{body.version}' not found",
        )

    # Deactivate all other versions for this name
    await db.execute(
        update(PromptVersion)
        .where(PromptVersion.tenant_id == tenant_id, PromptVersion.prompt_name == name)
        .values(is_active=False)
    )
    target.is_active = True
    target.activated_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "status": "activated",
        "name": name,
        "version": body.version,
        "tenant_id": tenant_id,
        "activated_at": target.activated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# GET /prompts/{name}/history  — all versions ordered newest first
# ---------------------------------------------------------------------------

@router.get("/{name}/history", summary="Prompt version history")
async def prompt_history(
    name: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    await _seed_from_yaml(tenant_id, db)
    rows = (await db.execute(
        select(PromptVersion)
        .where(PromptVersion.tenant_id == tenant_id, PromptVersion.prompt_name == name)
        .order_by(PromptVersion.created_at.desc())
    )).scalars().all()
    return {
        "name": name,
        "tenant_id": tenant_id,
        "total_versions": len(rows),
        "versions": [_to_out(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# DELETE /prompts/{name}/{version}  — remove a specific version
# ---------------------------------------------------------------------------

@router.delete("/{name}/{version}", summary="Delete a prompt version")
async def delete_prompt_version(
    name: str,
    version: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
):
    row = (await db.execute(
        select(PromptVersion).where(
            PromptVersion.tenant_id == tenant_id,
            PromptVersion.prompt_name == name,
            PromptVersion.version == version,
        )
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' v{version} not found")
    if row.is_active:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the active version. Activate another version first.",
        )
    await db.delete(row)
    await db.commit()
    return {"status": "deleted", "name": name, "version": version}
