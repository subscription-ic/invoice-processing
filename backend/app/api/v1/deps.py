from __future__ import annotations

import uuid as _uuid

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Document


async def resolve_document(db: AsyncSession, document_id: str) -> Document:
    """
    Resolve a document by either its internal UUID (Document.id) or its
    human-readable reference (Document.document_id, e.g. "DOC-20260616-XXXX").

    Document.id is a native Postgres UUID column. Comparing it against an
    arbitrary non-UUID string in the same OR'd WHERE clause crashes at the
    DB driver level — asyncpg validates parameter types strictly and raises
    "invalid input for query argument: invalid UUID '...'" — even though the
    VARCHAR side of the OR would have matched fine. So we only add the
    Document.id condition when the value actually parses as a UUID.

    Every endpoint that takes a `{document_id}` path param should resolve it
    through this helper exactly once, then use the returned `doc.id` (a real
    UUID) for any further joins/filters — never the raw path param.
    """
    conditions = [Document.document_id == document_id]
    try:
        _uuid.UUID(str(document_id))
        conditions.append(Document.id == document_id)
    except (ValueError, AttributeError, TypeError):
        pass

    result = await db.execute(select(Document).where(or_(*conditions)))
    doc = result.scalars().first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc
