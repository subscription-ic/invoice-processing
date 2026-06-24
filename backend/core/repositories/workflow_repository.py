"""
WorkflowRepository — manages WorkflowState DB records and LangGraph checkpoint linkage.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update

from core.base.exceptions import RepositoryException
from core.base.repository import BaseRepository


class WorkflowRepository(BaseRepository):
    """Repository for WorkflowState ORM model and workflow lifecycle management."""

    async def get_by_id(self, workflow_id: str) -> Optional[Any]:
        from app.models.models import WorkflowState as WorkflowStateModel

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(WorkflowStateModel).where(WorkflowStateModel.id == workflow_id)
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryException(str(exc), "WorkflowState", "get_by_id") from exc

    async def get_by_document_id(self, document_id: str) -> Optional[Any]:
        """Get the workflow state record for a document."""
        from app.models.models import WorkflowState as WorkflowStateModel

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(WorkflowStateModel)
                    .where(WorkflowStateModel.document_id == document_id)
                    .order_by(WorkflowStateModel.created_at.desc())
                    .limit(1)
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryException(str(exc), "WorkflowState", "get_by_document_id") from exc

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Any]:
        from app.models.models import WorkflowState as WorkflowStateModel

        try:
            async with self._session() as session:
                query = select(WorkflowStateModel)
                if filters and (status := filters.get("status")):
                    query = query.where(WorkflowStateModel.current_stage == status)
                result = await session.execute(
                    query.offset(skip).limit(limit).order_by(
                        WorkflowStateModel.updated_at.desc()
                    )
                )
                return list(result.scalars().all())
        except Exception as exc:
            raise RepositoryException(str(exc), "WorkflowState", "get_all") from exc

    async def save(self, workflow: Any) -> Any:
        try:
            async with self._session() as session:
                session.add(workflow)
                await session.commit()
                await session.refresh(workflow)
                return workflow
        except Exception as exc:
            raise RepositoryException(str(exc), "WorkflowState", "save") from exc

    async def delete(self, workflow_id: str) -> bool:
        return False  # Workflow records are never deleted

    async def update_stage(
        self,
        document_id: str,
        stage: str,
        agent: str,
        progress_percent: float = 0.0,
        error_message: Optional[str] = None,
    ) -> bool:
        """Update the current processing stage of a workflow."""
        from app.models.models import WorkflowState as WorkflowStateModel

        try:
            async with self._session() as session:
                values: Dict[str, Any] = {
                    "current_stage": stage,
                    "current_agent": agent,
                    "progress_percent": progress_percent,
                    "updated_at": datetime.now(timezone.utc),
                }
                if error_message:
                    values["error_message"] = error_message

                result = await session.execute(
                    update(WorkflowStateModel)
                    .where(WorkflowStateModel.document_id == document_id)
                    .values(**values)
                )
                await session.commit()
                return result.rowcount > 0
        except Exception as exc:
            raise RepositoryException(str(exc), "WorkflowState", "update_stage") from exc

    async def append_stage_history(
        self,
        document_id: str,
        stage_entry: Dict[str, Any],
    ) -> None:
        """Append a stage completion record to the workflow history JSON array."""
        from app.models.models import WorkflowState as WorkflowStateModel
        from sqlalchemy import text

        try:
            async with self._session() as session:
                # Use a raw update to append to the JSONB array atomically
                await session.execute(
                    text(
                        """
                        UPDATE workflow_states
                        SET stage_history = COALESCE(stage_history, '[]'::jsonb) || :entry::jsonb,
                            updated_at = :now
                        WHERE document_id = :doc_id
                        """
                    ),
                    {
                        "entry": json.dumps([stage_entry]),
                        "now": datetime.now(timezone.utc),
                        "doc_id": document_id,
                    },
                )
                await session.commit()
        except Exception as exc:
            raise RepositoryException(str(exc), "WorkflowState", "append_stage_history") from exc

    async def find_stuck_workflows(self, stale_minutes: int = 60) -> List[Any]:
        """Find workflows that have not progressed in a configurable time window."""
        from app.models.models import WorkflowState as WorkflowStateModel
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
        try:
            async with self._session() as session:
                result = await session.execute(
                    select(WorkflowStateModel).where(
                        WorkflowStateModel.updated_at < cutoff,
                        WorkflowStateModel.current_stage.notin_(
                            ["COMPLETED", "EXCEPTION", "FAILED"]
                        ),
                    )
                )
                return list(result.scalars().all())
        except Exception as exc:
            raise RepositoryException(str(exc), "WorkflowState", "find_stuck_workflows") from exc
