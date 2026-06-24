"""
VendorRepository — database access for Vendor, PurchaseOrder, GRN, and Contract models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import and_, or_, select

from core.base.exceptions import RepositoryException
from core.base.repository import BaseRepository


class VendorRepository(BaseRepository):
    """Repository for Vendor and related ERP master data."""

    async def get_by_id(self, vendor_id: str) -> Optional[Any]:
        from app.models.models import Vendor

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(Vendor).where(Vendor.id == vendor_id)
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryException(str(exc), "Vendor", "get_by_id") from exc

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Any]:
        from app.models.models import Vendor

        try:
            async with self._session() as session:
                query = select(Vendor).where(Vendor.is_active == True)
                if filters and (search := filters.get("search")):
                    query = query.where(
                        or_(
                            Vendor.name.ilike(f"%{search}%"),
                            Vendor.gstin.ilike(f"%{search}%"),
                        )
                    )
                query = query.offset(skip).limit(limit).order_by(Vendor.name)
                result = await session.execute(query)
                return list(result.scalars().all())
        except Exception as exc:
            raise RepositoryException(str(exc), "Vendor", "get_all") from exc

    async def save(self, vendor: Any) -> Any:
        try:
            async with self._session() as session:
                session.add(vendor)
                await session.commit()
                await session.refresh(vendor)
                return vendor
        except Exception as exc:
            raise RepositoryException(str(exc), "Vendor", "save") from exc

    async def delete(self, vendor_id: str) -> bool:
        from app.models.models import Vendor
        from sqlalchemy import update
        from datetime import datetime, timezone

        try:
            async with self._session() as session:
                result = await session.execute(
                    update(Vendor)
                    .where(Vendor.id == vendor_id)
                    .values(is_active=False, updated_at=datetime.now(timezone.utc))
                )
                await session.commit()
                return result.rowcount > 0
        except Exception as exc:
            raise RepositoryException(str(exc), "Vendor", "delete") from exc

    async def find_by_gstin(self, gstin: str) -> Optional[Any]:
        """Find a vendor by GSTIN — used for matching extracted invoice data."""
        from app.models.models import Vendor

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(Vendor).where(
                        and_(Vendor.gstin == gstin, Vendor.is_active == True)
                    )
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryException(str(exc), "Vendor", "find_by_gstin") from exc

    async def find_by_name_fuzzy(self, name: str, threshold: float = 0.7) -> List[Any]:
        """Find vendors with names similar to the given string."""
        from app.models.models import Vendor

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(Vendor).where(
                        and_(
                            Vendor.name.ilike(f"%{name[:20]}%"),
                            Vendor.is_active == True,
                        )
                    ).limit(10)
                )
                return list(result.scalars().all())
        except Exception as exc:
            raise RepositoryException(str(exc), "Vendor", "find_by_name_fuzzy") from exc


class PurchaseOrderRepository(BaseRepository):
    """Repository for PurchaseOrder and POLineItem models."""

    async def get_by_id(self, po_id: str) -> Optional[Any]:
        from app.models.models import PurchaseOrder

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(PurchaseOrder).where(PurchaseOrder.id == po_id)
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryException(str(exc), "PurchaseOrder", "get_by_id") from exc

    async def get_all(self, skip: int = 0, limit: int = 100, filters: Optional[Dict] = None) -> List[Any]:
        from app.models.models import PurchaseOrder

        try:
            async with self._session() as session:
                query = select(PurchaseOrder)
                if filters:
                    if vendor_id := filters.get("vendor_id"):
                        query = query.where(PurchaseOrder.vendor_id == vendor_id)
                    if status := filters.get("status"):
                        query = query.where(PurchaseOrder.status == status)
                result = await session.execute(query.offset(skip).limit(limit))
                return list(result.scalars().all())
        except Exception as exc:
            raise RepositoryException(str(exc), "PurchaseOrder", "get_all") from exc

    async def save(self, po: Any) -> Any:
        try:
            async with self._session() as session:
                session.add(po)
                await session.commit()
                await session.refresh(po)
                return po
        except Exception as exc:
            raise RepositoryException(str(exc), "PurchaseOrder", "save") from exc

    async def delete(self, po_id: str) -> bool:
        return False  # POs are not deleted; they are closed/cancelled

    async def find_by_po_number(self, po_number: str) -> Optional[Any]:
        """Find a PO by its reference number."""
        from app.models.models import PurchaseOrder

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(PurchaseOrder).where(
                        PurchaseOrder.po_number == po_number
                    ).limit(1)
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryException(str(exc), "PurchaseOrder", "find_by_po_number") from exc

    async def find_open_pos_for_vendor(self, vendor_id: str) -> List[Any]:
        """Find all open POs for a vendor — used when no explicit PO number is present."""
        from app.models.models import PurchaseOrder

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(PurchaseOrder).where(
                        and_(
                            PurchaseOrder.vendor_id == vendor_id,
                            PurchaseOrder.status.in_(["OPEN", "PARTIALLY_RECEIVED"]),
                        )
                    )
                )
                return list(result.scalars().all())
        except Exception as exc:
            raise RepositoryException(str(exc), "PurchaseOrder", "find_open_pos_for_vendor") from exc

    async def get_line_items(self, po_id: str) -> List[Any]:
        from app.models.models import POLineItem

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(POLineItem)
                    .where(POLineItem.po_id == po_id)
                    .order_by(POLineItem.line_number)
                )
                return list(result.scalars().all())
        except Exception as exc:
            raise RepositoryException(str(exc), "POLineItem", "get_line_items") from exc


class GRNRepository(BaseRepository):
    """Repository for GRN and GRNLineItem models."""

    async def get_by_id(self, grn_id: str) -> Optional[Any]:
        from app.models.models import GRN

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(GRN).where(GRN.id == grn_id)
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryException(str(exc), "GRN", "get_by_id") from exc

    async def get_all(self, skip: int = 0, limit: int = 100, filters: Optional[Dict] = None) -> List[Any]:
        from app.models.models import GRN

        try:
            async with self._session() as session:
                query = select(GRN)
                if filters and (po_id := filters.get("po_id")):
                    query = query.where(GRN.po_id == po_id)
                result = await session.execute(query.offset(skip).limit(limit))
                return list(result.scalars().all())
        except Exception as exc:
            raise RepositoryException(str(exc), "GRN", "get_all") from exc

    async def save(self, grn: Any) -> Any:
        try:
            async with self._session() as session:
                session.add(grn)
                await session.commit()
                await session.refresh(grn)
                return grn
        except Exception as exc:
            raise RepositoryException(str(exc), "GRN", "save") from exc

    async def delete(self, grn_id: str) -> bool:
        return False

    async def find_by_grn_number(self, grn_number: str) -> Optional[Any]:
        from app.models.models import GRN

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(GRN).where(GRN.grn_number == grn_number).limit(1)
                )
                return result.scalar_one_or_none()
        except Exception as exc:
            raise RepositoryException(str(exc), "GRN", "find_by_grn_number") from exc

    async def find_by_po_id(self, po_id: str) -> List[Any]:
        from app.models.models import GRN

        try:
            async with self._session() as session:
                result = await session.execute(
                    select(GRN).where(
                        and_(
                            GRN.po_id == po_id,
                            GRN.status.notin_(["REJECTED"]),
                        )
                    )
                )
                return list(result.scalars().all())
        except Exception as exc:
            raise RepositoryException(str(exc), "GRN", "find_by_po_id") from exc
