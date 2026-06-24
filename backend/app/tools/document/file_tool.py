"""
FileTool — validates uploaded files before any downstream processing.

Detects true MIME type via magic bytes, enforces size limits,
checks for password protection and corruption.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import ClassVar, List, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


_MAGIC = {
    b"%PDF": ("application/pdf", ".pdf"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"\x89PNG": ("image/png", ".png"),
    b"II*\x00": ("image/tiff", ".tiff"),
    b"MM\x00*": ("image/tiff", ".tiff"),
    b"PK\x03\x04": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
}

_ALLOWED_MIMES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class FileValidationInput(ToolInput):
    file_bytes: bytes
    filename: str
    declared_mime: Optional[str] = None
    tenant_id: str = "default"


class FileValidationOutput(ToolOutput):
    is_valid: bool
    detected_mime: Optional[str]
    canonical_extension: Optional[str]
    size_bytes: int
    is_password_protected: bool = False
    is_corrupted: bool = False
    sha256: Optional[str] = None
    error_code: Optional[str] = None
    recommendation: Optional[str] = None


class FileTool(BaseTool[FileValidationInput, FileValidationOutput]):
    name: ClassVar[str] = "file_validation"
    description: ClassVar[str] = "Validate file format, size, and integrity before processing"
    input_model: ClassVar = FileValidationInput
    output_model: ClassVar = FileValidationOutput

    def __init__(self, max_size_bytes: int = 52_428_800, **kwargs):
        super().__init__(**kwargs)
        self._max_size_bytes = max_size_bytes

    def _execute(self, input_data: FileValidationInput) -> FileValidationOutput:
        content = input_data.file_bytes
        size = len(content)

        if size == 0:
            return FileValidationOutput(
                success=False, is_valid=False,
                detected_mime=None, canonical_extension=None, size_bytes=0,
                error_code="EMPTY_FILE", error_message="File is empty",
                recommendation="Upload a non-empty file",
            )

        if size > self._max_size_bytes:
            return FileValidationOutput(
                success=False, is_valid=False,
                detected_mime=None, canonical_extension=None, size_bytes=size,
                error_code="FILE_TOO_LARGE",
                error_message=f"File {size/1024/1024:.1f}MB exceeds {self._max_size_bytes/1024/1024:.0f}MB limit",
                recommendation="Upload a smaller file or split into multiple documents",
            )

        detected_mime, canonical_ext = self._detect_mime(content)

        if detected_mime is None or detected_mime not in _ALLOWED_MIMES:
            return FileValidationOutput(
                success=False, is_valid=False,
                detected_mime=detected_mime, canonical_extension=canonical_ext, size_bytes=size,
                error_code="UNSUPPORTED_TYPE",
                error_message=f"File type '{detected_mime}' is not supported",
                recommendation="Upload a PDF, JPG, PNG, TIFF, or DOCX file",
            )

        is_password_protected = False
        is_corrupted = False

        if detected_mime == "application/pdf":
            is_password_protected, is_corrupted = self._inspect_pdf(content)
            if is_corrupted:
                return FileValidationOutput(
                    success=False, is_valid=False,
                    detected_mime=detected_mime, canonical_extension=canonical_ext, size_bytes=size,
                    is_corrupted=True,
                    error_code="CORRUPTED", error_message="PDF file appears to be corrupted",
                    recommendation="Request the sender to re-send the document",
                )
            if is_password_protected:
                return FileValidationOutput(
                    success=False, is_valid=False,
                    detected_mime=detected_mime, canonical_extension=canonical_ext, size_bytes=size,
                    is_password_protected=True,
                    error_code="PASSWORD_PROTECTED", error_message="PDF is password-protected",
                    recommendation="Remove password protection before uploading",
                )

        sha256 = hashlib.sha256(content).hexdigest()
        return FileValidationOutput(
            success=True, is_valid=True,
            detected_mime=detected_mime, canonical_extension=canonical_ext,
            size_bytes=size, sha256=sha256,
        )

    def _detect_mime(self, content: bytes):
        header = content[:16]
        for magic, (mime, ext) in _MAGIC.items():
            if header.startswith(magic):
                return mime, ext
        return None, None

    def _inspect_pdf(self, content: bytes):
        try:
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            is_encrypted = doc.is_encrypted
            doc.close()
            if is_encrypted:
                return True, False
            return False, False
        except Exception:
            return False, True
