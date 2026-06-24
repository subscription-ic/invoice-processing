from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Tuple

from app.core.config import settings


ALLOWED_MIME_TYPES = {
    "pdf": ["application/pdf"],
    "jpg": ["image/jpeg"],
    "jpeg": ["image/jpeg"],
    "png": ["image/png"],
    "tiff": ["image/tiff"],
    "tif": ["image/tiff"],
    "docx": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
}

MAGIC_BYTES = {
    b"%PDF": "pdf",
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG": "png",
    b"II*\x00": "tiff",
    b"MM\x00*": "tiff",
    b"PK\x03\x04": "docx",
}


def detect_file_type_from_bytes(content: bytes) -> str | None:
    for magic, file_type in MAGIC_BYTES.items():
        if content.startswith(magic):
            return file_type
    return None


def validate_file(
    filename: str,
    content: bytes,
    declared_extension: str | None = None,
) -> Tuple[bool, str, dict]:
    """
    Validate an uploaded file.
    Returns (is_valid, error_message, metadata).
    """
    metadata = {}

    # Size check
    file_size = len(content)
    metadata["file_size"] = file_size
    if file_size == 0:
        return False, "File is empty", metadata
    if file_size > settings.max_upload_bytes:
        return False, f"File too large: {file_size/1024/1024:.1f}MB > {settings.MAX_UPLOAD_SIZE_MB}MB limit", metadata

    # Extension check
    ext = Path(filename).suffix.lstrip(".").lower()
    if not ext and declared_extension:
        ext = declared_extension.lower()
    metadata["detected_extension"] = ext

    if ext not in settings.allowed_extensions_list:
        return False, f"File type '{ext}' not allowed. Allowed: {settings.ALLOWED_EXTENSIONS}", metadata

    # Magic byte verification
    detected_type = detect_file_type_from_bytes(content)
    metadata["magic_detected_type"] = detected_type

    # Loose validation — warn but don't block if magic doesn't match for all formats
    if detected_type and detected_type != ext and ext in ("pdf", "jpeg", "jpg", "png"):
        if not (ext in ("jpg", "jpeg") and detected_type == "jpeg"):
            return False, f"File content ({detected_type}) does not match extension ({ext})", metadata

    # Compute checksum
    metadata["checksum"] = hashlib.sha256(content).hexdigest()

    # MIME type
    mime_type, _ = mimetypes.guess_type(filename)
    metadata["mime_type"] = mime_type or "application/octet-stream"

    return True, "", metadata