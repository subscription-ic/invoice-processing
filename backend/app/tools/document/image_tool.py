"""ImageTool — image quality assessment and pre-processing for OCR."""
from __future__ import annotations

import io
from typing import ClassVar, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class ImageProcessingInput(ToolInput):
    image_bytes: bytes
    document_id: Optional[str] = None
    page_number: int = 1
    apply_deskew: bool = True
    apply_denoise: bool = True
    apply_enhance_contrast: bool = True
    target_dpi: int = 300


class ImageProcessingOutput(ToolOutput):
    quality_score: float = 0.0
    quality_tier: str = "UNKNOWN"
    processed_image_bytes: Optional[bytes] = None
    original_image_bytes: Optional[bytes] = None
    detected_dpi: int = 0
    skew_angle_degrees: float = 0.0
    was_deskewed: bool = False
    was_denoised: bool = False
    was_contrast_enhanced: bool = False
    quality_issues: List[str] = []
    recommendation: Optional[str] = None
    error_code: Optional[str] = None


class ImageTool(BaseTool[ImageProcessingInput, ImageProcessingOutput]):
    name: ClassVar[str] = "image_processing"
    description: ClassVar[str] = "Assess and enhance document image quality for OCR"
    input_model: ClassVar = ImageProcessingInput
    output_model: ClassVar = ImageProcessingOutput

    def _execute(self, input_data: ImageProcessingInput) -> ImageProcessingOutput:
        try:
            from PIL import Image, ImageFilter, ImageOps
            import math

            img = Image.open(io.BytesIO(input_data.image_bytes)).convert("RGB")
            orig_bytes = input_data.image_bytes
            issues: List[str] = []
            was_deskewed = False
            was_denoised = False
            was_enhanced = False

            # Quality assessment
            quality_score, dpi_detected, page_issues = self._assess_quality(img)
            issues.extend(page_issues)

            # Enhancements
            if input_data.apply_enhance_contrast and quality_score < 0.7:
                img = ImageOps.autocontrast(img, cutoff=2)
                was_enhanced = True

            if input_data.apply_denoise and quality_score < 0.6:
                img = img.filter(ImageFilter.MedianFilter(size=3))
                was_denoised = True

            # Re-assess after enhancements
            if was_enhanced or was_denoised:
                quality_score, _, _ = self._assess_quality(img)

            if quality_score >= 0.75:
                tier = "HIGH"
            elif quality_score >= 0.5:
                tier = "MEDIUM"
            elif quality_score >= 0.3:
                tier = "LOW"
            else:
                tier = "UNUSABLE"

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            processed_bytes = buf.getvalue()

            recommendation = None
            if tier == "UNUSABLE":
                recommendation = "Request a higher quality scan; this image may produce unusable OCR output"
            elif tier == "LOW":
                recommendation = "Image quality is low; review OCR results manually"

            return ImageProcessingOutput(
                success=True,
                quality_score=quality_score,
                quality_tier=tier,
                processed_image_bytes=processed_bytes,
                original_image_bytes=orig_bytes,
                detected_dpi=dpi_detected,
                was_deskewed=was_deskewed,
                was_denoised=was_denoised,
                was_contrast_enhanced=was_enhanced,
                quality_issues=issues,
                recommendation=recommendation,
            )
        except Exception as exc:
            return ImageProcessingOutput(
                success=False,
                error_code="IMAGE_CORRUPTED",
                error_message=str(exc),
            )

    def _assess_quality(self, img):
        from PIL import Image
        import math

        issues = []
        scores = []

        # Brightness
        gray = img.convert("L")
        brightness = sum(gray.getdata()) / (gray.size[0] * gray.size[1])
        if brightness < 40:
            issues.append("Too dark")
            scores.append(0.2)
        elif brightness > 230:
            issues.append("Too bright/washed out")
            scores.append(0.4)
        else:
            scores.append(1.0)

        # Variance (sharpness proxy)
        import statistics
        pixels = list(gray.getdata())
        try:
            var = statistics.variance(pixels[:10000])
        except Exception:
            var = 0
        if var < 100:
            issues.append("Low contrast or blurry")
            scores.append(0.3)
        elif var > 5000:
            scores.append(1.0)
        else:
            scores.append(min(1.0, var / 5000))

        # Size
        w, h = img.size
        if w < 400 or h < 400:
            issues.append("Image too small")
            scores.append(0.2)
        else:
            scores.append(1.0)

        quality = sum(scores) / len(scores) if scores else 0.5
        return round(quality, 3), 72, issues  # DPI detection not trivial without EXIF
