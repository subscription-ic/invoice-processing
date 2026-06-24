"""ThumbnailTool — generate thumbnail previews of document pages."""
from __future__ import annotations

import io
from typing import ClassVar, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class ThumbnailInput(ToolInput):
    image_bytes: bytes
    document_id: str
    page_number: int = 1
    width: int = 200
    height: int = 280


class ThumbnailOutput(ToolOutput):
    thumbnail_bytes: Optional[bytes] = None
    width: int = 0
    height: int = 0
    error_code: Optional[str] = None


class ThumbnailTool(BaseTool[ThumbnailInput, ThumbnailOutput]):
    name: ClassVar[str] = "thumbnail"
    description: ClassVar[str] = "Generate thumbnail images for document preview"
    input_model: ClassVar = ThumbnailInput
    output_model: ClassVar = ThumbnailOutput

    def _execute(self, input_data: ThumbnailInput) -> ThumbnailOutput:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(input_data.image_bytes)).convert("RGB")
            img.thumbnail((input_data.width, input_data.height), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return ThumbnailOutput(
                success=True,
                thumbnail_bytes=buf.getvalue(),
                width=img.width,
                height=img.height,
            )
        except Exception as exc:
            return ThumbnailOutput(success=False, error_code="THUMBNAIL_FAILED", error_message=str(exc))
