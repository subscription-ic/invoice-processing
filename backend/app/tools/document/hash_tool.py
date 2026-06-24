"""HashTool — cryptographic hashing for file integrity and deduplication."""
from __future__ import annotations

import hashlib
from typing import ClassVar, Optional

from core.base.tool import BaseTool, ToolInput, ToolOutput


class HashInput(ToolInput):
    content: bytes
    document_id: Optional[str] = None
    algorithm: str = "sha256"


class HashOutput(ToolOutput):
    sha256: str
    md5: str
    size_bytes: int
    document_id: Optional[str] = None


class HashTool(BaseTool[HashInput, HashOutput]):
    name: ClassVar[str] = "hash"
    description: ClassVar[str] = "Compute SHA-256 and MD5 hashes of file content"
    input_model: ClassVar = HashInput
    output_model: ClassVar = HashOutput

    def _execute(self, input_data: HashInput) -> HashOutput:
        sha256 = hashlib.sha256(input_data.content).hexdigest()
        md5 = hashlib.md5(input_data.content).hexdigest()
        return HashOutput(
            success=True,
            sha256=sha256,
            md5=md5,
            size_bytes=len(input_data.content),
            document_id=input_data.document_id,
        )
