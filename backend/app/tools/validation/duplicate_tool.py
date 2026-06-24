"""DuplicateTool — detect duplicate invoices within the lookback window."""
from __future__ import annotations

import asyncio
from typing import ClassVar, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class DuplicateCheckInput(ToolInput):
    invoice_number: str
    vendor_name: str
    total_amount: float
    file_hash: Optional[str] = None
    tenant_id: str = "default"
    lookback_days: int = 90
    document_id: Optional[str] = None


class DuplicateCheckOutput(ToolOutput):
    is_duplicate: bool = False
    duplicate_document_id: Optional[str] = None
    duplicate_invoice_number: Optional[str] = None
    similarity_score: float = 0.0
    detection_method: Optional[str] = None
    error_code: Optional[str] = None


class DuplicateTool(BaseTool[DuplicateCheckInput, DuplicateCheckOutput]):
    name: ClassVar[str] = "duplicate_check"
    description: ClassVar[str] = "Detect duplicate invoices by invoice number, vendor, amount, or file hash"
    input_model: ClassVar = DuplicateCheckInput
    output_model: ClassVar = DuplicateCheckOutput

    def __init__(self, document_repository=None, **kwargs):
        super().__init__(**kwargs)
        self._doc_repo = document_repository

    def _get_repo(self):
        if self._doc_repo is None:
            from core.container import get_container
            self._doc_repo = get_container().document_repository
        return self._doc_repo

    def _execute(self, input_data: DuplicateCheckInput) -> DuplicateCheckOutput:
        try:
            repo = self._get_repo()
            loop = asyncio.get_event_loop()

            # First check by file hash (exact duplicate)
            if input_data.file_hash:
                existing = loop.run_until_complete(
                    repo.find_by_content_hash(input_data.file_hash, input_data.tenant_id)
                )
                if existing and str(existing.id) != input_data.document_id:
                    return DuplicateCheckOutput(
                        success=True, is_duplicate=True,
                        duplicate_document_id=str(existing.id),
                        duplicate_invoice_number=existing.invoice_number,
                        similarity_score=1.0,
                        detection_method="FILE_HASH",
                    )

            # Check by invoice number + vendor + amount
            existing = loop.run_until_complete(repo.find_duplicate(
                invoice_number=input_data.invoice_number,
                vendor_name=input_data.vendor_name,
                total_amount=input_data.total_amount,
                tenant_id=input_data.tenant_id,
                window_days=input_data.lookback_days,
            ))
            if existing and str(existing.id) != input_data.document_id:
                return DuplicateCheckOutput(
                    success=True, is_duplicate=True,
                    duplicate_document_id=str(existing.id),
                    duplicate_invoice_number=existing.invoice_number,
                    similarity_score=0.95,
                    detection_method="INVOICE_VENDOR_AMOUNT",
                )

            return DuplicateCheckOutput(success=True, is_duplicate=False)
        except Exception as exc:
            return DuplicateCheckOutput(
                success=False,
                error_code="DUPLICATE_CHECK_FAILED",
                error_message=str(exc),
            )
