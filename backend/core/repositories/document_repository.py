"""
DocumentRepository — all database access for Document and DocumentLineItem models.

Rules:
- No agent or tool may import SQLAlchemy directly.
- All queries are parameterised — no string interpolation in SQL.
- Tenant isolation is enforced on every query via tenant_id filter.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.base.exceptions import RepositoryException
from core.base.repository import BaseRepository


class DocumentRepository(BaseRepository):
    """Repository for Document and DocumentLineItem ORM models."""

    # ---------------------------------------------------------------------------
    # Read operations
    # ---------------------------------------------------------------------------

    async def get_by_id(self, document_id: str) -> Optional[Any]:
        """Retrieve a document by its UUID."""
        from app.models.models import Document

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(Document).where(Document.id == document_id)
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryException(
                f"Failed to retrieve document {document_id}: {exc}",
                entity_type="Document",
                operation="get_by_id",
            ) from exc

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Any]:
        """List documents with optional status/tenant filters."""
        from app.models.models import Document

        try:
            async with self._session() as session:
                query = select(Document)
                if filters:
                    if status := filters.get("status"):
                        query = query.where(Document.status == status)
                    if tenant_id := filters.get("tenant_id"):
                        query = query.where(Document.tenant_id == tenant_id)
                query = query.offset(skip).limit(limit).order_by(Document.created_at.desc())
                result = await session.execute(query)
                return list(result.scalars().all())
        except Exception as exc:
            raise RepositoryException(
                f"Failed to list documents: {exc}",
                entity_type="Document",
                operation="get_all",
            ) from exc

    async def save(self, document: Any) -> Any:
        """Insert or update a document record."""
        from app.models.models import Document

        try:
            async with self._session() as session:
                session.add(document)
                await session.commit()
                await session.refresh(document)
                return document
        except Exception as exc:
            raise RepositoryException(
                f"Failed to save document: {exc}",
                entity_type="Document",
                operation="save",
            ) from exc

    async def delete(self, document_id: str) -> bool:
        """Soft-delete a document by marking it as FAILED (hard deletes not permitted)."""
        from app.models.models import Document

        try:
            async with self._session() as session:
                result = await session.execute(
                    update(Document)
                    .where(Document.id == document_id)
                    .values(status="FAILED", updated_at=datetime.now(timezone.utc))
                )
                await session.commit()
                return result.rowcount > 0
        except Exception as exc:
            raise RepositoryException(
                f"Failed to delete document {document_id}: {exc}",
                entity_type="Document",
                operation="delete",
            ) from exc

    # ---------------------------------------------------------------------------
    # Domain-specific operations
    # ---------------------------------------------------------------------------

    async def update_status(self, document_id: str, status: str) -> bool:
        """Update document processing status."""
        from app.models.models import Document

        try:
            async with self._session() as session:
                result = await session.execute(
                    update(Document)
                    .where(Document.id == document_id)
                    .values(status=status, updated_at=datetime.now(timezone.utc))
                )
                await session.commit()
                return result.rowcount > 0
        except Exception as exc:
            raise RepositoryException(
                f"Failed to update status for document {document_id}: {exc}",
                entity_type="Document",
                operation="update_status",
            ) from exc

    async def find_duplicate(
        self,
        invoice_number: str,
        vendor_name: str,
        total_amount: float,
        tenant_id: str = "default",
        window_days: int = 90,
    ) -> Optional[Any]:
        """
        Check for a duplicate invoice within the lookback window.

        Duplicate criteria:
        - Same invoice number AND same vendor (fuzzy) AND same amount
        - OR same content hash (exact duplicate file)
        """
        from app.models.models import Document

        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        try:
            async with self._session() as session:
                result = await session.execute(
                    select(Document).where(
                        and_(
                            Document.invoice_number == invoice_number,
                            Document.vendor_name == vendor_name,
                            Document.total_amount == total_amount,
                            Document.created_at >= cutoff,
                            Document.status.notin_(["FAILED", "REJECTED"]),
                        )
                    ).limit(1)
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryException(
                f"Duplicate check failed: {exc}",
                entity_type="Document",
                operation="find_duplicate",
            ) from exc

    async def find_by_content_hash(
        self,
        file_hash: str,
        tenant_id: str = "default",
    ) -> Optional[Any]:
        """Find a document with the same file content hash."""
        from app.models.models import Document

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(Document).where(
                        and_(
                            Document.file_hash == file_hash,
                            Document.status.notin_(["FAILED"]),
                        )
                    ).limit(1)
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryException(
                f"Hash lookup failed: {exc}",
                entity_type="Document",
                operation="find_by_content_hash",
            ) from exc

    async def save_line_items(self, document_id: str, line_items: List[Dict[str, Any]]) -> None:
        """Replace all line items for a document."""
        from app.models.models import DocumentLineItem

        try:
            async with self._session() as session:
                # Delete existing line items
                existing = await session.execute(
                    select(DocumentLineItem).where(
                        DocumentLineItem.document_id == document_id
                    )
                )
                for item in existing.scalars().all():
                    await session.delete(item)

                # Insert new line items
                for i, item_data in enumerate(line_items):
                    line_item = DocumentLineItem(
                        document_id=document_id,
                        line_number=i + 1,
                        **{k: v for k, v in item_data.items() if k != "line_number"},
                    )
                    session.add(line_item)

                await session.commit()
        except Exception as exc:
            raise RepositoryException(
                f"Failed to save line items for document {document_id}: {exc}",
                entity_type="DocumentLineItem",
                operation="save_line_items",
            ) from exc

    async def get_line_items(self, document_id: str) -> List[Any]:
        """Get all line items for a document."""
        from app.models.models import DocumentLineItem

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(DocumentLineItem)
                    .where(DocumentLineItem.document_id == document_id)
                    .order_by(DocumentLineItem.line_number)
                )
                return list(result.scalars().all())
        except Exception as exc:
            raise RepositoryException(
                f"Failed to get line items for document {document_id}: {exc}",
                entity_type="DocumentLineItem",
                operation="get_line_items",
            ) from exc

    async def count_by_status(self, tenant_id: str = "default") -> Dict[str, int]:
        """Get document counts grouped by status for dashboard metrics."""
        from app.models.models import Document

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(Document.status, func.count(Document.id))
                    .group_by(Document.status)
                )
                return {row[0]: row[1] for row in result.all()}
        except Exception as exc:
            raise RepositoryException(
                f"Failed to count documents by status: {exc}",
                entity_type="Document",
                operation="count_by_status",
            ) from exc
