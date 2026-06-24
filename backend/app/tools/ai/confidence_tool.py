"""ConfidenceTool — compute overall workflow confidence from component scores."""
from __future__ import annotations

from typing import ClassVar, Dict, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class ConfidenceInput(ToolInput):
    ocr_confidence: float = 0.0
    extraction_confidence: float = 0.0
    validation_pass: bool = False
    profile_confidence: float = 0.0
    match_score: float = 0.0
    tenant_id: str = "default"


class ConfidenceOutput(ToolOutput):
    overall_score: float = 0.0
    band: str = "LOW"
    component_scores: Dict[str, float] = {}
    recommendation: Optional[str] = None


class ConfidenceTool(BaseTool[ConfidenceInput, ConfidenceOutput]):
    name: ClassVar[str] = "confidence"
    description: ClassVar[str] = "Compute weighted overall confidence score from all processing steps"
    input_model: ClassVar = ConfidenceInput
    output_model: ClassVar = ConfidenceOutput

    def _execute(self, input_data: ConfidenceInput) -> ConfidenceOutput:
        from core.config.platform_config import get_platform_config

        cfg = get_platform_config().get_tenant_config(input_data.tenant_id).confidence
        weights = cfg.weights

        components = {
            "ocr_confidence": input_data.ocr_confidence,
            "extraction_confidence": input_data.extraction_confidence,
            "validation_pass": 1.0 if input_data.validation_pass else 0.0,
            "profile_confidence": input_data.profile_confidence,
            "match_score": input_data.match_score,
        }

        total_weight = sum(weights.get(k, 0.0) for k in components)
        if total_weight == 0:
            score = 0.0
        else:
            score = sum(
                v * weights.get(k, 0.0) for k, v in components.items()
            ) / total_weight

        score = round(max(0.0, min(1.0, score)), 4)

        if score >= cfg.high_band_threshold:
            band = "HIGH"
        elif score >= cfg.medium_band_threshold:
            band = "MEDIUM"
        elif score >= cfg.low_band_threshold:
            band = "LOW"
        else:
            band = "VERY_LOW"

        recommendations = {
            "HIGH": None,
            "MEDIUM": "Review extracted fields before approval",
            "LOW": "Manual review recommended",
            "VERY_LOW": "Send to exception queue — confidence too low for automated processing",
        }

        return ConfidenceOutput(
            success=True,
            overall_score=score,
            band=band,
            component_scores=components,
            recommendation=recommendations[band],
        )
