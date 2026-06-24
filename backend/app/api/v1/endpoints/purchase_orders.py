from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_async_session
from app.core.security import get_current_user
from app.models.models import PurchaseOrder, POLineItem, User, Vendor
from app.schemas.schemas import PurchaseOrderCreate, PurchaseOrderListOut, PurchaseOrderOut, PurchaseOrderUpdate, POLineItemOut

router = APIRouter(prefix="/purchase-orders", tags=["Purchase Orders"])


@router.get("", response_model=List[PurchaseOrderListOut])
async def list_pos(
    status: Optional[str] = Query(None),
    vendor_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    q = select(PurchaseOrder).options(selectinload(PurchaseOrder.vendor))
    if status:
        q = q.where(PurchaseOrder.status == status)
    if vendor_id:
        q = q.where(PurchaseOrder.vendor_id == vendor_id)
    q = q.order_by(desc(PurchaseOrder.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    pos = result.scalars().all()
    return [
        PurchaseOrderListOut(
            id=str(po.id), po_number=po.po_number,
            vendor_id=str(po.vendor_id), vendor_name=po.vendor.name if po.vendor else None,
            status=po.status, total_amount=po.total_amount, currency=po.currency,
            po_date=po.po_date, created_at=po.created_at,
        )
        for po in pos
    ]


@router.post("", response_model=PurchaseOrderOut, status_code=201)
async def create_po(
    body: PurchaseOrderCreate,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    existing = await db.execute(select(PurchaseOrder).where(PurchaseOrder.po_number == body.po_number))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="PO number already exists")

    po = PurchaseOrder(
        **{k: v for k, v in body.model_dump().items() if k != "line_items"},
        created_by=str(current_user.id),
    )
    db.add(po)
    await db.flush()

    for item in body.line_items:
        li = POLineItem(po_id=po.id, **item.model_dump())
        db.add(li)

    await db.flush()
    result = await db.execute(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.vendor), selectinload(PurchaseOrder.line_items))
        .where(PurchaseOrder.id == po.id)
    )
    po = result.scalar_one()
    return _map_po(po)


@router.get("/{po_id}", response_model=PurchaseOrderOut)
async def get_po(
    po_id: str,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.vendor), selectinload(PurchaseOrder.line_items))
        .where((PurchaseOrder.id == po_id) | (PurchaseOrder.po_number == po_id))
    )
    po = result.scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
    return _map_po(po)


@router.patch("/{po_id}", response_model=PurchaseOrderOut)
async def update_po(
    po_id: str,
    body: PurchaseOrderUpdate,
    db: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    po = result.scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="PO not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(po, k, v)
    await db.flush()
    result = await db.execute(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.vendor), selectinload(PurchaseOrder.line_items))
        .where(PurchaseOrder.id == po_id)
    )
    return _map_po(result.scalar_one())


def _map_po(po: PurchaseOrder) -> PurchaseOrderOut:
    return PurchaseOrderOut(
        id=str(po.id), po_number=po.po_number,
        vendor_id=str(po.vendor_id), vendor_name=po.vendor.name if po.vendor else None,
        status=po.status, total_amount=po.total_amount, invoiced_amount=po.invoiced_amount,
        currency=po.currency, payment_terms=po.payment_terms, po_date=po.po_date,
        delivery_date=po.delivery_date, created_at=po.created_at,
        line_items=[
            POLineItemOut(
                id=str(li.id), line_number=li.line_number, item_code=li.item_code,
                description=li.description, hsn_sac_code=li.hsn_sac_code,
                quantity=li.quantity, received_quantity=li.received_quantity,
                invoiced_quantity=li.invoiced_quantity, unit_price=li.unit_price,
                uom=li.uom, total_amount=li.total_amount,
                cgst_rate=li.cgst_rate, sgst_rate=li.sgst_rate, igst_rate=li.igst_rate,
            )
            for li in po.line_items
        ],
    )