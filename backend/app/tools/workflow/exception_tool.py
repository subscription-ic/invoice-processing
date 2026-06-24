"""ExceptionTool — create and manage exception records for problem invoices."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class ExceptionInput(ToolInput):
    document_id: str
    exception_type: str
    severity: str = "MEDIUM"
    queue: str = "AP_TEAM"
    description: str = ""
    resolution_hint: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    agent_name: str = "system"
    tenant_id: str = "default"


class ExceptionOutput(ToolOutput):
    exception_id: Optional[str] = None
    queue_assigned: Optional[str] = None
    sla_hours: int = 24
    error_code: Optional[str] = None


_SLA_MAP = {
    "AP_TEAM": 4,
    "FINANCE": 8,
    "PROCUREMENT": 24,
    "COMPLIANCE": 48,
    "WAREHOUSE": 8,
}


class ExceptionTool(BaseTool[ExceptionInput, ExceptionOutput]):
    name: ClassVar[str] = "exception"
    description: ClassVar[str] = "Create an exception record and route to the appropriate queue"
    input_model: ClassVar = ExceptionInput
    output_model: ClassVar = ExceptionOutput

    def _execute(self, input_data: ExceptionInput) -> ExceptionOutput:
        exception_id = str(uuid.uuid4())
        sla_hours = _SLA_MAP.get(input_data.queue, 24)
        return ExceptionOutput(
            success=True,
            exception_id=exception_id,
            queue_assigned=input_data.queue,
            sla_hours=sla_hours,
        )


class RoutingInput(ToolInput):
    document_id: str
    match_status: Optional[str] = None
    confidence_band: Optional[str] = None
    amount: float = 0.0
    business_profile: Optional[str] = None
    validation_passed: bool = False
    has_exception: bool = False
    tenant_id: str = "default"


class RoutingOutput(ToolOutput):
    next_stage: str = "EXCEPTION"
    queue: Optional[str] = None
    reason: Optional[str] = None
    requires_human: bool = True


class RoutingTool(BaseTool[RoutingInput, RoutingOutput]):
    name: ClassVar[str] = "routing"
    description: ClassVar[str] = "Determine the next processing stage for a document"
    input_model: ClassVar = RoutingInput
    output_model: ClassVar = RoutingOutput

    def _execute(self, input_data: RoutingInput) -> RoutingOutput:
        if input_data.has_exception:
            return RoutingOutput(
                success=True, next_stage="EXCEPTION",
                queue="AP_TEAM", reason="Validation or matching exception",
                requires_human=True,
            )

        if input_data.match_status == "FULL_MATCH" and input_data.confidence_band == "HIGH":
            return RoutingOutput(
                success=True, next_stage="AUTO_APPROVE",
                reason="Full match with high confidence",
                requires_human=False,
            )

        if input_data.match_status in ("PARTIAL_MATCH", None) or input_data.confidence_band in ("MEDIUM", "LOW"):
            return RoutingOutput(
                success=True, next_stage="APPROVAL",
                queue="AP_TEAM", reason="Partial match or medium confidence",
                requires_human=True,
            )

        return RoutingOutput(
            success=True, next_stage="EXCEPTION",
            queue="FINANCE", reason="No match or low confidence",
            requires_human=True,
        )
