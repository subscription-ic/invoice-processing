"""ConfidenceAgent — compute overall workflow confidence score and band."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from core.base.agent import BaseAgent
from core.state.workflow_state import WorkflowState


class ConfidenceAgent(BaseAgent):
    name: ClassVar[str] = "confidence_agent"

    def _execute(self, state: WorkflowState) -> WorkflowState:
        from app.tools.ai.confidence_tool import ConfidenceTool, ConfidenceInput
        from app.tools.workflow.audit_tool import AuditTool, AuditEventInput

        confidence_tool = ConfidenceTool()
        audit_tool = AuditTool()

        doc_id = state.workflow.document_id

        # Average extraction field confidences if present
        field_confs = state.extraction.field_confidences or {}
        extraction_conf = (
            sum(field_confs.values()) / len(field_confs) if field_confs else 0.0
        )

        result = confidence_tool.run(ConfidenceInput(
            ocr_confidence=state.ocr.avg_confidence or 0.0,
            extraction_confidence=extraction_conf,
            validation_passed=state.validation.is_valid or False,
            profile_confidence=state.profile.profile_confidence or 0.0,
            match_score=state.matching.three_way.overall_score or 0.0,
            document_id=doc_id,
        ))

        audit_tool.run(AuditEventInput(
            document_id=doc_id,
            entity_type="DOCUMENT",
            entity_id=doc_id,
            action="CONFIDENCE_SCORED",
            agent_name=self.name,
            after_state={"score": result.overall_score, "band": result.confidence_band},
            stage="CONFIDENCE_SCORING",
        ))

        return state.model_copy(deep=True, update={
            "confidence": state.confidence.model_copy(update={
                "overall_score": result.overall_score,
                "confidence_band": result.confidence_band,
                "component_scores": result.component_scores,
            }),
            "workflow": state.workflow.model_copy(update={
                "current_agent": self.name,
                "updated_at": datetime.now(timezone.utc),
            }),
        })
