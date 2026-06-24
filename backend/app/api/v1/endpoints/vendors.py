from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_session
from app.core.security import get_current_user
from app.models.models import User, Vendor, VendorContact
from app.schemas.schemas import VendorCreate, VendorListOut, VendorOut, VendorUpdate

router = APIRouter(prefix="/vendors", tags=["Vendors"])


@router.get("", response_model=List[VendorListOut])
async def list_vendors(
    search: Optional[str] = Query(None),
    is_approved: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    q = select(Vendor)
    if search:
        q = q.where(Vendor.name.ilike(f"%{search}%") | Vendor.vendor_code.ilike(f"%{search}%"))
    if is_approved is not None:
        q = q.where(Vendor.is_approved == is_approved)
    q = q.order_by(Vendor.name).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    vendors = result.scalars().all()
    return [VendorListOut.model_validate(v) for v in vendors]


@router.post("", response_model=VendorOut, status_code=201)
async def create_vendor(
    body: VendorCreate,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    existing = await db.execute(select(Vendor).where(Vendor.vendor_code == body.vendor_code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Vendor code already exists")

    vendor = Vendor(**{k: v for k, v in body.model_dump().items() if k != "contacts"})
    db.add(vendor)
    await db.flush()

    for contact_data in body.contacts:
        contact = VendorContact(vendor_id=vendor.id, **contact_data.model_dump())
        db.add(contact)

    await db.flush()
    await db.refresh(vendor)
    result = await db.execute(select(Vendor).options(selectinload(Vendor.contacts)).where(Vendor.id == vendor.id))
    vendor = result.scalar_one()
    return VendorOut.model_validate(vendor)


@router.get("/{vendor_id}", response_model=VendorOut)
async def get_vendor(
    vendor_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Vendor).options(selectinload(Vendor.contacts))
        .where((Vendor.id == vendor_id) | (Vendor.vendor_code == vendor_id))
    )
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return VendorOut.model_validate(vendor)


@router.patch("/{vendor_id}", response_model=VendorOut)
async def update_vendor(
    vendor_id: str,
    body: VendorUpdate,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(vendor, k, v)
    await db.flush()
    result = await db.execute(select(Vendor).options(selectinload(Vendor.contacts)).where(Vendor.id == vendor_id))
    return VendorOut.model_validate(result.scalar_one())