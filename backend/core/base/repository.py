"""
BaseRepository — abstract base class for all data repositories.

Design rules:
- Repositories own ALL database access. No agent or tool touches SQLAlchemy directly.
- Repositories accept a session factory, not a session, to manage transaction scope.
- All methods are async to support high-throughput processing.
- Repositories emit no audit events — that is the AuditTool's responsibility.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Generic, List, Optional, TypeVar

T = TypeVar("T")  # ORM entity type
F = TypeVar("F")  # Filter/criteria type


class BaseRepository(ABC, Generic[T]):
    """
    Abstract repository providing standard CRUD and query operations.

    Generic parameter T is the SQLAlchemy ORM model class.
    """

    def __init__(self, session_factory: Callable) -> None:
        """
        Args:
            session_factory: Callable that returns an async SQLAlchemy session.
                             Use the FastAPI Depends() pattern to inject this.
        """
        self._session_factory = session_factory

    # ---------------------------------------------------------------------------
    # Abstract CRUD operations — subclasses must implement
    # ---------------------------------------------------------------------------

    @abstractmethod
    async def get_by_id(self, entity_id: str) -> Optional[T]:
        """Retrieve an entity by primary key. Returns None if not found."""

    @abstractmethod
    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[Any] = None,
    ) -> List[T]:
        """Retrieve a paginated list of entities with optional filters."""

    @abstractmethod
    async def save(self, entity: T) -> T:
        """
        Persist a new or updated entity.

        INSERT if entity has no ID; UPDATE if it already exists.
        Returns the persisted entity with DB-generated fields populated.
        """

    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        """
        Delete an entity by primary key.

        Returns True if the entity existed and was deleted; False otherwise.
        """

    # ---------------------------------------------------------------------------
    # Context helpers available to all repositories
    # ---------------------------------------------------------------------------

    def _session(self):
        """Return a new database session from the factory."""
        return self._session_factory()

    async def _execute_query(self, query_fn: Callable) -> Any:
        """
        Execute a database query within a managed session context.

        Commits on success. Rolls back and re-raises on failure.
        Wraps exceptions in RepositoryException.
        """
        from core.base.exceptions import RepositoryException

        try:
            async with self._session() as session:
                return await query_fn(session)
        except RepositoryException:
            raise
        except Exception as exc:
            raise RepositoryException(
                message=f"Database operation failed: {exc}",
                entity_type=self.__class__.__name__,
                operation="query",
            ) from exc


class ReadOnlyRepository(BaseRepository[T], ABC):
    """
    Repository for read-only access to data (no INSERT/UPDATE/DELETE).

    Used for reference data (vendors, POs, GRNs) fetched from ERP.
    """

    async def save(self, entity: T) -> T:
        raise NotImplementedError("ReadOnlyRepository does not support save operations.")

    async def delete(self, entity_id: str) -> bool:
        raise NotImplementedError("ReadOnlyRepository does not support delete operations.")
