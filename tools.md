# AI Agent Platform — Reusable Tool Layer Specification

**Version:** 1.0.0
**Status:** Design Phase — Engineering Specification
**Source of Truth:** ARCHITECTURE.md
**Date:** 2026-06-09
**Classification:** Internal Engineering Reference

---

## TABLE OF CONTENTS

1. Overall Tool Architecture
2. Tool Categories
3. Tool Specifications (per category)
   - Document Tools
   - OCR Tools
   - AI Tools
   - Validation Tools
   - Matching Tools
   - ERP Tools
   - Workflow Tools
   - Storage Tools
   - Prompt Tools
   - Configuration Tools
   - Security Tools
4. Tool Dependency Matrix
5. Tool Usage Matrix (Agents × Tools)
6. Future Extensibility
7. Engineering Best Practices

---

## SECTION 1 — Overall Tool Architecture

### 1.1 What Is a Tool?

A **Tool** is the smallest independently deployable unit of business logic in the platform. It is a pure, stateless service class that accepts a typed input model, performs exactly one business operation, and returns a typed output model.

Tools are the only place in the platform where business logic is permitted to exist. Agents are forbidden from containing business logic. Graphs are forbidden from containing business logic. FastAPI routers are forbidden from containing business logic. The Tool Layer is the exclusive home of every rule, calculation, transformation, and decision the platform makes.

A Tool is NOT:
- A LangGraph node
- A FastAPI route handler
- A database model
- An agent
- A workflow state manager

A Tool IS:
- A stateless, injectable service
- A single-responsibility business operation
- A reusable component that knows nothing about invoices specifically
- A testable unit with clear inputs and outputs
- A provider-agnostic interface when it touches external services

### 1.2 Why Tools Instead of Business Logic Inside Agents?

The central architectural argument is **replaceability and testability**.

If business logic lives inside an Agent, then:
- You cannot test the logic without executing the graph
- You cannot reuse the logic in a different agent or project
- You cannot replace the agent without rewriting the logic
- You cannot version the logic independently
- You cannot swap providers (OCR, LLM, ERP) without touching agent code

If business logic lives inside a Tool, then:
- Every rule can be unit-tested with a single function call
- The same tool can be used by multiple agents
- The same tool can be used in a completely different AI project
- Agents become thin orchestrators — easy to read, easy to replace
- Provider swapping is a configuration change, not a code change

The 80/20 reusability goal of the platform is ONLY achievable if tools contain all logic and agents contain none.

### 1.3 Tool Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          TOOL EXECUTION LIFECYCLE                           │
│                                                                             │
│  1. INSTANTIATION                                                           │
│     Tool is constructed with injected dependencies                         │
│     (LLM client, repository, config, logger — never hardcoded)             │
│                                                                             │
│  2. INPUT VALIDATION                                                        │
│     Input model is validated by Pydantic before execute() is called        │
│     Invalid inputs raise ToolInputValidationError immediately               │
│                                                                             │
│  3. PRE-EXECUTION LOGGING                                                   │
│     Tool logs: tool_name, input_hash, correlation_id, timestamp            │
│                                                                             │
│  4. EXECUTION                                                               │
│     Business logic runs against validated inputs                            │
│     External calls go through injected providers, never direct imports     │
│                                                                             │
│  5. OUTPUT ASSEMBLY                                                         │
│     Result is assembled into a typed output model                          │
│     Confidence score is calculated where applicable                        │
│                                                                             │
│  6. POST-EXECUTION LOGGING                                                  │
│     Tool logs: duration_ms, result_status, output_hash, tokens (if LLM)    │
│                                                                             │
│  7. AUDIT EVENT (where applicable)                                          │
│     Compliance-relevant tools write an immutable audit event               │
│                                                                             │
│  8. RETURN                                                                  │
│     Typed output model returned to calling Agent                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.4 Tool Dependency Rules

The following rules govern how tools may depend on each other and on external services.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TOOL DEPENDENCY RULES                               │
│                                                                             │
│  ALLOWED                                                                    │
│  ✓ Tool → Repository (via injected interface)                              │
│  ✓ Tool → LLMService (via injected interface)                              │
│  ✓ Tool → StorageService (via injected interface)                          │
│  ✓ Tool → ConfigurationTool (for reading config values)                    │
│  ✓ Tool → LoggingTool (for structured logging)                             │
│  ✓ Tool → AuditTool (for writing audit events)                             │
│  ✓ Tool → RetryTool (for retry execution)                                  │
│  ✓ Utility Tool → stdlib / pure Python libraries                           │
│                                                                             │
│  FORBIDDEN                                                                  │
│  ✗ Tool → Agent                                                            │
│  ✗ Tool → LangGraph Graph                                                  │
│  ✗ Tool → FastAPI router or request context                                │
│  ✗ Tool → SQLAlchemy model directly (must use Repository)                  │
│  ✗ Tool → Another Tool of the same category (prevents circular deps)       │
│  ✗ Tool → Hardcoded provider (openai, tesseract) — always via interface    │
│  ✗ Tool → UI or frontend logic                                             │
│  ✗ Tool → HTTP client unless it IS a provider adapter                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.5 Tool Composition

Agents compose tools sequentially. Tools do not call each other (with the exception of Platform Tools: ConfigurationTool, LoggingTool, AuditTool, RetryTool which are infrastructure concerns).

```
Agent.execute(state):
  step_1_result = FileTool.validate(input)
  step_2_result = StorageTool.upload(step_1_result.path)
  step_3_result = HashTool.compute(step_2_result.blob_path)
  state.document.sha256 = step_3_result.sha256
  return state
```

This means:
- Each tool call is independently observable in logs
- Any tool can be mocked in tests without affecting others
- Tool call order is explicit in the agent — no hidden dependencies
- Failures are localized to a single tool call

### 1.6 Error Handling Contract

Every tool must adhere to this error contract:

```
ToolResult (every output model inherits from this):
  success: bool
  error_code: str | None          # machine-readable e.g. "GST_FORMAT_INVALID"
  error_message: str | None       # human-readable explanation
  error_severity: enum | None     # CRITICAL / HIGH / MEDIUM / LOW / INFO
  error_evidence: dict | None     # the raw data that caused the failure
  recommendation: str | None      # what to do next
```

Tools NEVER raise unhandled exceptions to agents. Every exception is caught, converted into a ToolResult with `success=False`, and returned. The Agent decides whether to escalate to an exception, retry, or continue.

The only exceptions to this rule are:
- `ToolInputValidationError` — raised before execute() for malformed inputs
- `ToolConfigurationError` — raised at instantiation if required config is missing

### 1.7 Retry Strategy

Tools do not implement their own retry loops. Retry logic is delegated to `RetryTool`, which is injected and called by the agent. This prevents nested retry logic and keeps retry configuration centralised.

```
RetryTool.execute(
  func        = lambda: ocr_tool.extract_text(image),
  max_retries = config.get("ocr.max_retries", 3),
  backoff     = "exponential",
  base_delay  = 1.0,
  retryable_on = [OCRProviderTimeoutError, OCRProviderRateLimitError]
)
```

### 1.8 Logging Contract

Every tool emits a structured `ToolExecutionLog` automatically via `LoggingTool`:

```
ToolExecutionLog:
  tool_name: str
  method_called: str
  workflow_id: UUID | None
  document_id: UUID | None
  correlation_id: str
  started_at: datetime
  completed_at: datetime
  duration_ms: int
  success: bool
  input_hash: str           # SHA-256 of serialised input (for dedup/debug)
  output_hash: str          # SHA-256 of serialised output
  error_code: str | None
  llm_tokens_used: int | None
  provider_used: str | None
  confidence: float | None
  metadata: dict
```

### 1.9 Audit Contract

Tools that make compliance-relevant decisions (validation, matching, approval, ERP posting, exception creation, payment) MUST write an `AuditEvent` via `AuditTool`. The event is immutable once written.

### 1.10 Configuration Contract

Every tool reads configuration via the injected `ConfigurationTool`. Configuration is NEVER hardcoded. Every threshold, rate, timeout, model name, provider name, and flag comes from config. The tool specifies a config namespace: e.g. `ocr.confidence_threshold`, `validation.gst.strict_mode`.

### 1.11 Dependency Injection Contract

All tools receive their dependencies through constructor injection. No tool imports a concrete implementation. This is enforced by:
- Defining provider interfaces in `app/services/`
- Injecting concrete providers through FastAPI's dependency injection system
- All tests supply mock implementations of the same interfaces

### 1.12 Testing Contract

Every tool must have a corresponding test file at `tests/unit/tools/test_{tool_name}.py`. The test must:
- Test the happy path with valid inputs
- Test every failure mode with invalid/edge-case inputs
- Test configuration boundary values (thresholds, tolerances)
- Never require a running database, OCR engine, or LLM
- Never require LangGraph or any agent
- Run in under 1 second per test case

### 1.13 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              TOOL LAYER                                         │
│                                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  DOCUMENT    │  │  OCR         │  │  AI / LLM    │  │  VALIDATION      │   │
│  │  TOOLS       │  │  TOOLS       │  │  TOOLS       │  │  TOOLS           │   │
│  │              │  │              │  │              │  │                  │   │
│  │  FileTool    │  │  OCRTool     │  │  LLMTool     │  │  ValidationTool  │   │
│  │  StorageTool │  │  Tesseract   │  │  PromptTool  │  │  GSTTool         │   │
│  │  PDFTool     │  │  AzureOCR    │  │  Extraction  │  │  ArithmeticTool  │   │
│  │  ImageTool   │  │  Confidence  │  │  Classif.    │  │  DuplicateTool   │   │
│  │  HashTool    │  │  Deskew      │  │  Confidence  │  │  BusinessRule    │   │
│  │  VirusScan   │  │  Enhancement │  │  Normaliz.   │  │  ProfileValidat. │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └───────┬──────────┘   │
│         │                 │                  │                  │              │
│  ┌──────▼───────┐  ┌──────▼───────┐  ┌──────▼───────┐  ┌──────▼──────────┐   │
│  │  MATCHING    │  │  ERP         │  │  WORKFLOW    │  │  STORAGE         │   │
│  │  TOOLS       │  │  TOOLS       │  │  TOOLS       │  │  TOOLS           │   │
│  │              │  │              │  │              │  │                  │   │
│  │  VendorMatch │  │  ERPAdapter  │  │  WorkflowSt. │  │  LocalStorage    │   │
│  │  POMatching  │  │  MockERP     │  │  QueueTool   │  │  AzureBlob       │   │
│  │  GRNMatching │  │  SAPAdapter  │  │  RetryTool   │  │  DocVersion      │   │
│  │  ThreeWay    │  │  JournalBld  │  │  ApprovalTl  │  │  ArchiveTool     │   │
│  │  Similarity  │  │  PaymentSch  │  │  AuditTool   │  │                  │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └───────┬──────────┘   │
│         │                 │                  │                  │              │
│  ┌──────▼─────────────────▼──────────────────▼──────────────────▼──────────┐   │
│  │                    PLATFORM INFRASTRUCTURE TOOLS                        │   │
│  │  ConfigurationTool · LoggingTool · AuditTool · RetryTool               │   │
│  │  PromptRegistryTool · EncryptionTool · AuthorizationTool               │   │
│  └───────────────────────────────────────────────────────────────────────-─┘   │
│                                    │                                           │
│  ┌─────────────────────────────────▼───────────────────────────────────────┐   │
│  │              INJECTED INTERFACES (never concrete classes)               │   │
│  │  LLMServiceInterface · OCRProviderInterface · StorageProviderInterface  │   │
│  │  ERPProviderInterface · NotificationProviderInterface                   │   │
│  │  RepositoryInterface (per aggregate) · QueueProviderInterface           │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## SECTION 2 — Tool Categories

### Category Summary Table

| # | Category | Tool Count | Primary Concern | Reusable Beyond AP? |
|---|---|---|---|---|
| 1 | Document Tools | 12 | File handling, storage, integrity | Yes — any document pipeline |
| 2 | OCR Tools | 14 | Text extraction from images | Yes — any OCR pipeline |
| 3 | AI / LLM Tools | 11 | LLM calls, extraction, classification | Yes — any AI pipeline |
| 4 | Validation Tools | 14 | Business rule enforcement | Yes — any data validation |
| 5 | Matching Tools | 10 | Record comparison and matching | Yes — any reconciliation |
| 6 | ERP Tools | 14 | ERP integration abstraction | Yes — any finance system |
| 7 | Workflow Tools | 13 | State, queue, approval, exception | Yes — any workflow engine |
| 8 | Storage Tools | 6 | File persistence and versioning | Yes — any file platform |
| 9 | Prompt Tools | 6 | LLM prompt management | Yes — any AI platform |
| 10 | Configuration Tools | 6 | Runtime configuration | Yes — any enterprise app |
| 11 | Security Tools | 6 | Auth, encryption, masking | Yes — any enterprise app |
| **Total** | | **112** | | |

### Dependency Hierarchy

```
Level 0 (no tool deps):  ConfigurationTool, LoggingTool, HashTool, EncryptionTool
Level 1 (deps on L0):    FileTool, StorageTool, AuditTool, RetryTool, AuthorizationTool
Level 2 (deps on L1):    PDFTool, ImageTool, OCRTool, PromptTool, ValidationTool
Level 3 (deps on L2):    ExtractionTool, MatchingTool, GSTTool, VendorMatchingTool
Level 4 (deps on L3):    ThreeWayMatchingTool, BusinessProfileTool, ERPAdapterTool
Level 5 (deps on L4):    PostingTool, PaymentScheduleTool, ApprovalTool
```

No circular dependencies exist. Higher levels depend only on lower levels.

---

## SECTION 3 — Tool Specifications

---

# DOCUMENT TOOLS

---

## Tool: FileTool

**Category:** Document
**File:** `app/tools/document/file_tool.py`

### Description
Validates, inspects, and classifies uploaded files before any downstream processing. Acts as the first line of defence — no other tool processes a file that has not passed FileTool validation.

### Purpose
Ensure that files entering the platform are of an accepted format, size, and structure. This is provider-agnostic and reusable in any document intake pipeline.

### Responsibilities
- Detect the true MIME type of a file (not just extension — reads magic bytes)
- Validate the file against the platform's allowlist of accepted types
- Enforce configurable file size limits
- Detect if the file is password-protected or corrupted
- Normalise the file extension to a canonical form

### MUST Do
- Read the first 512 bytes (magic bytes) to determine true MIME type
- Reject files whose MIME type does not match their declared extension
- Enforce the `file.max_size_bytes` configuration value
- Return a `FileValidationResult` regardless of success or failure

### MUST NEVER Do
- Move, copy, or store the file (that is StorageTool's responsibility)
- Call any OCR or LLM service
- Modify the file content
- Make network calls

### Input Model
```
FileValidationInput:
  file_path: str          # absolute local path to the uploaded file
  declared_mime: str      # MIME type declared by the upload client
  declared_size_bytes: int
  tenant_id: str
```

### Output Model
```
FileValidationResult:
  success: bool
  is_valid: bool
  detected_mime: str
  canonical_extension: str   # .pdf, .png, .jpg, .tiff
  size_bytes: int
  is_password_protected: bool
  is_corrupted: bool
  error_code: str | None     # FILE_TOO_LARGE, UNSUPPORTED_TYPE, MIME_MISMATCH, CORRUPTED
  error_message: str | None
  recommendation: str | None
```

### Public Methods
| Method | Input | Output | Description |
|---|---|---|---|
| `validate(input)` | `FileValidationInput` | `FileValidationResult` | Full validation pipeline |
| `detect_mime_type(path)` | `str` | `str` | Returns detected MIME type |
| `is_format_allowed(mime)` | `str` | `bool` | Checks against allowlist |
| `check_size(path, limit)` | `str, int` | `bool` | Validates against size limit |
| `is_pdf_corrupted(path)` | `str` | `bool` | PyMuPDF corruption check |
| `is_password_protected(path)` | `str` | `bool` | Checks PDF encryption flag |

### Internal Helpers
- `_read_magic_bytes(path)` — reads first 512 bytes for MIME detection
- `_normalise_extension(mime)` — maps MIME to canonical extension

### Dependencies
- `python-magic` — magic byte MIME detection
- `PyMuPDF` — PDF structure inspection
- `ConfigurationTool` — reads `file.allowed_mimes`, `file.max_size_bytes`
- `LoggingTool` — structured execution log

### Configuration
| Key | Default | Description |
|---|---|---|
| `file.allowed_mimes` | `[application/pdf, image/png, image/jpeg, image/tiff]` | Accepted MIME types |
| `file.max_size_bytes` | `52428800` (50 MB) | Maximum upload size |
| `file.reject_password_protected` | `true` | Reject encrypted PDFs |

### Error Handling
| Error Code | Condition | Severity |
|---|---|---|
| `FILE_TOO_LARGE` | File exceeds size limit | HIGH |
| `UNSUPPORTED_TYPE` | MIME not in allowlist | HIGH |
| `MIME_MISMATCH` | Declared ≠ detected MIME | MEDIUM |
| `CORRUPTED` | File cannot be read | CRITICAL |
| `PASSWORD_PROTECTED` | PDF is encrypted | HIGH |

### Retry Strategy
No retry — deterministic, no external calls.

### Logging
- Logs: file_path (basename only, never full path for security), detected_mime, size_bytes, is_valid, duration_ms

### Audit Events
None — file validation is not a compliance event.

### Performance Considerations
- Magic byte read is O(1) — reads only 512 bytes regardless of file size
- Target: under 50ms for any file size

### Future Extensions
- Microsoft Office DOCX/XLSX support for future invoice formats
- EDI file format validation (X12, EDIFACT)
- ZIP/archive extraction for bulk uploads

### Used By
| Agent | Graph |
|---|---|
| UploadAgent | InvoiceProcessingGraph |

---

## Tool: StorageTool

**Category:** Document
**File:** `app/tools/document/storage_tool.py`

### Description
Provider-agnostic file storage abstraction. Delegates to the injected `StorageProviderInterface` — either `LocalStorageProvider` (development) or `AzureBlobStorageProvider` (production). No agent, graph, or other tool knows which provider is active.

### Purpose
Decouple all file I/O from specific storage infrastructure. Agents call `StorageTool` — never Azure SDK or local `os.path` directly.

### Responsibilities
- Upload validated files to the configured storage backend
- Generate stable, non-expiring content-addressed paths
- Generate time-limited secure download URLs (SAS URLs on Azure)
- Delete files on quarantine or rejection
- Check file existence before processing

### MUST Do
- Accept the injected `StorageProviderInterface` — never import Azure SDK directly
- Store files at a deterministic path: `{tenant_id}/{year}/{month}/{document_id}/{filename}`
- Return the canonical storage path and a time-limited access URL
- Log upload size, duration, and provider used

### MUST NEVER Do
- Compress or modify file content
- Read file content (that is PDFTool/ImageTool's responsibility)
- Perform validation (that is FileTool's responsibility)
- Store files without a document_id — every file must be traceable

### Input Models
```
StorageUploadInput:
  local_path: str
  document_id: UUID
  tenant_id: str
  original_filename: str
  content_type: str

StorageDownloadInput:
  storage_path: str
  tenant_id: str
  expiry_seconds: int = 3600

StorageDeleteInput:
  storage_path: str
  tenant_id: str
  reason: str           # "QUARANTINE" | "REJECTED" | "EXPIRED"
```

### Output Models
```
StorageUploadResult:
  success: bool
  storage_path: str       # canonical path in storage backend
  access_url: str         # time-limited download URL
  size_bytes: int
  provider: str           # "local" | "azure_blob"
  error_code: str | None

StorageDownloadResult:
  success: bool
  local_path: str
  size_bytes: int
  error_code: str | None

StorageDeleteResult:
  success: bool
  deleted_path: str
  error_code: str | None
```

### Public Methods
| Method | Input | Output |
|---|---|---|
| `upload(input)` | `StorageUploadInput` | `StorageUploadResult` |
| `download(input)` | `StorageDownloadInput` | `StorageDownloadResult` |
| `delete(input)` | `StorageDeleteInput` | `StorageDeleteResult` |
| `exists(path, tenant_id)` | `str, str` | `bool` |
| `get_access_url(path, expiry)` | `str, int` | `str` |

### Internal Helpers
- `_build_storage_path(tenant_id, document_id, filename)` — builds deterministic path

### Dependencies
- `StorageProviderInterface` — injected (LocalProvider or AzureBlobProvider)
- `ConfigurationTool` — reads `storage.provider`, `storage.container_name`
- `LoggingTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `storage.provider` | `azure_blob` | Active provider |
| `storage.container_name` | `ap-documents` | Blob container name |
| `storage.url_expiry_seconds` | `3600` | SAS URL lifetime |
| `storage.path_template` | `{tenant}/{year}/{month}/{doc_id}/{file}` | Path pattern |

### Error Handling
| Error Code | Condition |
|---|---|
| `UPLOAD_FAILED` | Provider write error |
| `FILE_NOT_FOUND` | Path does not exist |
| `DOWNLOAD_FAILED` | Provider read error |
| `DELETE_FAILED` | Provider delete error |

### Retry Strategy
`RetryTool` with max 3 retries, exponential backoff. Retryable on: `StorageProviderTimeoutError`, `StorageProviderRateLimitError`.

### Audit Events
| Event | Trigger |
|---|---|
| `DOCUMENT_STORED` | Successful upload |
| `DOCUMENT_DELETED` | File deleted with reason |

### Performance Considerations
- Upload is async-compatible — does not block the event loop
- Azure Blob: use block upload for files > 4MB

### Future Extensions
- AWS S3 provider
- Google Cloud Storage provider
- Content-Addressed Storage (CAS) for deduplication

### Used By
| Agent | Graph |
|---|---|
| UploadAgent | InvoiceProcessingGraph |
| ERPPostingAgent | InvoiceProcessingGraph |

---

## Tool: PDFTool

**Category:** Document
**File:** `app/tools/document/pdf_tool.py`

### Description
Extracts pages, embedded images, text layers, and structural metadata from PDF files. Determines whether a PDF is digitally native (has selectable text) or a scanned image (text is in raster images only).

### Purpose
Prepare PDF documents for downstream OCR or direct text extraction. Provide page images to ImageTool and OCRTool. Determine the correct processing path.

### Responsibilities
- Render each PDF page as a high-resolution image (300 DPI minimum)
- Detect whether the PDF contains a native text layer
- Extract embedded images from PDF pages
- Extract PDF metadata (author, creation date, software used)
- Report page count and page dimensions

### MUST Do
- Render pages at configurable DPI (minimum 300 for OCR quality)
- Detect native text layer presence per page
- Return pages as `bytes` objects (PNG format)
- Gracefully handle multi-page documents

### MUST NEVER Do
- Modify the original PDF
- Make network calls
- Perform OCR (that is OCRTool's responsibility)
- Access storage (pages are passed as bytes, not stored paths)

### Input Model
```
PDFExtractionInput:
  file_bytes: bytes         # PDF file content
  document_id: UUID
  render_dpi: int = 300
  extract_images: bool = True
  extract_metadata: bool = True
```

### Output Model
```
PDFExtractionResult:
  success: bool
  page_count: int
  has_native_text: bool           # True = DIGITAL, False = SCANNED
  pages: List[PDFPage]
  metadata: PDFMetadata
  error_code: str | None

PDFPage:
  page_number: int
  image_bytes: bytes              # PNG render at requested DPI
  width_px: int
  height_px: int
  has_text_layer: bool
  embedded_images: List[bytes]
  native_text: str | None         # if has_text_layer is True

PDFMetadata:
  author: str | None
  creator_software: str | None
  creation_date: datetime | None
  modification_date: datetime | None
  is_encrypted: bool
  pdf_version: str
```

### Public Methods
| Method | Description |
|---|---|
| `extract(input)` | Full extraction: pages + metadata |
| `render_page(page_index, dpi)` | Render single page as PNG bytes |
| `has_text_layer(page_index)` | Check if page has selectable text |
| `extract_metadata()` | Extract PDF document metadata |
| `get_page_count()` | Return page count without full extraction |

### Dependencies
- `PyMuPDF (fitz)` — PDF rendering and text extraction
- `ConfigurationTool` — reads `pdf.render_dpi`, `pdf.max_pages`
- `LoggingTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `pdf.render_dpi` | `300` | Page render resolution |
| `pdf.max_pages` | `50` | Maximum pages to process |
| `pdf.extract_embedded_images` | `true` | Whether to extract inline images |

### Error Handling
| Error Code | Condition |
|---|---|
| `PDF_CORRUPTED` | File cannot be opened by PyMuPDF |
| `PDF_ENCRYPTED` | Password-protected (should be caught by FileTool) |
| `PDF_TOO_MANY_PAGES` | Exceeds `pdf.max_pages` config |
| `PAGE_RENDER_FAILED` | Single page render failure |

### Performance Considerations
- Render only pages needed — lazy loading for large documents
- Target: under 200ms per page at 300 DPI

### Future Extensions
- PDF/A compliance validation
- Digital signature extraction and verification
- Form field extraction (for structured invoice forms)
- Searchable PDF creation from OCR results

### Used By
| Agent | Graph |
|---|---|
| ClassificationAgent | InvoiceProcessingGraph |
| OCRAgent | InvoiceProcessingGraph |

---

## Tool: ImageTool

**Category:** Document
**File:** `app/tools/document/image_tool.py`

### Description
Assesses image quality and performs pre-processing to maximise OCR accuracy. Takes raw page images from PDFTool or direct image uploads and returns optimised images suitable for OCR engines.

### Purpose
Improve OCR quality by correcting common image problems (skew, noise, low contrast, low DPI) before text extraction. Reusable in any image processing pipeline.

### Responsibilities
- Assess image quality and produce a quality score
- Detect and correct skew (deskewing)
- Remove noise (denoising)
- Enhance contrast for low-contrast documents
- Detect and correct page orientation (0°, 90°, 180°, 270°)
- Resize to target DPI if below minimum

### MUST Do
- Return the original image if no enhancement is needed (avoid unnecessary transforms)
- Report a quality score between 0.0 and 1.0
- List all quality issues detected in the output
- Return both the processed image AND the original

### MUST NEVER Do
- Crop or alter document boundaries beyond deskew margin
- Perform OCR
- Store images — return as bytes only

### Input Model
```
ImageProcessingInput:
  image_bytes: bytes
  document_id: UUID
  page_number: int
  apply_deskew: bool = True
  apply_denoise: bool = True
  apply_enhance_contrast: bool = True
  target_dpi: int = 300
```

### Output Model
```
ImageProcessingResult:
  success: bool
  quality_score: float              # 0.0 (unusable) to 1.0 (perfect)
  quality_tier: str                 # HIGH / MEDIUM / LOW / UNUSABLE
  processed_image_bytes: bytes
  original_image_bytes: bytes
  detected_dpi: int
  skew_angle_degrees: float
  was_deskewed: bool
  was_denoised: bool
  was_contrast_enhanced: bool
  quality_issues: List[str]         # human-readable list of detected issues
  recommendation: str | None        # e.g. "Request higher quality scan"
```

### Public Methods
| Method | Description |
|---|---|
| `process(input)` | Full processing pipeline |
| `assess_quality(image_bytes)` | Returns quality score and issues |
| `deskew(image_bytes)` | Correct skew angle |
| `denoise(image_bytes)` | Remove noise |
| `enhance_contrast(image_bytes)` | CLAHE contrast enhancement |
| `detect_orientation(image_bytes)` | Detect 90°/180°/270° rotation |
| `correct_orientation(image_bytes)` | Auto-correct orientation |

### Dependencies
- `OpenCV` — all image processing operations
- `Pillow` — format conversion
- `ConfigurationTool` — reads `image.quality_threshold`, `image.min_dpi`
- `LoggingTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `image.quality_threshold.high` | `0.75` | Score above which = HIGH tier |
| `image.quality_threshold.medium` | `0.50` | Score above which = MEDIUM tier |
| `image.quality_threshold.low` | `0.30` | Score above which = LOW tier |
| `image.min_dpi` | `150` | Minimum acceptable DPI |
| `image.denoise_strength` | `10` | OpenCV fastNlMeansDenoising h parameter |

### Error Handling
| Error Code | Condition |
|---|---|
| `IMAGE_CORRUPTED` | Cannot decode image bytes |
| `IMAGE_TOO_SMALL` | Below minimum dimensions for OCR |
| `UNSUPPORTED_FORMAT` | Not PNG/JPEG/TIFF |

### Performance Considerations
- Deskew is the most expensive operation — skip if skew < 0.5°
- Target: under 300ms per page

### Future Extensions
- Barcode and QR code region detection (for routing to BarcodeTool)
- Stamp and signature region detection
- Table region detection (for TableExtractionTool pre-processing)

### Used By
| Agent | Graph |
|---|---|
| ClassificationAgent | InvoiceProcessingGraph |
| OCRAgent | InvoiceProcessingGraph |

---

## Tool: MetadataTool

**Category:** Document
**File:** `app/tools/document/metadata_tool.py`

### Description
Extracts, normalises, and enriches document metadata from PDF properties, image EXIF data, and file system attributes. Metadata is stored in WorkflowState and used for audit trails and duplicate detection.

### Purpose
Build a rich metadata record for every document entering the platform. Metadata supports deduplication, audit, provenance tracking, and compliance reporting.

### Responsibilities
- Extract PDF document properties (author, creator, dates)
- Extract image EXIF metadata (camera, GPS, capture date)
- Normalise all dates to ISO 8601 UTC
- Detect the software that created the PDF (useful for identifying invoice generators)
- Estimate document age from metadata dates

### MUST Do
- Return a result even if metadata is sparse (many fields nullable)
- Normalise all timezone-aware dates to UTC
- Sanitise metadata values — strip null bytes and control characters

### MUST NEVER Do
- Modify the document
- Make network calls
- Perform any business-logic validation

### Input Model
```
MetadataExtractionInput:
  file_bytes: bytes
  mime_type: str
  document_id: UUID
```

### Output Model
```
MetadataExtractionResult:
  success: bool
  author: str | None
  creator_software: str | None
  producer: str | None
  creation_date: datetime | None
  modification_date: datetime | None
  pdf_version: str | None
  page_count: int | None
  is_digitally_signed: bool
  custom_properties: dict           # any non-standard PDF metadata
  exif_data: dict | None            # for image files
```

### Public Methods
| Method | Description |
|---|---|
| `extract(input)` | Extracts all available metadata |
| `extract_pdf_metadata(bytes)` | PDF-specific extraction |
| `extract_image_exif(bytes)` | Image EXIF extraction |
| `normalise_dates(metadata)` | Convert all dates to UTC ISO 8601 |

### Dependencies
- `PyMuPDF` — PDF metadata
- `Pillow` — EXIF data
- `LoggingTool`

### Audit Events
| Event | Trigger |
|---|---|
| `DOCUMENT_METADATA_EXTRACTED` | On successful extraction |

### Future Extensions
- Microsoft Office (DOCX/XLSX) metadata extraction
- Email header metadata extraction (for email ingestion workflow)

### Used By
| Agent | Graph |
|---|---|
| UploadAgent | InvoiceProcessingGraph |

---

## Tool: HashTool

**Category:** Document
**File:** `app/tools/document/hash_tool.py`

### Description
Generates and verifies cryptographic hashes of file content. The SHA-256 hash is the primary document identity key used for integrity verification, deduplication, and audit chain integrity.

### Purpose
Provide a deterministic, tamper-evident fingerprint for every document. The hash is stored at upload time and verified at every downstream processing stage.

### Responsibilities
- Compute SHA-256 and MD5 hashes of file content
- Verify a file's hash against a stored reference
- Compute content hashes for arbitrary byte sequences (used for input/output logging)

### MUST Do
- Compute SHA-256 hash using a streaming read for large files (never load entire file into memory for hashing)
- Return lowercase hex strings
- Never store the hash — return it for the caller to store

### MUST NEVER Do
- Make network calls
- Cache hash results (hash must be computed fresh each time)

### Input Models
```
HashComputeInput:
  file_path: str | None
  content: bytes | None    # one of file_path or content must be provided
  algorithms: List[str] = ["sha256", "md5"]

HashVerifyInput:
  file_path: str
  expected_sha256: str
```

### Output Models
```
HashResult:
  success: bool
  sha256: str
  md5: str

HashVerifyResult:
  success: bool
  is_valid: bool
  computed_sha256: str
  expected_sha256: str
```

### Public Methods
| Method | Description |
|---|---|
| `compute(input)` | Compute hashes for file or bytes |
| `verify(input)` | Verify file against expected hash |
| `hash_bytes(content, algorithm)` | Hash arbitrary bytes |

### Dependencies
- `hashlib` (stdlib) — no third-party dependencies
- `LoggingTool`

### Performance Considerations
- Streaming read: 4KB chunks — handles files of any size with constant memory usage
- SHA-256 of a 50MB file: under 200ms

### Future Extensions
- BLAKE3 support (faster than SHA-256 for large files)
- Hash-based content addressing for deduplication

### Used By
| Agent | Graph |
|---|---|
| UploadAgent | InvoiceProcessingGraph |
| DuplicateDetectionAgent | InvoiceProcessingGraph |

---

## Tool: VirusScanTool

**Category:** Document
**File:** `app/tools/document/virus_scan_tool.py`

### Description
Scans uploaded files for malware, viruses, and malicious content before any processing begins. Provider-agnostic — delegates to the injected `VirusScanProviderInterface`.

### Purpose
Prevent malicious files from entering the processing pipeline. Mandatory first step before any file content is read by other tools.

### Responsibilities
- Scan file content using the configured antivirus provider
- Return a clean/infected verdict with threat name if infected
- Quarantine infected files by triggering deletion via StorageTool

### MUST Do
- Scan EVERY uploaded file — no bypassing
- Complete the scan before returning control to the calling agent
- Log the scan result and provider used for every file

### MUST NEVER Do
- Allow a file to proceed if the scan fails (fail-closed, not fail-open)
- Read or process file content beyond passing it to the AV provider

### Input Model
```
VirusScanInput:
  file_path: str
  document_id: UUID
  tenant_id: str
```

### Output Model
```
VirusScanResult:
  success: bool           # scan completed (not file clean)
  is_clean: bool          # True = no threat found
  threat_name: str | None
  scan_provider: str
  scan_duration_ms: int
  error_code: str | None  # SCAN_PROVIDER_UNAVAILABLE, SCAN_TIMEOUT
```

### Public Methods
| Method | Description |
|---|---|
| `scan(input)` | Perform virus scan |
| `is_provider_available()` | Health check for AV provider |

### Dependencies
- `VirusScanProviderInterface` — injected (ClamAVProvider or AzureDefenderProvider)
- `ConfigurationTool` — reads `virusscan.provider`, `virusscan.timeout_seconds`
- `LoggingTool`
- `AuditTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `virusscan.provider` | `clamav` | Active provider |
| `virusscan.timeout_seconds` | `30` | Max scan wait time |
| `virusscan.fail_on_unavailable` | `true` | Reject file if AV unavailable |

### Error Handling
| Error Code | Condition | Behaviour |
|---|---|---|
| `SCAN_PROVIDER_UNAVAILABLE` | AV engine not reachable | Reject file if `fail_on_unavailable=true` |
| `SCAN_TIMEOUT` | Scan exceeded timeout | Retry once, then reject |
| `THREAT_DETECTED` | Malware found | `is_clean=false`, quarantine triggered |

### Audit Events
| Event | Trigger |
|---|---|
| `VIRUS_SCAN_COMPLETED` | Every scan, clean or infected |
| `THREAT_DETECTED` | Infected file found |

### Future Extensions
- Azure Defender for Storage integration (server-side scanning on blob upload)
- Yara rule scanning for custom threat signatures

### Used By
| Agent | Graph |
|---|---|
| UploadAgent | InvoiceProcessingGraph |

---

## Tool: ChecksumTool

**Category:** Document
**File:** `app/tools/document/checksum_tool.py`

### Description
Validates file integrity at every stage of the processing pipeline by re-computing and comparing checksums against the value stored at upload time. Detects in-transit corruption.

### Purpose
Provide a lightweight integrity check that can be called at any pipeline stage to confirm a file has not been corrupted between storage and processing.

### Responsibilities
- Re-compute the SHA-256 of a file at any processing stage
- Compare against the stored checksum in WorkflowState
- Report any integrity violation immediately

### MUST Do
- Use HashTool internally for the actual hash computation
- Compare checksums in constant time (prevent timing attacks)

### Input Model
```
ChecksumValidationInput:
  file_path: str
  expected_sha256: str
  document_id: UUID
```

### Output Model
```
ChecksumValidationResult:
  success: bool
  is_valid: bool
  computed_sha256: str
  expected_sha256: str
  error_code: str | None   # CHECKSUM_MISMATCH, FILE_NOT_FOUND
```

### Public Methods
| Method | Description |
|---|---|
| `validate(input)` | Compare file checksum against expected |

### Dependencies
- `HashTool`
- `LoggingTool`

### Audit Events
| Event | Trigger |
|---|---|
| `INTEGRITY_CHECK_FAILED` | Checksum mismatch detected |

### Used By
| Agent | Graph |
|---|---|
| OCRAgent | InvoiceProcessingGraph |
| ExtractionAgent | InvoiceProcessingGraph |

---

## Tool: DocumentTypeTool

**Category:** Document
**File:** `app/tools/document/document_type_tool.py`

### Description
Classifies documents into platform-recognised document types beyond simple MIME classification. Determines if a file is an invoice, credit note, debit note, purchase order, GRN, or other document type. This is a rule-based classification layer before AI classification.

### Purpose
Apply fast, deterministic rule-based document type detection as a pre-filter before LLM classification. Reduces unnecessary LLM calls for obviously non-invoice documents.

### Responsibilities
- Detect obvious document types from filename patterns, metadata, and structural signals
- Flag documents that are clearly not invoices (e.g. GRNs attached to uploads, PO copies)
- Pass through ambiguous documents to ClassificationAgent for AI classification

### MUST Do
- Never make an LLM call — rule-based only
- Return a confidence score for the detected type
- Return UNKNOWN rather than guessing incorrectly

### Input Model
```
DocumentTypeInput:
  filename: str
  pdf_metadata: PDFMetadata | None
  native_text_sample: str | None    # first 500 chars of native text if available
  document_id: UUID
```

### Output Model
```
DocumentTypeResult:
  success: bool
  detected_type: str       # INVOICE / CREDIT_NOTE / DEBIT_NOTE / PO_COPY / GRN / UNKNOWN
  confidence: float
  detection_signals: List[str]   # which signals led to this classification
```

### Public Methods
| Method | Description |
|---|---|
| `classify(input)` | Classify document type |

### Dependencies
- `ConfigurationTool` — reads document type patterns
- `LoggingTool`

### Future Extensions
- Statement of account detection
- Bank advice note detection
- Contract and lease detection

### Used By
| Agent | Graph |
|---|---|
| ClassificationAgent | InvoiceProcessingGraph |

---

## Tool: PageTool

**Category:** Document
**File:** `app/tools/document/page_tool.py`

### Description
Manages multi-page document operations — splitting, reordering, page selection, and thumbnail generation. Ensures only relevant pages are processed by downstream tools.

### Purpose
Optimise pipeline performance by processing only the pages that contain invoice data, and provide thumbnail images for the frontend document viewer.

### Responsibilities
- Split multi-page PDFs into individual page byte objects
- Select specific pages by index or range
- Generate thumbnail images for frontend display
- Detect blank pages and exclude them from processing

### MUST Do
- Return page bytes without modifying originals
- Detect blank pages using pixel variance analysis

### MUST NEVER Do
- Permanently modify the source file

### Input Model
```
PageOperationInput:
  file_bytes: bytes
  operation: str        # SPLIT / SELECT / THUMBNAIL / DETECT_BLANK
  page_indices: List[int] | None
  thumbnail_width_px: int = 200
```

### Output Model
```
PageOperationResult:
  success: bool
  pages: List[PageResult]
  blank_page_indices: List[int]

PageResult:
  page_index: int
  image_bytes: bytes
  is_blank: bool
  thumbnail_bytes: bytes | None
```

### Dependencies
- `PyMuPDF`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| ClassificationAgent | InvoiceProcessingGraph |
| OCRAgent | InvoiceProcessingGraph |

---

## Tool: FileValidationTool

**Category:** Document
**File:** `app/tools/document/file_validation_tool.py`

### Description
Orchestrates the complete file intake validation pipeline by composing FileTool, VirusScanTool, HashTool, and ChecksumTool into a single validation pass. This is the only composite Document Tool.

### Purpose
Provide a single entry point for agents that need complete file validation without calling four individual tools.

### Responsibilities
- Run format validation (FileTool)
- Run virus scan (VirusScanTool)
- Compute integrity hash (HashTool)
- Return a unified validation verdict

### MUST Do
- Run virus scan BEFORE hash computation
- Return a single `FileIntakeResult` with results from all sub-tools
- Abort pipeline if any sub-tool returns a critical failure

### Input Model
```
FileIntakeInput:
  file_path: str
  declared_mime: str
  declared_size: int
  document_id: UUID
  tenant_id: str
```

### Output Model
```
FileIntakeResult:
  success: bool
  is_safe: bool
  is_valid_format: bool
  sha256: str
  detected_mime: str
  size_bytes: int
  file_validation: FileValidationResult
  virus_scan: VirusScanResult
  hash: HashResult
  overall_verdict: str    # ACCEPTED / QUARANTINED / REJECTED
```

### Dependencies
- `FileTool`
- `VirusScanTool`
- `HashTool`
- `LoggingTool`
- `AuditTool`

### Audit Events
| Event | Trigger |
|---|---|
| `FILE_INTAKE_COMPLETED` | After all checks |
| `FILE_QUARANTINED` | Virus detected |
| `FILE_REJECTED` | Invalid format |

### Used By
| Agent | Graph |
|---|---|
| UploadAgent | InvoiceProcessingGraph |

---

## Tool: CompressionTool

**Category:** Document
**File:** `app/tools/document/compression_tool.py`

### Description
Compresses and decompresses document files for archive storage. Reduces storage costs for processed documents that move to long-term archive.

### Purpose
Reduce Azure Blob Storage costs for the archival tier by compressing processed documents before moving them to cold storage.

### Responsibilities
- Compress PDF and image files using configurable algorithm
- Decompress files for retrieval from archive
- Ensure no data loss (lossless compression only for documents)

### MUST Do
- Use lossless compression only
- Preserve original file metadata after decompression
- Verify integrity via checksum after compression

### Input Model
```
CompressionInput:
  file_bytes: bytes
  algorithm: str = "gzip"     # gzip | zstd
  level: int = 6
```

### Output Model
```
CompressionResult:
  success: bool
  compressed_bytes: bytes
  original_size: int
  compressed_size: int
  compression_ratio: float
  algorithm: str
```

### Dependencies
- `gzip`, `zstd` (stdlib + third-party)
- `HashTool` — integrity verification
- `ConfigurationTool`

### Used By
| Agent | Graph |
|---|---|
| AuditAgent | InvoiceProcessingGraph |

---

*END OF DOCUMENT TOOLS*

---

# OCR TOOLS

---

## Tool: OCRTool

**Category:** OCR
**File:** `app/tools/ocr/ocr_tool.py`

### Description
Provider-agnostic OCR orchestrator. Selects the correct OCR provider based on document type and configuration, invokes it, and returns a normalised `OCRResult` regardless of which engine was used. This is the only OCR entry point for agents — no agent calls TesseractTool or AzureOCRTool directly.

### Purpose
Decouple the OCR engine selection from agents. Enable switching from Tesseract to Azure Document Intelligence by changing one config value, with zero agent code changes.

### Responsibilities
- Read the `ocr.provider` configuration to determine active engine
- Delegate to the appropriate provider tool
- Normalise provider-specific output to the standard `OCRResult` format
- Apply fallback to secondary provider if primary fails
- Report which provider was used

### MUST Do
- Expose a single `extract(input)` method to all callers
- Never expose provider-specific types to calling agents
- Attempt fallback provider when primary fails and `ocr.enable_fallback=true`
- Include the provider name in every result

### MUST NEVER Do
- Contain OCR implementation logic — it is a router only
- Cache OCR results (results are document-specific, not reusable)

### Input Model
```
OCRInput:
  image_bytes: bytes          # pre-processed image from ImageTool
  document_type: str          # DIGITAL / SCANNED / HANDWRITTEN
  document_id: UUID
  page_number: int
  language_hint: str = "eng"
```

### Output Model
```
OCRResult:
  success: bool
  raw_text: str
  structured_blocks: List[TextBlock]
  confidence: float               # 0.0–1.0, averaged from provider
  provider_used: str              # "tesseract" | "azure_di"
  processing_time_ms: int
  language_detected: str
  quality_warnings: List[str]
  error_code: str | None

TextBlock:
  text: str
  confidence: float
  bounding_box: BoundingBox
  block_type: str              # WORD / LINE / PARAGRAPH / TABLE / KEY_VALUE
  page_number: int

BoundingBox:
  x: float
  y: float
  width: float
  height: float
```

### Public Methods
| Method | Description |
|---|---|
| `extract(input)` | Main extraction entry point |
| `get_active_provider()` | Returns name of currently configured provider |
| `health_check()` | Verifies provider is reachable |

### Internal Helpers
- `_route_to_provider(input)` — selects provider based on document_type and config
- `_normalise_result(provider_output, provider_name)` — maps to standard OCRResult
- `_try_fallback(input, primary_error)` — fallback logic

### Dependencies
- `TesseractTool` — primary provider (injected)
- `AzureOCRTool` — secondary provider (injected)
- `ConfigurationTool` — reads `ocr.provider`, `ocr.fallback_provider`, `ocr.enable_fallback`
- `LoggingTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `ocr.provider` | `tesseract` | Active OCR provider |
| `ocr.fallback_provider` | `azure_di` | Provider to use if primary fails |
| `ocr.enable_fallback` | `true` | Whether to attempt fallback |
| `ocr.confidence_threshold` | `0.60` | Minimum acceptable confidence |

### Error Handling
| Error Code | Condition |
|---|---|
| `OCR_ALL_PROVIDERS_FAILED` | Both primary and fallback failed |
| `OCR_LOW_CONFIDENCE` | Result below confidence threshold |
| `OCR_EMPTY_RESULT` | No text extracted |

### Audit Events
| Event | Trigger |
|---|---|
| `OCR_COMPLETED` | Successful extraction |
| `OCR_FALLBACK_USED` | Primary failed, fallback succeeded |
| `OCR_FAILED` | All providers failed |

### Used By
| Agent | Graph |
|---|---|
| OCRAgent | InvoiceProcessingGraph |

---

## Tool: TesseractTool

**Category:** OCR
**File:** `app/tools/ocr/tesseract_provider.py`

### Description
Implements the `OCRProviderInterface` using Tesseract 5.x. Handles SCANNED and HANDWRITTEN documents. Returns output normalised to the standard `OCRResult` format expected by OCRTool.

### Purpose
Provide a self-hosted, free OCR option for scanned documents. Production-grade for typed scanned invoices. Lower accuracy for handwritten content.

### Responsibilities
- Run Tesseract with the correct page segmentation mode for each document type
- Extract per-word and per-line confidence scores
- Return bounding box coordinates for each text block
- Support multiple language packs

### MUST Do
- Use Page Segmentation Mode 1 (auto with OSD) for scanned invoices
- Use Page Segmentation Mode 6 (uniform block of text) for handwritten
- Return per-word confidence scores — not just overall
- Support at minimum: `eng`, `hin` language packs

### MUST NEVER Do
- Perform image pre-processing (that is ImageTool's responsibility)
- Return raw Tesseract HOCR output to calling code

### Input Model
```
TesseractInput:
  image_bytes: bytes
  language: str = "eng"
  psm: int = 1
  oem: int = 3        # LSTM only
  document_id: UUID
  page_number: int
```

### Output Model
```
TesseractResult:
  success: bool
  raw_text: str
  words: List[TesseractWord]
  lines: List[TesseractLine]
  overall_confidence: float
  processing_time_ms: int
  error_code: str | None

TesseractWord:
  text: str
  confidence: float
  bounding_box: BoundingBox
  line_number: int
```

### Public Methods
| Method | Description |
|---|---|
| `extract(input)` | Run Tesseract OCR |
| `get_available_languages()` | List installed language packs |

### Dependencies
- `pytesseract` (Python wrapper)
- `Tesseract 5.x` (system installation)
- `LoggingTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `tesseract.path` | `/usr/bin/tesseract` | Binary path |
| `tesseract.default_language` | `eng` | Default language pack |
| `tesseract.timeout_seconds` | `60` | Per-page timeout |

### Error Handling
| Error Code | Condition |
|---|---|
| `TESSERACT_NOT_FOUND` | Binary not in path |
| `LANGUAGE_PACK_MISSING` | Requested language not installed |
| `TESSERACT_TIMEOUT` | Exceeded per-page timeout |

### Performance Considerations
- Target: under 3 seconds per page at 300 DPI
- CPU-bound — consider worker pool for concurrent documents

### Used By
OCRTool only (agents never call this directly)

---

## Tool: AzureOCRTool

**Category:** OCR
**File:** `app/tools/ocr/azure_di_provider.py`

### Description
Implements `OCRProviderInterface` using Azure Document Intelligence (Form Recognizer). Handles all document types including handwritten content with higher accuracy than Tesseract.

### Purpose
Provide a cloud-scale, high-accuracy OCR option as either the primary engine or fallback. Enables Azure Document Intelligence structured extraction (key-value pairs, tables) in addition to raw text.

### Responsibilities
- Call Azure Document Intelligence REST API
- Extract structured data (key-value pairs, tables) in addition to raw text
- Map Azure DI response to standard `OCRResult` format
- Handle Azure API rate limiting and quota errors

### MUST Do
- Use Azure Managed Identity or Key Vault for authentication — no hardcoded keys
- Map Azure DI confidence scores (0–1) to standard format
- Extract table structures when `extract_tables=true`

### MUST NEVER Do
- Store the API key in code — always from Key Vault via injected config
- Make direct HTTP calls — use the Azure SDK client (injected)

### Input Model
```
AzureOCRInput:
  image_bytes: bytes
  document_id: UUID
  page_number: int
  extract_tables: bool = True
  extract_key_values: bool = True
  model_id: str = "prebuilt-document"
```

### Output Model
```
AzureOCRResult:
  success: bool
  raw_text: str
  words: List[TextBlock]
  tables: List[ExtractedTable]
  key_value_pairs: List[KeyValuePair]
  overall_confidence: float
  processing_time_ms: int
  api_request_id: str
  error_code: str | None

ExtractedTable:
  row_count: int
  column_count: int
  cells: List[TableCell]

KeyValuePair:
  key: str
  value: str
  confidence: float
```

### Dependencies
- `azure-ai-formrecognizer` SDK (injected client)
- `ConfigurationTool` — reads `azure_di.endpoint`, `azure_di.model_id`
- `LoggingTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `azure_di.endpoint` | *(from Key Vault)* | Azure DI endpoint URL |
| `azure_di.model_id` | `prebuilt-invoice` | Default analysis model |
| `azure_di.timeout_seconds` | `120` | API call timeout |

### Future Extensions
- Custom trained invoice model (`azure_di.model_id = "custom-invoice-v2"`)
- Multi-page document analysis

### Used By
OCRTool only

---

## Tool: OCRConfidenceTool

**Category:** OCR
**File:** `app/tools/ocr/ocr_confidence_tool.py`

### Description
Evaluates the quality of an OCR result by analysing word-level confidence scores, text completeness, and structural coherence. Produces a composite OCR quality score distinct from raw provider confidence.

### Purpose
Provide an objective, provider-agnostic quality measure for OCR output. The OCR quality score directly influences whether the pipeline continues automatically or escalates to human review.

### Responsibilities
- Compute weighted average confidence from word-level scores
- Detect confidence valleys (regions of consistently low confidence)
- Identify suspicious OCR artefacts (garbled characters, impossible character sequences)
- Produce a quality tier: HIGH / MEDIUM / LOW / UNUSABLE

### MUST Do
- Return a confidence score even for failed OCR (0.0)
- Identify and list specific regions with low confidence

### Input Model
```
OCRConfidenceInput:
  ocr_result: OCRResult
  document_id: UUID
```

### Output Model
```
OCRConfidenceResult:
  success: bool
  overall_confidence: float
  quality_tier: str            # HIGH / MEDIUM / LOW / UNUSABLE
  low_confidence_regions: List[BoundingBox]
  garbled_word_count: int
  total_word_count: int
  recommendation: str | None
```

### Public Methods
| Method | Description |
|---|---|
| `evaluate(input)` | Full confidence evaluation |
| `compute_weighted_confidence(words)` | Weighted average by word length |
| `detect_garbled_text(text)` | Find implausible character sequences |

### Dependencies
- `ConfigurationTool` — reads `ocr.confidence.high_threshold`, `ocr.confidence.low_threshold`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| OCRAgent | InvoiceProcessingGraph |

---

## Tool: DeskewTool

**Category:** OCR
**File:** `app/tools/ocr/deskew_tool.py`

### Description
Detects and corrects document skew (rotation introduced during scanning). A specialised tool that wraps the deskew capability of ImageTool with OCR-specific configuration and quality feedback.

### Purpose
Maximise OCR accuracy by ensuring document pages are aligned horizontally before processing. Even 1–2° of skew can significantly reduce Tesseract accuracy.

### Responsibilities
- Detect skew angle using Hough transform
- Correct skew via affine transformation
- Report the correction applied for audit

### MUST Do
- Return the original image unchanged if skew is below threshold
- Report the skew angle detected and angle applied

### Input Model
```
DeskewInput:
  image_bytes: bytes
  document_id: UUID
  page_number: int
  max_correction_degrees: float = 15.0
```

### Output Model
```
DeskewResult:
  success: bool
  corrected_image_bytes: bytes
  detected_angle_degrees: float
  correction_applied: bool
  correction_degrees: float
```

### Dependencies
- `OpenCV`
- `ConfigurationTool` — reads `deskew.min_angle_threshold` (below this, skip)
- `LoggingTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `deskew.min_angle_threshold` | `0.5` | Skip correction below this angle |
| `deskew.max_correction_degrees` | `15.0` | Reject if skew exceeds this |

### Used By
| Agent | Graph |
|---|---|
| OCRAgent (via ImageTool pipeline) | InvoiceProcessingGraph |

---

## Tool: ImageEnhancementTool

**Category:** OCR
**File:** `app/tools/ocr/image_enhancement_tool.py`

### Description
Applies a targeted set of image enhancements specifically tuned for OCR pre-processing. Goes beyond ImageTool's general quality assessment to apply aggressive enhancement for very low-quality scans.

### Purpose
Recover usable text from poor-quality scans that would otherwise fall below the OCR confidence threshold, reducing human review escalations.

### Responsibilities
- Binarisation (convert greyscale to black-and-white using Otsu thresholding)
- Adaptive thresholding for uneven lighting
- Morphological operations (erosion/dilation) to improve character clarity
- Background removal for documents with coloured backgrounds

### MUST Do
- Return the original if quality is already HIGH (avoid over-processing)
- Document every transformation applied in the result

### Input Model
```
ImageEnhancementInput:
  image_bytes: bytes
  quality_tier: str        # from ImageTool — only enhance MEDIUM or LOW
  document_id: UUID
  page_number: int
```

### Output Model
```
ImageEnhancementResult:
  success: bool
  enhanced_image_bytes: bytes
  transformations_applied: List[str]
  estimated_quality_improvement: float    # delta score
```

### Dependencies
- `OpenCV`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| OCRAgent | InvoiceProcessingGraph |

---

## Tool: TextCleaningTool

**Category:** OCR
**File:** `app/tools/ocr/text_cleaning_tool.py`

### Description
Post-processes raw OCR text output to remove artefacts, normalise whitespace, fix common OCR substitution errors, and prepare clean text for LLM extraction.

### Purpose
Improve LLM extraction accuracy by cleaning OCR noise before passing text to ExtractionTool. Clean input = more accurate extraction = higher confidence scores.

### Responsibilities
- Normalise Unicode characters (decompose composed forms)
- Replace common OCR substitutions (0→O, l→1, rn→m patterns)
- Normalise line breaks and whitespace
- Remove null bytes and control characters
- Fix broken hyphenation across lines
- Preserve meaningful formatting (table-like structures)

### MUST Do
- Return a string for all inputs (never None)
- Log a diff summary (characters changed, lines cleaned)

### MUST NEVER Do
- Change or interpret the semantic meaning of the text
- Remove words — only fix character-level artefacts

### Input Model
```
TextCleaningInput:
  raw_text: str
  document_id: UUID
  apply_ocr_correction: bool = True
  apply_unicode_normalisation: bool = True
```

### Output Model
```
TextCleaningResult:
  success: bool
  cleaned_text: str
  characters_changed: int
  lines_cleaned: int
  corrections_applied: List[str]
```

### Public Methods
| Method | Description |
|---|---|
| `clean(input)` | Full cleaning pipeline |
| `normalise_unicode(text)` | Unicode normalisation (NFC) |
| `fix_ocr_substitutions(text)` | Pattern-based character fix |
| `normalise_whitespace(text)` | Remove excess whitespace |

### Dependencies
- `unicodedata` (stdlib)
- `re` (stdlib)
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| OCRAgent | InvoiceProcessingGraph |

---

## Tool: LanguageDetectionTool

**Category:** OCR
**File:** `app/tools/ocr/language_detection_tool.py`

### Description
Detects the primary language of the document from OCR text output. Used to select the correct OCR language pack and LLM prompt variant.

### Purpose
Enable multi-language invoice processing. India-specific: detect Hindi, Tamil, Telugu alongside English for appropriate language model selection.

### Responsibilities
- Detect primary language from text sample
- Return ISO 639-1 language code
- Report confidence of detection

### Input Model
```
LanguageDetectionInput:
  text_sample: str    # first 500 characters of OCR output
  document_id: UUID
```

### Output Model
```
LanguageDetectionResult:
  success: bool
  detected_language: str      # ISO 639-1 e.g. "en", "hi", "ta"
  confidence: float
  alternative_languages: List[str]
```

### Dependencies
- `langdetect` or `fasttext` (injected as LanguageDetectionProviderInterface)
- `LoggingTool`

### Future Extensions
- Arabic, Chinese, Japanese support for global platform rollout

### Used By
| Agent | Graph |
|---|---|
| OCRAgent | InvoiceProcessingGraph |

---

## Tool: TableExtractionTool

**Category:** OCR
**File:** `app/tools/ocr/table_extraction_tool.py`

### Description
Detects and extracts tabular data from document images. Invoice line items are almost universally presented in tables — this tool specialises in extracting structured table content from raw image data.

### Purpose
Extract invoice line items as structured rows and columns rather than raw text, significantly improving line item extraction accuracy.

### Responsibilities
- Detect table regions in document images using visual structure
- Extract row and column structure
- Return cell-level text with positional information
- Handle merged cells and spanning headers

### MUST Do
- Return an empty table list (not an error) if no tables are found
- Preserve row/column relationships in the output

### Input Model
```
TableExtractionInput:
  image_bytes: bytes
  document_id: UUID
  page_number: int
  extraction_method: str = "auto"    # "auto" | "lines" | "whitespace"
```

### Output Model
```
TableExtractionResult:
  success: bool
  tables: List[ExtractedTable]
  table_count: int

ExtractedTable:
  table_index: int
  row_count: int
  column_count: int
  bounding_box: BoundingBox
  cells: List[TableCell]
  confidence: float

TableCell:
  row: int
  column: int
  text: str
  confidence: float
  is_header: bool
  bounding_box: BoundingBox
```

### Dependencies
- `camelot-py` or `pdfplumber` for native PDF tables
- `OpenCV` for image-based table detection
- `AzureOCRTool` when `extraction_method=azure` (table API)
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| OCRAgent | InvoiceProcessingGraph |
| ExtractionAgent | InvoiceProcessingGraph |

---

## Tool: BoundingBoxTool

**Category:** OCR
**File:** `app/tools/ocr/bounding_box_tool.py`

### Description
Manages bounding box coordinates for text regions. Converts between coordinate systems (pixels, percentages, normalised) and provides spatial relationship queries.

### Purpose
Enable field localisation — knowing WHERE on the page a field appears helps validate extraction (e.g. "total amount should be bottom-right region") and supports human review UI highlighting.

### Responsibilities
- Convert between pixel coordinates, percentage coordinates, and normalised coordinates
- Compute spatial relationships (above, below, left of, right of)
- Merge overlapping bounding boxes
- Filter text blocks by region of interest

### Input Model
```
BoundingBoxInput:
  boxes: List[BoundingBox]
  page_width_px: int
  page_height_px: int
  operation: str    # CONVERT / MERGE / FILTER_REGION / SPATIAL_QUERY
```

### Dependencies
- Pure Python — no external dependencies
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| OCRAgent | InvoiceProcessingGraph |
| ExtractionAgent | InvoiceProcessingGraph |

---

## Tool: BarcodeTool

**Category:** OCR
**File:** `app/tools/ocr/barcode_tool.py`

### Description
Detects and decodes barcodes and QR codes embedded in document images. Some invoices contain barcodes encoding invoice numbers, vendor codes, or amounts.

### Purpose
Extract machine-readable data from barcodes to supplement OCR extraction and provide a high-confidence anchor for key fields.

### Responsibilities
- Detect barcode regions in images
- Decode 1D barcodes (Code 128, Code 39, EAN-13)
- Decode QR codes
- Map decoded content to invoice fields where possible

### Input Model
```
BarcodeInput:
  image_bytes: bytes
  document_id: UUID
  page_number: int
```

### Output Model
```
BarcodeResult:
  success: bool
  barcodes_found: int
  barcodes: List[DecodedBarcode]

DecodedBarcode:
  barcode_type: str     # QR_CODE | CODE_128 | EAN_13 | ...
  decoded_value: str
  bounding_box: BoundingBox
  confidence: float
```

### Dependencies
- `pyzbar` or `zxing-cpp`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| OCRAgent | InvoiceProcessingGraph |

---

## Tool: QRCodeTool

**Category:** OCR
**File:** `app/tools/ocr/qrcode_tool.py`

### Description
Specialised QR code extraction and parsing tool. India's e-invoicing mandate (IRP system) embeds a signed QR code in every GST invoice containing invoice summary data. This tool decodes and verifies the IRP QR code.

### Purpose
Extract authoritative invoice data from the IRP-mandated QR code as a high-confidence reference for extraction validation.

### Responsibilities
- Detect and decode QR codes
- Parse IRP invoice QR code payload (JSON structure defined by GSTN)
- Verify QR code digital signature (future)
- Return structured invoice fields from QR content

### Input Model
```
QRCodeInput:
  image_bytes: bytes
  document_id: UUID
  parse_irp_format: bool = True
```

### Output Model
```
QRCodeResult:
  success: bool
  qr_content_raw: str
  is_irp_format: bool
  irp_data: IRPQRData | None

IRPQRData:
  seller_gstin: str
  buyer_gstin: str
  invoice_number: str
  invoice_date: str
  invoice_value: str
  irn: str              # Invoice Reference Number
  signed_qr_data: str
```

### Used By
| Agent | Graph |
|---|---|
| OCRAgent | InvoiceProcessingGraph |
| UniversalValidationAgent | InvoiceProcessingGraph |

---

## Tool: CoordinateExtractionTool

**Category:** OCR
**File:** `app/tools/ocr/coordinate_extraction_tool.py`

### Description
Extracts field values from specific spatial regions of a document based on expected field positions. Used for fixed-format invoices where field positions are predictable.

### Purpose
Enable template-based extraction for recurring vendor invoices with predictable layouts. Higher accuracy and lower LLM cost for known templates.

### Responsibilities
- Accept a field template (field name → bounding box coordinates)
- Extract text from each defined region
- Return field-value pairs with per-field confidence

### Input Model
```
CoordinateExtractionInput:
  image_bytes: bytes
  document_id: UUID
  field_template: Dict[str, BoundingBox]   # field_name → expected region
```

### Output Model
```
CoordinateExtractionResult:
  success: bool
  extracted_fields: Dict[str, FieldExtraction]

FieldExtraction:
  field_name: str
  value: str
  confidence: float
  actual_bounding_box: BoundingBox
```

### Dependencies
- `TesseractTool` — region-constrained OCR
- `LoggingTool`

### Future Extensions
- Template learning from repeated vendor invoices
- Template marketplace for common vendor formats

### Used By
| Agent | Graph |
|---|---|
| ExtractionAgent | InvoiceProcessingGraph |

---

## Tool: PageRotationTool

**Category:** OCR
**File:** `app/tools/ocr/page_rotation_tool.py`

### Description
Detects and corrects page orientation errors (90°, 180°, 270° rotations) that occur when documents are scanned in the wrong orientation.

### Purpose
Prevent OCR failure on sideways or upside-down pages — a common issue with multi-page scanned invoices.

### Responsibilities
- Detect rotation angle (0, 90, 180, 270 degrees)
- Apply rotation correction
- Use Tesseract OSD (orientation and script detection) as the detection engine

### Input Model
```
PageRotationInput:
  image_bytes: bytes
  document_id: UUID
  page_number: int
```

### Output Model
```
PageRotationResult:
  success: bool
  corrected_image_bytes: bytes
  detected_rotation_degrees: int
  correction_applied: bool
```

### Dependencies
- `OpenCV`
- `pytesseract` (OSD mode)

### Used By
| Agent | Graph |
|---|---|
| OCRAgent | InvoiceProcessingGraph |

---

*END OF OCR TOOLS*

---

# AI / LLM TOOLS

---

## Tool: LLMTool

**Category:** AI
**File:** `app/tools/ai/llm_tool.py`

### Description
Provider-agnostic LLM invocation tool. The only tool in the platform that makes calls to a Large Language Model. All other AI tools compose LLMTool. Agents never call an LLM directly.

### Purpose
Centralise all LLM calls for unified token tracking, cost monitoring, rate limit handling, model selection, and provider switching.

### Responsibilities
- Accept a rendered prompt and call the configured LLM provider
- Return the raw completion text and token counts
- Handle rate limiting, timeouts, and provider errors
- Track cost per call
- Support JSON-mode and structured output forcing

### MUST Do
- Log every call: model, tokens in, tokens out, cost, duration, prompt hash
- Never expose OpenAI or Azure OpenAI types to calling tools — return normalised `LLMResult`
- Support streaming response aggregation
- Return token counts even for failed calls (if available)

### MUST NEVER Do
- Store prompt content — pass it through only
- Make a decision based on LLM output — that is the calling tool's responsibility
- Retry at this level — RetryTool handles retries externally

### Input Model
```
LLMInput:
  system_prompt: str
  user_prompt: str
  model: str | None           # None = use config default
  temperature: float = 0.0    # 0 for structured extraction
  max_tokens: int = 4096
  response_format: str = "text"    # "text" | "json_object"
  workflow_id: UUID | None
  document_id: UUID | None
  prompt_version: str | None
  tenant_id: str
```

### Output Model
```
LLMResult:
  success: bool
  content: str
  prompt_tokens: int
  completion_tokens: int
  total_tokens: int
  model_used: str
  provider_used: str          # "openai" | "azure_openai"
  estimated_cost_usd: float
  finish_reason: str          # "stop" | "length" | "content_filter"
  latency_ms: int
  error_code: str | None      # RATE_LIMIT, TIMEOUT, CONTEXT_LENGTH, CONTENT_FILTER
```

### Public Methods
| Method | Description |
|---|---|
| `complete(input)` | Send prompt, return completion |
| `estimate_cost(model, tokens)` | Cost estimation before calling |
| `count_tokens(text, model)` | Token count for a string |
| `get_active_model()` | Currently configured model name |

### Internal Helpers
- `_build_request(input)` — builds provider-specific request
- `_normalise_response(raw, provider)` — maps to LLMResult
- `_calculate_cost(model, prompt_tokens, completion_tokens)` — cost table lookup

### Dependencies
- `LLMProviderInterface` — injected (OpenAIProvider or AzureOpenAIProvider)
- `ConfigurationTool` — reads `llm.provider`, `llm.model`, `llm.temperature`
- `LoggingTool` — logs every LLM call
- `TokenTrackingTool` — increments tenant token budget

### Configuration
| Key | Default | Description |
|---|---|---|
| `llm.provider` | `openai` | Active provider |
| `llm.model` | `gpt-4o` | Default model |
| `llm.temperature` | `0.0` | Default temperature |
| `llm.max_tokens` | `4096` | Default max tokens |
| `llm.timeout_seconds` | `60` | API call timeout |
| `llm.cost_per_1k_input_tokens` | varies by model | For cost calculation |

### Error Handling
| Error Code | Condition | Recommended Action |
|---|---|---|
| `RATE_LIMIT` | 429 from provider | Backoff + retry |
| `TIMEOUT` | Request exceeded timeout | Retry with shorter prompt |
| `CONTEXT_LENGTH` | Input too long | Truncate prompt |
| `CONTENT_FILTER` | Content policy violation | Flag for review |
| `INVALID_API_KEY` | Auth failure | Alert ops |

### Audit Events
| Event | Trigger |
|---|---|
| `LLM_CALL_COMPLETED` | Every successful call |
| `LLM_CALL_FAILED` | Provider error |

### Performance Considerations
- Async invocation preferred — do not block Celery worker thread
- Cost estimation before long prompts — abort if cost exceeds budget

### Future Extensions
- Azure OpenAI provider
- Anthropic Claude provider
- Local Ollama provider for air-gapped environments
- Multi-model ensemble for high-stakes decisions

### Used By
All AI tools compose LLMTool. No agent calls LLMTool directly.

---

## Tool: PromptTool

**Category:** AI
**File:** `app/tools/ai/prompt_tool.py`

### Description
Loads, renders, and delivers versioned prompts to LLMTool. Reads the active prompt version from PromptVersionTool, resolves tenant-specific overrides, and renders Jinja2 templates with runtime variables.

### Purpose
Decouple prompt content from agent and tool code. Enable prompt changes, A/B testing, rollback, and customer-specific variations without code deployments.

### Responsibilities
- Load the active prompt version for a given agent
- Check for tenant-specific prompt override first
- Render Jinja2 template with provided variables
- Hash the rendered prompt for logging
- Return system and user prompt components separately

### MUST Do
- Always check tenant-specific prompt before falling back to global
- Return the prompt version hash with every result (for reproduction)
- Validate that all required template variables are provided

### MUST NEVER Do
- Cache rendered prompts (variables change per document)
- Modify prompt content

### Input Model
```
PromptInput:
  agent_name: str
  variables: dict            # Jinja2 template variables
  tenant_id: str
  version: str | None = None  # None = use active version
```

### Output Model
```
PromptResult:
  success: bool
  system_prompt: str
  user_prompt: str
  prompt_version: str
  prompt_hash: str           # SHA-256 of rendered prompt
  agent_name: str
  tenant_id: str
  missing_variables: List[str] | None
```

### Public Methods
| Method | Description |
|---|---|
| `load_and_render(input)` | Load + render prompt for agent |
| `get_active_version(agent, tenant_id)` | Get active version name |
| `preview(agent, version, variables)` | Preview without activating |

### Internal Helpers
- `_resolve_prompt_template(agent, tenant_id, version)` — resolves tenant override chain
- `_render_jinja2(template, variables)` — safe Jinja2 render
- `_validate_variables(template, provided)` — check for missing vars

### Dependencies
- `PromptVersionTool` — version management
- `PromptRepository` — loads prompt content from DB/filesystem
- `HashTool` — prompt hashing
- `ConfigurationTool`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| ClassificationAgent | InvoiceProcessingGraph |
| ExtractionAgent | InvoiceProcessingGraph |
| BusinessProfileAgent | InvoiceProcessingGraph |
| DecisionAgent | InvoiceProcessingGraph |

---

## Tool: ExtractionTool

**Category:** AI
**File:** `app/tools/ai/extraction_tool.py`

### Description
Extracts structured invoice data from cleaned OCR text using LLM. Combines PromptTool (to get the active extraction prompt), LLMTool (to call the LLM), and NormalizationTool (to normalise extracted values). Returns typed, validated invoice fields.

### Purpose
Convert unstructured OCR text into the structured `ExtractionResult` that the rest of the pipeline depends on. This is the highest-stakes AI operation in the platform.

### Responsibilities
- Compose PromptTool + LLMTool to extract invoice fields
- Parse the LLM JSON response into typed fields
- Pass raw values through NormalizationTool
- Compute per-field confidence scores from LLM output
- Flag low-confidence fields for human review
- Handle partial extraction (some fields found, others missing)

### MUST Do
- Use `response_format=json_object` to enforce JSON output
- Validate LLM JSON against the invoice extraction schema
- Return a confidence score per field, not just overall
- Log the prompt version used for every extraction

### MUST NEVER Do
- Interpret or validate extracted values (that is ValidationTool's responsibility)
- Make assumptions about missing fields — leave as None

### Input Model
```
ExtractionInput:
  cleaned_text: str
  document_id: UUID
  tenant_id: str
  document_type: str           # DIGITAL / SCANNED / HANDWRITTEN
  table_data: List[ExtractedTable] | None
  key_value_pairs: List[KeyValuePair] | None
```

### Output Model
```
ExtractionResult:
  success: bool
  # Core fields
  invoice_number: str | None
  invoice_date: date | None
  due_date: date | None
  # Vendor fields
  vendor_name: str | None
  vendor_gstin: str | None
  vendor_pan: str | None
  vendor_address: str | None
  # Buyer fields
  buyer_name: str | None
  buyer_gstin: str | None
  buyer_address: str | None
  # Financial fields
  line_items: List[LineItem]
  subtotal: Decimal | None
  discount: Decimal | None
  tax_amount: Decimal | None
  total_amount: Decimal | None
  currency: str | None
  # Reference fields
  po_reference: str | None
  payment_terms: str | None
  bank_details: BankDetails | None
  # Metadata
  confidence_per_field: Dict[str, float]
  overall_confidence: float
  prompt_version_used: str
  model_used: str
  tokens_used: int
  low_confidence_fields: List[str]

LineItem:
  description: str
  quantity: Decimal
  unit: str | None
  unit_price: Decimal
  amount: Decimal
  tax_rate: Decimal | None
  tax_amount: Decimal | None
  hsn_sac_code: str | None
```

### Public Methods
| Method | Description |
|---|---|
| `extract(input)` | Full extraction pipeline |
| `validate_extraction_schema(llm_json)` | Validate LLM output structure |
| `compute_field_confidence(llm_response)` | Per-field confidence |

### Dependencies
- `PromptTool`
- `LLMTool`
- `NormalizationTool`
- `LoggingTool`
- `AuditTool`

### Audit Events
| Event | Trigger |
|---|---|
| `EXTRACTION_COMPLETED` | Successful extraction |
| `EXTRACTION_LOW_CONFIDENCE` | Any field below confidence threshold |
| `EXTRACTION_SCHEMA_ERROR` | LLM returned invalid JSON |

### Future Extensions
- Few-shot examples per vendor (inject historical extractions into prompt)
- RAG-assisted extraction (retrieve similar invoice examples)
- Multi-model ensemble for high-value invoices

### Used By
| Agent | Graph |
|---|---|
| ExtractionAgent | InvoiceProcessingGraph |

---

## Tool: ClassificationTool

**Category:** AI
**File:** `app/tools/ai/classification_tool.py`

### Description
Classifies documents using LLM when rule-based classification (DocumentTypeTool) is inconclusive. Determines the document type (DIGITAL/SCANNED/HANDWRITTEN) and overall content category.

### Purpose
Provide AI-powered document classification for ambiguous cases where structural signals are insufficient.

### Responsibilities
- Classify document as DIGITAL / SCANNED / HANDWRITTEN
- Provide confidence score for the classification
- Provide reasoning for the classification decision

### MUST Do
- Use `temperature=0.0` for deterministic output
- Include reasoning in output for explainability

### Input Model
```
ClassificationInput:
  text_sample: str | None          # native text if available
  image_quality_score: float
  has_native_text: bool
  page_count: int
  document_id: UUID
  tenant_id: str
```

### Output Model
```
ClassificationResult:
  success: bool
  document_type: str          # DIGITAL / SCANNED / HANDWRITTEN
  confidence: float
  ocr_strategy: str           # which OCR approach to use
  reasoning: str              # LLM's explanation
  prompt_version_used: str
```

### Dependencies
- `PromptTool`
- `LLMTool`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| ClassificationAgent | InvoiceProcessingGraph |

---

## Tool: BusinessProfileTool

**Category:** AI
**File:** `app/tools/ai/business_profile_tool.py`

### Description
Determines which of the 9 configured business profiles applies to an invoice. Uses a hybrid approach: rule-based detection first (fast, cheap), LLM confirmation for ambiguous cases.

### Purpose
Route each invoice to the correct validation rules, matching logic, and approval matrix. The business profile is the single most important classification in the platform — all subsequent processing depends on it.

### Responsibilities
- Apply rule-based profile detection from `business_rules.yaml`
- If rules are inconclusive or confidence < threshold, use LLM confirmation
- Return the detected profile with confidence and detection method
- Support all 9 profiles: PO_RAW_MATERIAL, NON_PO_RAW_MATERIAL, PO_CAPEX, NON_PO_CAPEX, PO_OPEX, NON_PO_OPEX, LEASE_RENT, EMPLOYEE_REIMBURSEMENT, PETTY_CASH

### MUST Do
- Attempt rule-based detection before LLM
- Return detection method in result (RULE / AI / HYBRID)
- Return UNKNOWN rather than guess when confidence < minimum threshold

### Input Model
```
BusinessProfileInput:
  extraction_result: ExtractionResult
  validation_result: ValidationResult
  document_id: UUID
  tenant_id: str
```

### Output Model
```
BusinessProfileResult:
  success: bool
  detected_profile: str
  confidence: float
  detection_method: str       # RULE / AI / HYBRID
  rule_signals: List[str]     # which rules fired
  llm_reasoning: str | None
  prompt_version_used: str | None
  fallback_profiles: List[str]   # next-most-likely profiles
```

### Dependencies
- `BusinessRuleTool` — rule-based pre-classification
- `PromptTool`
- `LLMTool`
- `ConfigurationTool` — loads 9 profile definitions
- `LoggingTool`
- `AuditTool`

### Audit Events
| Event | Trigger |
|---|---|
| `PROFILE_DETECTED` | Profile determination completed |
| `PROFILE_AMBIGUOUS` | Confidence below threshold |

### Used By
| Agent | Graph |
|---|---|
| BusinessProfileAgent | InvoiceProcessingGraph |

---

## Tool: NormalizationTool

**Category:** AI
**File:** `app/tools/ai/normalization_tool.py`

### Description
Converts raw extracted field values from their source format (as-extracted strings) into canonical typed values. Handles date parsing, number parsing, name normalisation, and GSTIN/PAN formatting.

### Purpose
Ensure all downstream tools work with consistent, typed data regardless of the format variation on the source invoice (e.g. "15/06/2026", "15-Jun-2026", and "June 15, 2026" all become `date(2026, 6, 15)`).

### Responsibilities
- Parse and normalise date fields to `date` type
- Parse and normalise amount fields to `Decimal`
- Title-case vendor and buyer names
- Normalise GSTIN to uppercase without spaces
- Normalise currency codes to ISO 4217
- Handle Indian number format (lakhs, crores) conversion

### MUST Do
- Return None for values that cannot be parsed — never guess
- Log normalisation failures as warnings (not errors)

### MUST NEVER Do
- Validate normalised values (that is ValidationTool's responsibility)
- Discard partially parseable values — return both raw and normalised

### Input Model
```
NormalizationInput:
  raw_fields: Dict[str, Any]     # field_name → raw string value
  country_code: str = "IN"
  document_id: UUID
```

### Output Model
```
NormalizationResult:
  success: bool
  normalised_fields: Dict[str, Any]     # typed values
  raw_fields: Dict[str, str]            # original strings preserved
  normalisation_failures: Dict[str, str]  # field → reason
```

### Public Methods
| Method | Description |
|---|---|
| `normalise(input)` | Full normalisation pass |
| `parse_date(value, formats)` | Date parsing with format fallbacks |
| `parse_decimal(value, locale)` | Amount parsing |
| `normalise_gstin(value)` | GSTIN formatting |
| `normalise_name(value)` | Name title-casing and cleaning |

### Dependencies
- `dateutil` — flexible date parsing
- `babel` — locale-aware number parsing
- `ConfigurationTool` — reads country locale config
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| ExtractionAgent | InvoiceProcessingGraph |

---

## Tool: ConfidenceTool

**Category:** AI
**File:** `app/tools/ai/confidence_tool.py`

### Description
Aggregates all per-stage confidence scores from the WorkflowState into a single overall confidence score. Applies configurable weights per stage and classifies the result into confidence tiers (HIGH/MEDIUM/LOW).

### Purpose
Provide the single confidence signal that drives the DecisionAgent's routing decision. This tool is the final arbiter of automation vs. human review.

### Responsibilities
- Read all stage confidence scores from WorkflowState
- Apply configured weights per stage
- Compute weighted average
- Classify result into tier: HIGH / MEDIUM / LOW
- Identify which factors dragged the score down
- Generate a human-readable confidence explanation

### MUST Do
- Return a result even if some stage scores are missing (use 0.5 as default for missing stages)
- Report the dominant negative factors
- Use configurable weights — never hardcode stage weights

### Input Model
```
ConfidenceAggregationInput:
  stage_scores: Dict[str, float]    # stage_name → 0.0–1.0
  document_id: UUID
  tenant_id: str
```

### Output Model
```
ConfidenceAggregationResult:
  success: bool
  overall_score: float
  confidence_tier: str         # HIGH / MEDIUM / LOW
  per_stage_scores: Dict[str, float]
  applied_weights: Dict[str, float]
  risk_factors: List[ConfidenceRiskFactor]
  explanation: str             # human-readable summary

ConfidenceRiskFactor:
  stage: str
  score: float
  weight: float
  contribution_to_reduction: float
  description: str
```

### Public Methods
| Method | Description |
|---|---|
| `aggregate(input)` | Full confidence aggregation |
| `compute_weighted_score(scores, weights)` | Weighted average |
| `classify_tier(score)` | Map score to tier name |
| `identify_risk_factors(scores, weights)` | Find top detractors |

### Dependencies
- `ConfigurationTool` — reads stage weights and tier thresholds
- `LoggingTool`

### Audit Events
| Event | Trigger |
|---|---|
| `CONFIDENCE_CALCULATED` | After aggregation |

### Used By
| Agent | Graph |
|---|---|
| ConfidenceAgent | InvoiceProcessingGraph |

---

## Tool: TokenTrackingTool

**Category:** AI
**File:** `app/tools/ai/token_tracking_tool.py`

### Description
Tracks LLM token consumption per tenant, per agent, and per document. Maintains running totals and enforces configurable budget limits.

### Purpose
Enable cost visibility and budget enforcement at the tenant level. Prevents runaway LLM costs from anomalous documents or misconfigured prompts.

### Responsibilities
- Increment token counters after every LLM call
- Enforce per-tenant daily and monthly token budgets
- Alert when budget thresholds are approached
- Provide cost breakdown by agent and model

### MUST Do
- Update counters atomically (Redis INCR — not read-then-write)
- Enforce budget BEFORE the LLM call when possible (pre-check)

### Input Models
```
TokenIncrementInput:
  tenant_id: str
  agent_name: str
  model: str
  prompt_tokens: int
  completion_tokens: int
  estimated_cost_usd: float
  document_id: UUID
  workflow_id: UUID

TokenBudgetCheckInput:
  tenant_id: str
  estimated_tokens: int
  model: str
```

### Output Models
```
TokenBudgetCheckResult:
  within_budget: bool
  current_usage_today: int
  daily_limit: int
  estimated_cost_usd: float
  budget_remaining_usd: float
```

### Dependencies
- Redis (via QueueTool) — atomic counter updates
- `ConfigurationTool` — reads tenant budget limits
- `LoggingTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `token_budget.daily_limit_per_tenant` | `1000000` | Daily token limit |
| `token_budget.alert_threshold_percent` | `80` | Alert at 80% budget |

### Used By
| Agent | Graph |
|---|---|
| All agents that call LLM | InvoiceProcessingGraph |

---

## Tool: SummaryTool

**Category:** AI
**File:** `app/tools/ai/summary_tool.py`

### Description
Generates human-readable summaries of workflow state for approvers, exception handlers, and audit consumers. Converts machine-readable WorkflowState sections into natural language.

### Purpose
Provide approvers with a concise, AI-generated invoice summary so they can make informed approval decisions without reading raw JSON or navigating multiple screens.

### Responsibilities
- Generate invoice summary for approval notification
- Generate exception summary for exception handlers
- Generate processing summary for audit reports

### Input Model
```
SummaryInput:
  summary_type: str        # APPROVAL | EXCEPTION | AUDIT | EXTRACTION
  context_data: dict       # relevant section of WorkflowState
  document_id: UUID
  tenant_id: str
```

### Output Model
```
SummaryResult:
  success: bool
  summary_text: str
  summary_bullets: List[str]    # 3–5 key points
  prompt_version_used: str
```

### Dependencies
- `PromptTool`
- `LLMTool`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| ApprovalAgent | ApprovalGraph |
| ExceptionAgent | ExceptionGraph |
| AuditAgent | InvoiceProcessingGraph |

---

## Tool: ReasoningTool

**Category:** AI
**File:** `app/tools/ai/reasoning_tool.py`

### Description
Generates structured chain-of-thought reasoning for complex AI decisions. Used by DecisionAgent to produce explainable routing decisions and by BusinessProfileAgent for ambiguous profiles.

### Purpose
Make every AI decision auditable and explainable. Regulators, auditors, and approvers must be able to understand why the system made a particular decision.

### Responsibilities
- Produce step-by-step reasoning for a given decision
- Structure reasoning as: observed evidence → applied rules → conclusion
- Map reasoning to specific WorkflowState fields

### Input Model
```
ReasoningInput:
  decision_type: str          # PROFILE | ROUTING | APPROVAL_RECOMMENDATION
  evidence: dict              # relevant state data
  rules_applied: List[str]
  conclusion: str
  document_id: UUID
  tenant_id: str
```

### Output Model
```
ReasoningResult:
  success: bool
  reasoning_steps: List[ReasoningStep]
  conclusion: str
  confidence: float
  supporting_evidence: List[str]
  contrary_evidence: List[str]

ReasoningStep:
  step_number: int
  observation: str
  rule_applied: str | None
  inference: str
```

### Dependencies
- `PromptTool`
- `LLMTool`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| DecisionAgent | InvoiceProcessingGraph |
| BusinessProfileAgent | InvoiceProcessingGraph |

---

*END OF AI TOOLS*

---

# VALIDATION TOOLS

---

## Tool: ValidationTool

**Category:** Validation
**File:** `app/tools/validation/validation_tool.py`

### Description
Core validation engine. Executes a list of typed `ValidationRule` objects against a data payload and returns a structured `ValidationReport`. All other validation tools compose this tool — it is the single mechanism through which rules produce `ValidationResult` objects.

### Purpose
Provide a reusable, rule-agnostic validation runner. The same engine validates GST numbers, arithmetic totals, PO matches, and profile rules. Rule definitions live in YAML config — the engine never needs to change.

### Responsibilities
- Accept a list of validation rules and a data dictionary
- Execute each rule in order
- Collect results (PASS / FAIL / WARNING / SKIPPED)
- Compute overall status: PASS if all pass, SOFT_FAIL if any warnings, HARD_FAIL if any critical rule fails
- Return an immutable validation report

### MUST Do
- Execute ALL rules even if some fail (collect all errors, not just first)
- Mark rules as SKIPPED when their precondition is not met (not FAIL)
- Compute overall status deterministically
- Include evidence, compared values, and recommendation in every result

### MUST NEVER Do
- Short-circuit on first failure (unless `abort_on_first_failure=true` is explicitly set)
- Store results — return them to the caller

### Input Model
```
ValidationInput:
  rules: List[ValidationRule]
  data: dict
  document_id: UUID
  abort_on_first_failure: bool = False

ValidationRule:
  rule_id: str
  rule_name: str
  severity: str           # CRITICAL / HIGH / MEDIUM / LOW
  precondition: str | None   # JSONPath expression; skip rule if data doesn't match
  rule_type: str          # PRESENCE / FORMAT / RANGE / ARITHMETIC / COMPARISON / CUSTOM
  parameters: dict        # rule-specific parameters
  error_message_template: str
  recommendation: str
```

### Output Model
```
ValidationReport:
  overall_status: str         # PASS / SOFT_FAIL / HARD_FAIL
  total_rules: int
  passed: int
  failed: int
  warnings: int
  skipped: int
  results: List[ValidationResult]
  critical_failures: List[str]    # rule_ids of CRITICAL failures
  execution_time_ms: int

ValidationResult:
  rule_id: str
  rule_name: str
  status: str                 # PASS / FAIL / WARNING / SKIPPED
  severity: str
  reason: str                 # why it passed or failed
  evidence: dict              # raw data evaluated
  compared_values: dict       # a vs b with variance
  confidence: float
  recommendation: str
```

### Public Methods
| Method | Description |
|---|---|
| `run(input)` | Execute all rules |
| `run_single(rule, data)` | Execute one rule |
| `evaluate_precondition(precondition, data)` | Check if rule applies |

### Internal Helpers
- `_execute_presence_rule(rule, data)` — checks field exists and is non-empty
- `_execute_format_rule(rule, data)` — regex pattern match
- `_execute_range_rule(rule, data)` — numeric range validation
- `_execute_arithmetic_rule(rule, data)` — computed value comparison
- `_execute_comparison_rule(rule, data)` — field-to-field comparison

### Dependencies
- `ConfigurationTool` — loads rule definitions
- `LoggingTool`

### Audit Events
| Event | Trigger |
|---|---|
| `VALIDATION_COMPLETED` | After full run |
| `CRITICAL_VALIDATION_FAILURE` | Any CRITICAL rule fails |

### Used By
| Agent | Graph |
|---|---|
| UniversalValidationAgent | InvoiceProcessingGraph |
| ProfileValidationAgent | InvoiceProcessingGraph |
| TaxValidationAgent | InvoiceProcessingGraph |

---

## Tool: MandatoryFieldTool

**Category:** Validation
**File:** `app/tools/validation/mandatory_field_tool.py`

### Description
Validates that all mandatory fields for a given business profile are present and non-empty in the extraction result. Mandatory field lists are configuration-driven — no field names are hardcoded.

### Purpose
Be the first gate after extraction — if mandatory fields are missing, there is no point running further validation. Provides clear, actionable feedback on which fields are missing.

### Responsibilities
- Load the mandatory field list for the detected business profile from config
- Check each field in ExtractionResult
- Distinguish between NULL (never extracted) and EMPTY (extracted as empty string)
- Identify optional fields that are present vs. absent

### MUST Do
- Read mandatory fields from `business_rules.yaml` — never hardcode
- Report each missing field individually with a clear recommendation
- Distinguish CRITICAL mandatory (blocks processing) from RECOMMENDED (warning only)

### Input Model
```
MandatoryFieldInput:
  extraction_result: ExtractionResult
  business_profile: str       # e.g. "PO_RAW_MATERIAL"
  document_id: UUID
  tenant_id: str
```

### Output Model
```
MandatoryFieldResult:
  success: bool
  overall_status: str              # PASS / SOFT_FAIL / HARD_FAIL
  missing_critical_fields: List[str]
  missing_recommended_fields: List[str]
  present_fields: List[str]
  field_results: List[FieldPresenceResult]

FieldPresenceResult:
  field_name: str
  is_present: bool
  is_critical: bool
  extracted_value: str | None
  reason: str
  recommendation: str
```

### Dependencies
- `ConfigurationTool` — loads `business_rules.yaml` mandatory field lists
- `ValidationTool`
- `LoggingTool`

### Configuration
Reads `profiles.{profile_name}.mandatory_fields` and `profiles.{profile_name}.recommended_fields` from `business_rules.yaml`.

### Used By
| Agent | Graph |
|---|---|
| UniversalValidationAgent | InvoiceProcessingGraph |
| ProfileValidationAgent | InvoiceProcessingGraph |

---

## Tool: GSTValidationTool

**Category:** Validation
**File:** `app/tools/validation/gst_validation_tool.py`

### Description
Validates GST-related data on the invoice: GSTIN format, state code, GSTIN checksum, GST rate applicability, and (optionally) live verification via GSTN API.

### Purpose
Ensure GSTIN data is valid before financial processing. Invalid GSTINs are a common cause of input tax credit rejection — this tool prevents compliance violations.

### Responsibilities
- Validate GSTIN format against the 15-character checksum algorithm
- Extract and validate the embedded state code (first 2 digits)
- Validate the embedded PAN within the GSTIN (chars 3–12)
- Validate the taxpayer type code (char 13)
- Optionally verify the GSTIN is active against GSTN API

### MUST Do
- Run the Luhn-style GSTIN checksum validation
- Extract and cross-reference the embedded PAN
- Clearly state which component failed

### MUST NEVER Do
- Make GSTN API calls unless `gst.live_verification=true` in config
- Block processing if GSTN API is unavailable when `live_verification=false`

### Input Model
```
GSTValidationInput:
  vendor_gstin: str | None
  buyer_gstin: str | None
  invoice_amount: Decimal
  document_id: UUID
  tenant_id: str
```

### Output Model
```
GSTValidationResult:
  success: bool
  vendor_gstin_valid: bool
  buyer_gstin_valid: bool
  vendor_state_code: str | None
  buyer_state_code: str | None
  is_interstate: bool
  embedded_pan_matches: bool | None   # if PAN also present on invoice
  live_verification_result: str | None   # ACTIVE / INACTIVE / CANCELLED / UNKNOWN
  results: List[ValidationResult]
  overall_status: str
```

### Public Methods
| Method | Description |
|---|---|
| `validate(input)` | Full GST validation |
| `validate_gstin_format(gstin)` | Format and checksum check |
| `extract_state_code(gstin)` | Extract 2-digit state code |
| `extract_pan_from_gstin(gstin)` | Extract embedded PAN |
| `verify_gstin_live(gstin)` | GSTN API verification |

### Dependencies
- `ConfigurationTool` — reads `gst.live_verification`, `gst.state_code_map`
- `ValidationTool`
- `LoggingTool`
- `AuditTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `gst.live_verification` | `false` | Enable GSTN API calls |
| `gst.strict_mode` | `true` | HARD_FAIL on invalid GSTIN |
| `gst.gstn_api_url` | *(from Key Vault)* | GSTN verification endpoint |

### Audit Events
| Event | Trigger |
|---|---|
| `GST_VALIDATION_COMPLETED` | After validation |
| `GST_INVALID_DETECTED` | Invalid GSTIN found |

### Used By
| Agent | Graph |
|---|---|
| UniversalValidationAgent | InvoiceProcessingGraph |
| TaxValidationAgent | InvoiceProcessingGraph |

---

## Tool: PANValidationTool

**Category:** Validation
**File:** `app/tools/validation/pan_validation_tool.py`

### Description
Validates PAN (Permanent Account Number) format and cross-references it against the PAN embedded in the vendor's GSTIN. Detects PAN mismatches that indicate GSTIN fraud.

### Purpose
Validate PAN format and detect inconsistencies between the standalone PAN and the PAN embedded in the GSTIN. A PAN-GSTIN mismatch is a critical compliance flag.

### Responsibilities
- Validate 10-character PAN format: `[A-Z]{5}[0-9]{4}[A-Z]{1}`
- Validate PAN entity type from 4th character (P=Person, C=Company, F=Firm, H=HUF, A=AOP, B=BOI, G=Government, J=Artificial Juridical Person, L=Local Authority, T=Trust)
- Cross-reference PAN with the PAN embedded in vendor GSTIN (characters 3–12)

### Input Model
```
PANValidationInput:
  pan: str | None
  gstin: str | None           # to extract and compare embedded PAN
  entity_type_expected: str | None
  document_id: UUID
```

### Output Model
```
PANValidationResult:
  success: bool
  pan_format_valid: bool
  entity_type: str | None       # P / C / F / H / ...
  entity_type_matches_expected: bool | None
  pan_gstin_consistent: bool | None   # True if PAN matches embedded GSTIN PAN
  extracted_pan_from_gstin: str | None
  results: List[ValidationResult]
  overall_status: str
```

### Dependencies
- `ConfigurationTool`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| UniversalValidationAgent | InvoiceProcessingGraph |
| TaxValidationAgent | InvoiceProcessingGraph |

---

## Tool: ArithmeticValidationTool

**Category:** Validation
**File:** `app/tools/validation/arithmetic_validation_tool.py`

### Description
Verifies the arithmetic integrity of the invoice: that line items sum to the subtotal, that taxes are correctly calculated, and that the total equals subtotal + tax - discount.

### Purpose
Detect invoice arithmetic errors or manipulations before payment. A common fraud vector is altering total amounts without adjusting line items. This tool is the financial integrity check.

### Responsibilities
- Sum all line item amounts and compare to extracted subtotal
- Verify tax amounts against declared tax rates
- Verify total = subtotal + tax_amount - discount
- Compute variance for each check
- Apply configurable tolerance for rounding differences

### MUST Do
- Use `Decimal` arithmetic throughout — never float
- Report the exact variance, not just pass/fail
- Apply rounding tolerance before failing (configurable per currency)

### MUST NEVER Do
- Correct arithmetic errors — only report them
- Make assumptions about tax rates — use only extracted values

### Input Model
```
ArithmeticValidationInput:
  line_items: List[LineItem]
  subtotal: Decimal | None
  discount: Decimal | None
  tax_amount: Decimal | None
  total_amount: Decimal | None
  currency: str
  document_id: UUID
  tenant_id: str
```

### Output Model
```
ArithmeticValidationResult:
  success: bool
  line_items_sum: Decimal
  declared_subtotal: Decimal | None
  subtotal_variance: Decimal
  declared_tax: Decimal | None
  declared_total: Decimal | None
  computed_total: Decimal
  total_variance: Decimal
  within_tolerance: bool
  results: List[ValidationResult]
  overall_status: str
```

### Configuration
| Key | Default | Description |
|---|---|---|
| `arithmetic.tolerance_amount` | `0.01` | Max acceptable rounding variance |
| `arithmetic.tolerance_percent` | `0.001` | Percentage tolerance for large invoices |

### Dependencies
- `ConfigurationTool`
- `ValidationTool`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| UniversalValidationAgent | InvoiceProcessingGraph |

---

## Tool: DateValidationTool

**Category:** Validation
**File:** `app/tools/validation/date_validation_tool.py`

### Description
Validates date fields on the invoice: invoice date is not in the future, due date is after invoice date, invoice is within the processing window (not too old), and dates are consistent with each other.

### Purpose
Catch common date errors (future-dated invoices, expired invoices, due date before invoice date) that would cause ERP posting failures.

### Responsibilities
- Validate invoice_date is not in the future
- Validate due_date >= invoice_date
- Validate invoice is within configurable lookback window
- Validate payment terms are consistent with due_date
- Validate fiscal year consistency

### Input Model
```
DateValidationInput:
  invoice_date: date | None
  due_date: date | None
  payment_terms: str | None
  document_id: UUID
  tenant_id: str
```

### Output Model
```
DateValidationResult:
  success: bool
  invoice_date_valid: bool
  due_date_valid: bool
  is_within_lookback_window: bool
  payment_terms_consistent: bool | None
  results: List[ValidationResult]
  overall_status: str
```

### Configuration
| Key | Default | Description |
|---|---|---|
| `date.lookback_days` | `365` | Max age of acceptable invoice |
| `date.future_tolerance_days` | `0` | Allow invoices up to N days in future |

### Used By
| Agent | Graph |
|---|---|
| UniversalValidationAgent | InvoiceProcessingGraph |

---

## Tool: CurrencyValidationTool

**Category:** Validation
**File:** `app/tools/validation/currency_validation_tool.py`

### Description
Validates currency codes, ensures consistency of currency across line items, and validates that the invoice currency is an accepted currency for the tenant.

### Input Model
```
CurrencyValidationInput:
  currency: str | None
  line_item_currencies: List[str]
  document_id: UUID
  tenant_id: str
```

### Output Model
```
CurrencyValidationResult:
  success: bool
  currency_valid: bool
  is_accepted_currency: bool
  is_consistent: bool         # all line items same currency
  normalised_currency: str | None
  results: List[ValidationResult]
```

### Configuration
| Key | Default | Description |
|---|---|---|
| `currency.accepted` | `["INR", "USD", "EUR"]` | Accepted currency codes |

### Used By
| Agent | Graph |
|---|---|
| UniversalValidationAgent | InvoiceProcessingGraph |

---

## Tool: InvoiceNumberValidationTool

**Category:** Validation
**File:** `app/tools/validation/invoice_number_validation_tool.py`

### Description
Validates the invoice number format against vendor-specific or global patterns. Detects obviously invalid or placeholder invoice numbers.

### Responsibilities
- Check invoice number is non-empty and non-placeholder ("NA", "N/A", "TBD", "000")
- Apply vendor-specific format patterns where configured
- Validate length within acceptable range
- Detect sequential numbering gaps (future: fraud detection signal)

### Input Model
```
InvoiceNumberInput:
  invoice_number: str | None
  vendor_id: UUID | None
  document_id: UUID
  tenant_id: str
```

### Output Model
```
InvoiceNumberResult:
  success: bool
  is_valid: bool
  is_placeholder: bool
  format_matches_vendor_pattern: bool | None
  results: List[ValidationResult]
```

### Used By
| Agent | Graph |
|---|---|
| UniversalValidationAgent | InvoiceProcessingGraph |

---

## Tool: TaxValidationTool

**Category:** Validation
**File:** `app/tools/validation/tax_validation_tool.py`

### Description
Validates TDS (Tax Deducted at Source) applicability, TDS rate selection, TDS calculation, and GST rate correctness. India-specific, but designed with country config abstraction so other countries can add their tax rules without code changes.

### Purpose
Ensure tax calculations on the invoice are correct before ERP posting. Incorrect TDS rates are a common compliance issue that results in penalties.

### Responsibilities
- Determine if TDS applies based on vendor category and invoice amount
- Select correct TDS section (194C, 194J, etc.) based on vendor category
- Validate declared TDS amount matches computed TDS
- Validate GST rates are applicable for the HSN/SAC codes
- Compute net payable after TDS deduction

### MUST Do
- Read TDS rates and thresholds from `country_config.yaml` — never hardcode
- Support vendor-category-specific TDS sections
- Return computed TDS as evidence regardless of pass/fail

### Input Model
```
TaxValidationInput:
  vendor_gstin: str | None
  vendor_pan: str | None
  vendor_category: str | None      # loaded from vendor master
  invoice_amount: Decimal
  declared_tax_amount: Decimal | None
  declared_tds_amount: Decimal | None
  line_items: List[LineItem]
  country_code: str = "IN"
  document_id: UUID
  tenant_id: str
```

### Output Model
```
TaxValidationResult:
  success: bool
  tds_applicable: bool
  applicable_tds_section: str | None   # "194C" / "194J" / etc.
  applicable_tds_rate: Decimal | None
  computed_tds_amount: Decimal | None
  declared_tds_amount: Decimal | None
  tds_variance: Decimal | None
  tds_valid: bool
  gst_valid: bool
  net_payable: Decimal | None
  results: List[ValidationResult]
  overall_status: str
```

### Public Methods
| Method | Description |
|---|---|
| `validate(input)` | Full tax validation |
| `compute_tds(amount, rate, threshold)` | TDS calculation |
| `determine_tds_section(vendor_category)` | Select applicable TDS section |
| `validate_gst_rates(line_items)` | Validate HSN/SAC → GST rate mapping |

### Dependencies
- `ConfigurationTool` — reads `country_config.yaml` TDS sections and rates
- `ValidationTool`
- `LoggingTool`
- `AuditTool`

### Audit Events
| Event | Trigger |
|---|---|
| `TAX_VALIDATION_COMPLETED` | After validation |
| `TDS_MISMATCH_DETECTED` | TDS variance exceeds tolerance |

### Used By
| Agent | Graph |
|---|---|
| TaxValidationAgent | InvoiceProcessingGraph |
| PaymentAgent | InvoiceProcessingGraph |

---

## Tool: DuplicateDetectionTool

**Category:** Validation
**File:** `app/tools/validation/duplicate_detection_tool.py`

### Description
Detects duplicate invoice submissions by comparing the current invoice against recent invoices in the database. Uses a multi-level detection strategy: exact match first, then near-duplicate similarity scoring.

### Purpose
Prevent double-payment — one of the most costly AP errors. Detects both exact duplicates (same invoice number) and near-duplicates (same invoice, different submission).

### Responsibilities
- Level 1: Exact match on (invoice_number + vendor_id + amount)
- Level 2: Hash match on document content (same file re-uploaded)
- Level 3: Near-duplicate scoring on (vendor_id + amount + date within tolerance)
- Return similarity score and which fields matched

### MUST Do
- Check against a configurable lookback window (not all history)
- Return the document_id of the suspected duplicate
- Provide field-level comparison evidence
- Return NEAR_DUPLICATE with score for human review (not auto-reject)

### MUST NEVER Do
- Auto-reject near-duplicates — escalate to human review
- Query more records than `duplicate.lookback_days` window

### Input Model
```
DuplicateDetectionInput:
  invoice_number: str | None
  vendor_id: UUID
  total_amount: Decimal
  invoice_date: date | None
  document_sha256: str
  document_id: UUID
  tenant_id: str
```

### Output Model
```
DuplicateDetectionResult:
  success: bool
  is_exact_duplicate: bool
  is_near_duplicate: bool
  is_content_duplicate: bool
  similarity_score: float             # 0.0–1.0
  suspected_duplicate_id: UUID | None
  matched_fields: Dict[str, any]      # field → matched value
  comparison_details: List[FieldComparison]
  verdict: str                        # UNIQUE / EXACT_DUPLICATE / NEAR_DUPLICATE
  recommendation: str
```

### Public Methods
| Method | Description |
|---|---|
| `detect(input)` | Full duplicate detection |
| `exact_match(invoice_number, vendor_id, amount)` | Level 1 check |
| `content_hash_match(sha256)` | Level 2 check |
| `near_duplicate_score(input)` | Level 3 similarity scoring |

### Dependencies
- `DocumentRepository` — queries recent invoices
- `HashTool` — for content hash comparison
- `ComparisonTool` — similarity scoring
- `ConfigurationTool` — reads `duplicate.lookback_days`, `duplicate.similarity_threshold`
- `LoggingTool`
- `AuditTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `duplicate.lookback_days` | `365` | Days of history to check |
| `duplicate.exact_match_fields` | `[invoice_number, vendor_id, total_amount]` | Exact match keys |
| `duplicate.near_duplicate_threshold` | `0.90` | Score above which = NEAR_DUPLICATE |

### Audit Events
| Event | Trigger |
|---|---|
| `DUPLICATE_DETECTED` | Exact or near-duplicate found |
| `UNIQUE_CONFIRMED` | No duplicate found |

### Used By
| Agent | Graph |
|---|---|
| DuplicateDetectionAgent | InvoiceProcessingGraph |

---

## Tool: ToleranceValidationTool

**Category:** Validation
**File:** `app/tools/validation/tolerance_validation_tool.py`

### Description
Evaluates whether a variance between two values (extracted vs. expected, invoice vs. PO) is within the configured tolerance band. Tolerances are configurable per business profile and field type.

### Purpose
Apply configurable tolerance to variance checks so that minor rounding differences do not cause unnecessary exceptions while genuine discrepancies are still caught.

### Responsibilities
- Accept a computed variance and evaluate it against configured tolerance
- Support both absolute (`±0.01`) and percentage (`±2.5%`) tolerances
- Return both the variance and the tolerance applied

### Input Model
```
ToleranceValidationInput:
  field_name: str
  computed_value: Decimal
  reference_value: Decimal
  business_profile: str | None
  tenant_id: str
```

### Output Model
```
ToleranceValidationResult:
  success: bool
  variance: Decimal
  variance_percent: Decimal
  tolerance_absolute: Decimal
  tolerance_percent: Decimal
  within_tolerance: bool
  verdict: str    # WITHIN_TOLERANCE / TOLERANCE_BREACH
```

### Dependencies
- `ConfigurationTool` — reads `tolerance_config.yaml`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| POMatchingAgent | InvoiceProcessingGraph |
| ArithmeticValidationTool (composed) | InvoiceProcessingGraph |

---

## Tool: BusinessRuleTool

**Category:** Validation
**File:** `app/tools/validation/business_rule_tool.py`

### Description
Evaluates business rules defined in `business_rules.yaml` against a data payload. Each rule is a named, versioned, configurable condition — no rule logic is hardcoded. Supports ALL rule types needed by the platform.

### Purpose
Externalise all business decision logic from code into YAML configuration. A new business rule is added in YAML — no code change, no deployment required.

### Responsibilities
- Load rule sets by name from configuration
- Evaluate each rule using the ValidationTool engine
- Support rule types: presence, format, range, comparison, arithmetic, cross-field
- Support rule chaining (rule B only runs if rule A passed)
- Return which rules fired and their results

### MUST Do
- Support rule versioning — each rule set has a version string
- Support precondition guards on individual rules
- Return which specific rule IDs fired for audit trail

### Input Model
```
BusinessRuleInput:
  rule_set_name: str      # e.g. "PO_RAW_MATERIAL_VALIDATION"
  data: dict
  document_id: UUID
  tenant_id: str
```

### Output Model
```
BusinessRuleResult:
  success: bool
  rule_set_name: str
  rule_set_version: str
  rules_evaluated: int
  rules_passed: int
  rules_failed: int
  rules_skipped: int
  triggered_rules: List[str]      # rule IDs that fired
  overall_status: str
  results: List[ValidationResult]
```

### Public Methods
| Method | Description |
|---|---|
| `evaluate(input)` | Run a named rule set |
| `load_rule_set(name, tenant_id)` | Load rules with tenant override |
| `list_rule_sets()` | List available rule set names |
| `get_rule_set_version(name)` | Get current version |

### Dependencies
- `ValidationTool`
- `ConfigurationTool`
- `LoggingTool`

### Future Extensions
- Visual rule editor in Admin UI (edit YAML via GUI)
- Rule simulation mode (preview impact before activating)
- Per-vendor rule overrides

### Used By
| Agent | Graph |
|---|---|
| UniversalValidationAgent | InvoiceProcessingGraph |
| ProfileValidationAgent | InvoiceProcessingGraph |
| BusinessProfileAgent | InvoiceProcessingGraph |
| DecisionAgent | InvoiceProcessingGraph |

---

## Tool: ProfileValidationTool

**Category:** Validation
**File:** `app/tools/validation/profile_validation_tool.py`

### Description
Applies the complete set of validation rules specific to the detected business profile. Composes MandatoryFieldTool and BusinessRuleTool with the profile's rule set. This is the profile-aware validation orchestrator.

### Purpose
Ensure that all profile-specific requirements are met. A PO_RAW_MATERIAL invoice has different validation requirements than a PETTY_CASH invoice — this tool loads and applies the correct requirements.

### Responsibilities
- Load profile-specific mandatory fields from config
- Load profile-specific validation rules from config
- Run mandatory field check (MandatoryFieldTool)
- Run profile business rules (BusinessRuleTool)
- Aggregate results into a single ProfileValidationResult

### Input Model
```
ProfileValidationInput:
  extraction_result: ExtractionResult
  business_profile: str
  document_id: UUID
  tenant_id: str
```

### Output Model
```
ProfileValidationResult:
  success: bool
  business_profile: str
  mandatory_field_check: MandatoryFieldResult
  rule_evaluation: BusinessRuleResult
  overall_status: str
  profile_rules_version: str
  compliance_flags: List[str]     # specific compliance concerns
```

### Dependencies
- `MandatoryFieldTool`
- `BusinessRuleTool`
- `ConfigurationTool`
- `LoggingTool`
- `AuditTool`

### Audit Events
| Event | Trigger |
|---|---|
| `PROFILE_VALIDATION_COMPLETED` | After validation |

### Used By
| Agent | Graph |
|---|---|
| ProfileValidationAgent | InvoiceProcessingGraph |

---

## Tool: VendorValidationTool

**Category:** Validation
**File:** `app/tools/validation/vendor_validation_tool.py`

### Description
Validates vendor-related fields on the invoice: GSTIN consistency with vendor master, PAN consistency, vendor blacklist check, and vendor active status.

### Responsibilities
- Cross-reference invoice vendor GSTIN against vendor master GSTIN
- Validate vendor is not on blacklist
- Validate vendor is in ACTIVE status
- Validate vendor's registered state matches GSTIN state code

### Input Model
```
VendorValidationInput:
  extracted_vendor_name: str | None
  extracted_vendor_gstin: str | None
  matched_vendor_id: UUID | None
  document_id: UUID
  tenant_id: str
```

### Output Model
```
VendorValidationResult:
  success: bool
  gstin_matches_master: bool | None
  vendor_is_active: bool | None
  vendor_is_blacklisted: bool
  state_consistent: bool | None
  results: List[ValidationResult]
  overall_status: str
```

### Dependencies
- `VendorRepository`
- `GSTValidationTool`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| ProfileValidationAgent | InvoiceProcessingGraph |

---

*END OF VALIDATION TOOLS*

---

# MATCHING TOOLS

---

## Tool: VendorMatchingTool

**Category:** Matching
**File:** `app/tools/matching/vendor_matching_tool.py`

### Description
Matches the vendor name extracted from the invoice against the vendor master database using a multi-strategy cascade: exact GSTIN match → exact name match → fuzzy name match → PAN match. Returns the best match with a confidence score and the matching strategy used.

### Purpose
Reliably identify the correct vendor record for every invoice, even when vendor names are abbreviated, misspelled, or vary across invoices from the same vendor.

### Responsibilities
- Execute matching strategies in priority order
- Return the vendor_id, match score, and strategy that produced the match
- Return NO_MATCH with suggestions when no strategy succeeds
- Support fuzzy matching using configurable similarity algorithm

### MUST Do
- Try strategies in order: GSTIN → PAN → EXACT_NAME → FUZZY_NAME
- Stop at first strategy that exceeds the match threshold
- Return the match score for every strategy attempted
- Never return a match below the minimum acceptable score

### MUST NEVER Do
- Create new vendor records — only match or report NO_MATCH
- Make a network call to an external vendor database

### Input Model
```
VendorMatchingInput:
  vendor_name: str | None
  vendor_gstin: str | None
  vendor_pan: str | None
  document_id: UUID
  tenant_id: str
```

### Output Model
```
VendorMatchingResult:
  success: bool
  is_matched: bool
  matched_vendor_id: UUID | None
  matched_vendor_name: str | None
  match_score: float
  match_strategy: str             # GSTIN / PAN / EXACT_NAME / FUZZY_NAME
  all_strategy_scores: Dict[str, float]
  suggestions: List[VendorSuggestion] | None   # top 3 near-matches for human
  evidence: dict

VendorSuggestion:
  vendor_id: UUID
  vendor_name: str
  gstin: str
  similarity_score: float
```

### Public Methods
| Method | Description |
|---|---|
| `match(input)` | Full matching cascade |
| `match_by_gstin(gstin, tenant_id)` | GSTIN-exact match |
| `match_by_pan(pan, tenant_id)` | PAN-exact match |
| `match_by_name_exact(name, tenant_id)` | Exact name match |
| `match_by_name_fuzzy(name, tenant_id)` | Fuzzy name match |

### Internal Helpers
- `_normalise_for_comparison(name)` — lowercase, strip punctuation, expand common abbreviations

### Dependencies
- `VendorRepository`
- `SimilarityTool`
- `ComparisonTool`
- `ConfigurationTool` — reads `vendor.match_threshold`, `vendor.fuzzy_algorithm`
- `LoggingTool`
- `AuditTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `vendor.match_threshold` | `0.85` | Minimum score to accept a match |
| `vendor.fuzzy_algorithm` | `rapidfuzz` | Fuzzy matching library |
| `vendor.suggestion_count` | `3` | Number of near-match suggestions to return |

### Audit Events
| Event | Trigger |
|---|---|
| `VENDOR_MATCHED` | Successful match |
| `VENDOR_NOT_FOUND` | No match above threshold |

### Used By
| Agent | Graph |
|---|---|
| VendorMatchingAgent | InvoiceProcessingGraph |

---

## Tool: POMatchingTool

**Category:** Matching
**File:** `app/tools/matching/po_matching_tool.py`

### Description
Matches the invoice against the Purchase Order referenced on the invoice. Validates that the PO exists, is open, belongs to the matched vendor, and has sufficient remaining value to cover the invoice.

### Purpose
Enforce the purchase order control — only invoices that reference valid, open POs with sufficient remaining value should be processed without exception.

### Responsibilities
- Look up the PO by the reference number on the invoice
- Validate PO status (OPEN / CLOSED / CANCELLED)
- Validate PO belongs to the matched vendor
- Validate PO has sufficient remaining value
- Return PO line items for three-way matching

### MUST Do
- Check PO status before value comparison
- Return the remaining PO value for context
- Distinguish between profile-allowed NO_PO and unexpected NO_PO

### Input Model
```
POMatchingInput:
  po_reference: str | None
  vendor_id: UUID
  invoice_amount: Decimal
  business_profile: str
  document_id: UUID
  tenant_id: str
```

### Output Model
```
POMatchingResult:
  success: bool
  po_found: bool
  po_id: UUID | None
  po_status: str | None           # OPEN / CLOSED / CANCELLED
  po_vendor_matches: bool | None
  po_remaining_value: Decimal | None
  po_line_items: List[POLineItem] | None
  invoice_exceeds_po_value: bool | None
  skip_reason: str | None         # "PROFILE_DOES_NOT_REQUIRE_PO"
  verdict: str                    # MATCHED / NO_PO / PO_CLOSED / PO_WRONG_VENDOR / SKIP
```

### Dependencies
- `PORepository`
- `ConfigurationTool` — reads which profiles require PO
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| POMatchingAgent | InvoiceProcessingGraph |

---

## Tool: GRNMatchingTool

**Category:** Matching
**File:** `app/tools/matching/grn_matching_tool.py`

### Description
Retrieves all Goods Receipt Notes (GRNs) associated with the matched PO and computes the total received quantity and value. Provides the GRN data required for three-way matching.

### Purpose
Enable three-way matching by providing verified goods receipt data. The GRN is the authoritative record of what was actually received.

### Responsibilities
- Retrieve all GRNs for a given PO
- Aggregate total received quantity and value per line item
- Identify pending (unmatched) GRN quantities
- Detect partial deliveries

### Input Model
```
GRNMatchingInput:
  po_id: UUID
  po_line_items: List[POLineItem]
  document_id: UUID
  tenant_id: str
```

### Output Model
```
GRNMatchingResult:
  success: bool
  grn_count: int
  grns: List[GRNRecord]
  total_received_quantity_by_line: Dict[str, Decimal]
  total_received_value: Decimal
  pending_quantity: Decimal
  is_fully_received: bool
```

### Dependencies
- `GRNRepository`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| POMatchingAgent | InvoiceProcessingGraph |

---

## Tool: ThreeWayMatchingTool

**Category:** Matching
**File:** `app/tools/matching/three_way_matching_tool.py`

### Description
Performs the core three-way match: Invoice vs. Purchase Order vs. Goods Receipt Note. Computes variances at the line-item level and the header level. Applies tolerance rules. Returns a definitive match verdict.

### Purpose
Automate the three-way match that is the heart of purchase-order-based AP processing. Reduces the most labour-intensive AP activity to a configuration-driven comparison.

### Responsibilities
- Compare invoice line items to PO line items by description/code
- Compare invoice quantities to GRN received quantities
- Compare invoice values to PO values
- Apply tolerance per profile per field
- Classify match result: FULL_MATCH / WITHIN_TOLERANCE / TOLERANCE_BREACH / PARTIAL_MATCH

### MUST Do
- Match at line-item level, not just header totals
- Apply tolerance for quantity and value separately
- Return full comparison table for every line item

### Input Model
```
ThreeWayMatchInput:
  invoice_line_items: List[LineItem]
  invoice_total: Decimal
  po_line_items: List[POLineItem]
  po_value: Decimal
  grn_quantities: Dict[str, Decimal]
  business_profile: str
  document_id: UUID
  tenant_id: str
```

### Output Model
```
ThreeWayMatchResult:
  success: bool
  match_type: str       # THREE_WAY / TWO_WAY / NO_MATCH
  overall_verdict: str  # FULL_MATCH / WITHIN_TOLERANCE / TOLERANCE_BREACH / PARTIAL
  line_item_results: List[LineItemMatchResult]
  quantity_variance: Decimal
  value_variance: Decimal
  within_tolerance: bool
  tolerance_applied: ToleranceConfig
  unmatched_invoice_lines: List[LineItem]
  unmatched_po_lines: List[POLineItem]

LineItemMatchResult:
  invoice_line: LineItem
  po_line: POLineItem | None
  grn_quantity: Decimal | None
  quantity_variance: Decimal | None
  value_variance: Decimal | None
  match_status: str    # MATCHED / OVER / UNDER / UNMATCHED
```

### Dependencies
- `ToleranceValidationTool`
- `ComparisonTool`
- `ConfigurationTool`
- `LoggingTool`
- `AuditTool`

### Audit Events
| Event | Trigger |
|---|---|
| `THREE_WAY_MATCH_COMPLETED` | After match |
| `TOLERANCE_BREACH_DETECTED` | Variance exceeds tolerance |

### Used By
| Agent | Graph |
|---|---|
| POMatchingAgent | InvoiceProcessingGraph |

---

## Tool: ComparisonTool

**Category:** Matching
**File:** `app/tools/matching/comparison_tool.py`

### Description
Provides a set of typed comparison primitives used by all matching tools. Supports string comparison, decimal comparison, date comparison, and list comparison — all with configurable strategies.

### Purpose
Centralise all value comparison logic. Ensures consistent comparison behaviour across vendor matching, PO matching, duplicate detection, and arithmetic validation.

### Responsibilities
- String comparison: exact, case-insensitive, normalised, fuzzy
- Decimal comparison: exact, percentage tolerance, absolute tolerance
- Date comparison: exact, within N days
- List comparison: subset, intersection

### MUST Do
- Always return the comparison method used
- Return a similarity score (0.0–1.0) for all comparisons
- Use `Decimal` for all numeric comparisons

### Input Model
```
ComparisonInput:
  value_a: Any
  value_b: Any
  strategy: str        # EXACT / FUZZY / PERCENTAGE / ABSOLUTE / DATE_PROXIMITY
  tolerance: float | None
  data_type: str       # STRING / DECIMAL / DATE / LIST
```

### Output Model
```
ComparisonResult:
  is_equal: bool
  similarity_score: float
  strategy_used: str
  difference: Any | None     # numeric diff for DECIMAL, char diff for STRING
  tolerance_applied: float | None
  within_tolerance: bool | None
```

### Public Methods
| Method | Description |
|---|---|
| `compare(input)` | General-purpose compare |
| `compare_strings(a, b, strategy)` | String comparison |
| `compare_decimals(a, b, tolerance)` | Decimal comparison |
| `compare_dates(a, b, tolerance_days)` | Date comparison |
| `fuzzy_score(a, b)` | Returns 0–1 similarity |

### Dependencies
- `rapidfuzz` — fuzzy string matching
- `LoggingTool`

### Used By
All matching tools and DuplicateDetectionTool

---

## Tool: SimilarityTool

**Category:** Matching
**File:** `app/tools/matching/similarity_tool.py`

### Description
Computes similarity scores between strings using multiple algorithms. Returns the best score and the algorithm that produced it. Used primarily by VendorMatchingTool for name similarity.

### Purpose
Provide a robust, multi-algorithm similarity scoring service. No single fuzzy matching algorithm is optimal for all vendor name variations — this tool tries multiple and returns the best.

### Responsibilities
- Compute similarity using Levenshtein, Jaro-Winkler, Token Sort Ratio, and Token Set Ratio
- Return the highest score and corresponding algorithm
- Support abbreviation expansion before comparison

### Input Model
```
SimilarityInput:
  text_a: str
  text_b: str
  algorithms: List[str] = ["all"]
  expand_abbreviations: bool = True
```

### Output Model
```
SimilarityResult:
  best_score: float
  best_algorithm: str
  all_scores: Dict[str, float]
```

### Dependencies
- `rapidfuzz`
- `LoggingTool`

### Used By
VendorMatchingTool, DuplicateDetectionTool

---

## Tool: VarianceTool

**Category:** Matching
**File:** `app/tools/matching/variance_tool.py`

### Description
Computes absolute and percentage variance between two numeric values, and classifies the variance against configured tolerance bands. Used across matching, arithmetic validation, and tax validation.

### Input Model
```
VarianceInput:
  value_a: Decimal        # reference/expected value
  value_b: Decimal        # actual/computed value
  field_name: str
  tolerance_config: ToleranceConfig | None
```

### Output Model
```
VarianceResult:
  absolute_variance: Decimal
  percentage_variance: Decimal
  is_within_tolerance: bool
  variance_direction: str    # OVER / UNDER / EQUAL
  tolerance_absolute: Decimal | None
  tolerance_percent: Decimal | None
```

### Used By
ThreeWayMatchingTool, ArithmeticValidationTool, TaxValidationTool

---

## Tool: BlanketPOTool

**Category:** Matching
**File:** `app/tools/matching/blanket_po_tool.py`

### Description
Handles matching against Blanket Purchase Orders (framework agreements with a total value but multiple delivery calls). Validates that cumulative invoiced amount does not exceed the blanket PO value.

### Responsibilities
- Identify if a PO is a blanket/framework PO
- Retrieve total previously invoiced against this blanket PO
- Validate current invoice does not exceed remaining blanket value
- Return cumulative utilisation percentage

### Input Model
```
BlanketPOInput:
  po_id: UUID
  current_invoice_amount: Decimal
  document_id: UUID
  tenant_id: str
```

### Output Model
```
BlanketPOResult:
  success: bool
  is_blanket_po: bool
  blanket_po_value: Decimal | None
  previously_invoiced: Decimal | None
  remaining_value: Decimal | None
  current_utilisation_percent: Decimal | None
  would_exceed: bool | None
```

### Dependencies
- `PORepository`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| POMatchingAgent | InvoiceProcessingGraph |

---

## Tool: ContractMatchingTool

**Category:** Matching
**File:** `app/tools/matching/contract_matching_tool.py`

### Description
Matches invoices against long-term contracts (applicable to LEASE_RENT and NON_PO_CAPEX profiles). Validates invoice amounts and terms against the contract terms.

### Responsibilities
- Look up contract by vendor and invoice reference
- Validate invoice amount against contracted rate
- Validate invoice period against contract validity dates
- Detect over-invoicing against contract value

### Input Model
```
ContractMatchingInput:
  vendor_id: UUID
  invoice_amount: Decimal
  invoice_date: date
  contract_reference: str | None
  document_id: UUID
  tenant_id: str
```

### Output Model
```
ContractMatchingResult:
  success: bool
  contract_found: bool
  contract_id: UUID | None
  amount_matches_contract: bool | None
  contract_is_active: bool | None
  rate_variance: Decimal | None
  verdict: str
```

### Dependencies
- `ContractRepository`
- `ToleranceValidationTool`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| POMatchingAgent | InvoiceProcessingGraph |

---

*END OF MATCHING TOOLS*

---

# ERP TOOLS

---

## Tool: ERPAdapterTool

**Category:** ERP
**File:** `app/tools/erp/erp_adapter_tool.py`

### Description
Provider-agnostic ERP integration interface. The single entry point through which all ERP operations flow. Selects the configured provider (Mock / SAP / Oracle / Dynamics / NetSuite) and delegates operations to the appropriate adapter. No agent or graph ever references a specific ERP implementation.

### Purpose
Enforce ERP provider abstraction so that switching from Mock ERP to SAP requires only a configuration change — zero agent code changes, zero graph changes, zero tool logic changes.

### Responsibilities
- Route all ERP operations to the active provider
- Normalise provider-specific errors to standard ERP error codes
- Log every ERP operation with provider name and request ID
- Return normalised `ERPResult` regardless of provider

### MUST Do
- Read `erp.provider` from config to select active adapter
- Never import a concrete ERP SDK — always use the injected `ERPProviderInterface`
- Return `ERPResult` with the provider name in every case
- Log the full request payload hash and response reference for audit

### MUST NEVER Do
- Contain SAP BAPI names, Oracle function names, or any ERP-specific constants
- Retry ERP calls — RetryTool handles that at the agent level

### Input Model
```
ERPOperationInput:
  operation: str              # POST_INVOICE / GET_STATUS / REVERSE / GET_COST_CENTERS / GET_GL_ACCOUNTS
  payload: ERPPayload | None
  reference: str | None       # ERP document number for GET_STATUS / REVERSE
  tenant_id: str
  document_id: UUID
```

### Output Model
```
ERPResult:
  success: bool
  operation: str
  provider: str               # "mock" | "sap" | "oracle" | "dynamics" | "netsuite"
  erp_document_number: str | None
  erp_response_reference: str | None   # provider's request tracking ID
  posted_at: datetime | None
  status: str | None
  error_code: str | None      # ERP_UNAVAILABLE / VALIDATION_ERROR / DUPLICATE_DOCUMENT
  error_message: str | None
  raw_response: dict | None   # provider response (sanitised for logging)
```

### Public Methods
| Method | Description |
|---|---|
| `execute(input)` | Route operation to active provider |
| `get_active_provider()` | Return name of active provider |
| `health_check()` | Verify ERP connectivity |
| `get_cost_centers(tenant_id)` | Retrieve cost centre list |
| `get_gl_accounts(tenant_id)` | Retrieve GL account list |

### Dependencies
- `ERPProviderInterface` — injected provider (Mock / SAP / Oracle)
- `ConfigurationTool` — reads `erp.provider`
- `LoggingTool`
- `AuditTool`

### Audit Events
| Event | Trigger |
|---|---|
| `ERP_POSTING_INITIATED` | Before provider call |
| `ERP_POSTING_COMPLETED` | Successful posting |
| `ERP_POSTING_FAILED` | Provider error |
| `ERP_REVERSAL_COMPLETED` | Successful reversal |

### Used By
| Agent | Graph |
|---|---|
| ERPPostingAgent | InvoiceProcessingGraph |

---

## Tool: MockERPTool

**Category:** ERP
**File:** `app/tools/erp/mock_erp_provider.py`

### Description
Implements `ERPProviderInterface` using PostgreSQL as the mock ERP backend. Simulates ERP posting, status queries, and reversals using the platform's own database. Used in development, demonstration, and pre-integration testing.

### Purpose
Allow the full invoice pipeline to function end-to-end without a real ERP system. Enable client demonstrations and testing of all 19 agents without ERP setup.

### Responsibilities
- Insert an `erp_postings` record for every POST_INVOICE operation
- Generate a deterministic mock document number (`MOCK-{year}-{sequence}`)
- Simulate configurable posting delay for realistic demos
- Support status queries and reversals

### MUST Do
- Generate unique document numbers (never duplicate within tenant)
- Support configurable `mock.posting_delay_ms` for realistic simulation
- Return success for all valid payloads

### MUST NEVER Do
- Be used in production without explicit `erp.allow_mock_in_production=false` guard
- Store sensitive vendor payment data differently than other ERP adapters

### Input
Conforms to `ERPProviderInterface` — accepts `ERPPayload`.

### Output
Returns `ERPResult` with `provider="mock"`.

### Dependencies
- `ERPRepository` (mock_erp_postings table)
- `ConfigurationTool` — reads `mock.posting_delay_ms`
- `LoggingTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `mock.posting_delay_ms` | `200` | Simulated ERP latency |
| `erp.allow_mock_in_production` | `false` | Safety guard |

### Used By
ERPAdapterTool only

---

## Tool: SAPAdapterTool

**Category:** ERP
**File:** `app/tools/erp/sap_provider.py`

### Description
Implements `ERPProviderInterface` for SAP S/4HANA. Maps the universal `ERPPayload` to the BAPI_INCOMINGINVOICE_CREATE SAP BAPI structure. Currently a stub — architecture is defined, implementation is pending client engagement.

### Purpose
Enable SAP integration by implementing the pre-defined interface. When a client uses SAP, only this file changes — no agent, graph, or tool logic changes.

### Responsibilities
- Map `ERPPayload` → `BAPI_INCOMINGINVOICE_CREATE` structure
- Handle SAP return codes (S/E/W/I)
- Map SAP document numbers back to `ERPResult.erp_document_number`
- Handle SAP-specific error codes and translate to standard ERP error codes

### MUST Do
- Use SAP Managed Identity or SAP OAuth for authentication (no passwords in code)
- Map ALL ERPPayload fields to correct BAPI parameters
- Handle SAP return table (RETURN) messages

### MUST NEVER Do
- Hardcode SAP system IDs or client numbers — read from Key Vault
- Implement any business logic — map fields only

### SAP Field Mapping
| ERPPayload Field | BAPI Field | Notes |
|---|---|---|
| `vendor_erp_code` | `LIFNR` | Vendor number in SAP |
| `invoice_number` | `XBLNR` | External document number |
| `invoice_date` | `BLDAT` | Document date (YYYYMMDD) |
| `posting_date` | `BUDAT` | Posting date |
| `total_amount` | `GROSS_AMOUNT` | Gross invoice amount |
| `currency` | `WAERS` | Currency key |
| `gl_account` | `GL_ACCOUNT` | G/L account |
| `cost_center` | `KOSTL` | Cost centre |

### Dependencies
- `pyrfc` — SAP RFC/BAPI Python library (or SAP REST API client)
- SAP credentials from Azure Key Vault
- `ConfigurationTool`
- `LoggingTool`

### Current Status: STUB
Stub implementation returns `ERPResult(success=False, error_code="NOT_IMPLEMENTED")` until client engagement. All method signatures are defined and documented.

### Used By
ERPAdapterTool only

---

## Tool: OracleAdapterTool

**Category:** ERP
**File:** `app/tools/erp/oracle_provider.py`

### Description
Implements `ERPProviderInterface` for Oracle Fusion Financials (Cloud) and Oracle EBS. Maps `ERPPayload` to Oracle AP Invoice REST API (Fusion) or Open Interface (EBS). Currently a stub.

### Purpose
Enable Oracle ERP integration. Oracle is the second-most-common ERP in enterprise clients after SAP.

### Oracle Fusion REST Endpoint
```
POST /fscmRestApi/resources/11.13.18.05/invoices
```

### Field Mapping (Oracle Fusion)
| ERPPayload Field | Oracle Field | Notes |
|---|---|---|
| `vendor_erp_code` | `VendorNumber` | Supplier number |
| `invoice_number` | `InvoiceNumber` | |
| `invoice_date` | `InvoiceDate` | ISO 8601 |
| `total_amount` | `InvoiceAmount` | |
| `currency` | `InvoiceCurrencyCode` | |

### Current Status: STUB

### Used By
ERPAdapterTool only

---

## Tool: DynamicsAdapterTool

**Category:** ERP
**File:** `app/tools/erp/dynamics_provider.py`

### Description
Implements `ERPProviderInterface` for Microsoft Dynamics 365 Finance. Maps `ERPPayload` to the Dynamics 365 AP Invoice REST API. Currently a stub.

### Dynamics API Endpoint
```
POST /data/VendorInvoiceHeaders
```

### Current Status: STUB

### Used By
ERPAdapterTool only

---

## Tool: NetSuiteAdapterTool

**Category:** ERP
**File:** `app/tools/erp/netsuite_provider.py`

### Description
Implements `ERPProviderInterface` for NetSuite. Maps `ERPPayload` to the NetSuite REST/SuiteTalk API for vendor bill creation. Currently a stub.

### Current Status: STUB

### Used By
ERPAdapterTool only

---

## Tool: JournalBuilderTool

**Category:** ERP
**File:** `app/tools/erp/journal_builder_tool.py`

### Description
Constructs the accounting journal entry (debit/credit lines) from an approved invoice before ERP posting. Determines the correct GL accounts, cost centres, and profit centres based on business profile and vendor category.

### Purpose
Separate the accounting logic from ERP posting. The journal entry is a platform construct — independent of which ERP receives it.

### Responsibilities
- Generate debit line (expense account) based on business profile + cost centre
- Generate credit line (vendor payable account)
- Generate tax lines (input GST debit, TDS payable credit)
- Apply fiscal year and period determination
- Validate journal entry balances (debits = credits)

### MUST Do
- Always validate that the journal balances (sum of debits = sum of credits)
- Return the journal entry as ERPPayload for downstream ERP posting
- Never hardcode GL account numbers — read from config

### Input Model
```
JournalBuildInput:
  extraction_result: ExtractionResult
  tax_validation_result: TaxValidationResult
  vendor_id: UUID
  business_profile: str
  cost_center: str
  document_id: UUID
  tenant_id: str
```

### Output Model
```
JournalEntry:
  header: JournalHeader
  debit_lines: List[JournalLine]
  credit_lines: List[JournalLine]
  tax_lines: List[JournalLine]
  is_balanced: bool
  total_debit: Decimal
  total_credit: Decimal

JournalLine:
  gl_account: str
  cost_center: str
  profit_center: str
  amount: Decimal
  currency: str
  description: str
  tax_code: str | None
```

### Dependencies
- `ConfigurationTool` — reads GL account mapping by profile
- `TaxValidationTool`
- `LoggingTool`

### Configuration
Reads `erp.gl_mapping.{profile}.expense_account`, `erp.gl_mapping.{profile}.payable_account` from config.

### Used By
| Agent | Graph |
|---|---|
| ERPPostingAgent | InvoiceProcessingGraph |

---

## Tool: PostingTool

**Category:** ERP
**File:** `app/tools/erp/posting_tool.py`

### Description
Orchestrates the complete ERP posting sequence: journal construction → pre-posting validation → ERP adapter call → result recording. The single tool that agents call to post an invoice.

### Purpose
Provide agents with a single `post(input)` method that handles the complete posting pipeline. Agents should not need to call JournalBuilderTool and ERPAdapterTool separately.

### Responsibilities
- Call JournalBuilderTool to build the accounting entry
- Validate the journal balance before posting
- Call ERPAdapterTool to submit to the configured ERP
- Record the posting result in the database
- Handle idempotency — reject duplicate posting requests

### MUST Do
- Check for existing posting before attempting (idempotency guard)
- Record posting result atomically with the ERP response

### Input Model
```
PostingInput:
  extraction_result: ExtractionResult
  tax_result: TaxValidationResult
  approval_result: ApprovalRecord
  vendor_id: UUID
  business_profile: str
  document_id: UUID
  tenant_id: str
```

### Output Model
```
PostingResult:
  success: bool
  erp_document_number: str | None
  journal_entry: JournalEntry
  erp_result: ERPResult
  posting_timestamp: datetime
  idempotency_key: str
```

### Dependencies
- `JournalBuilderTool`
- `ERPAdapterTool`
- `ERPRepository`
- `LoggingTool`
- `AuditTool`

### Audit Events
| Event | Trigger |
|---|---|
| `ERP_POSTING_COMPLETED` | Successful post |
| `ERP_POSTING_DUPLICATE_BLOCKED` | Duplicate posting detected |

### Used By
| Agent | Graph |
|---|---|
| ERPPostingAgent | InvoiceProcessingGraph |

---

## Tool: PaymentScheduleTool

**Category:** ERP
**File:** `app/tools/erp/payment_schedule_tool.py`

### Description
Calculates payment due date, net payable amount (after TDS deduction), and schedules the payment in the ERP system's payment run. Produces the payment schedule record.

### Purpose
Automate payment scheduling so that approved invoices are automatically queued for payment by the correct due date, with correct TDS deduction applied.

### Responsibilities
- Calculate payment due date from invoice date + payment terms
- Apply TDS deduction to compute net payable
- Determine payment method from vendor master
- Create payment schedule record in ERP

### MUST Do
- Use `Decimal` arithmetic for all amount calculations
- Read payment terms mapping from configuration (e.g. "Net 30" → 30 days)
- Never schedule payment before approval is confirmed

### Input Model
```
PaymentScheduleInput:
  invoice_date: date
  payment_terms: str | None
  gross_amount: Decimal
  tds_amount: Decimal
  vendor_id: UUID
  erp_document_number: str
  document_id: UUID
  tenant_id: str
```

### Output Model
```
PaymentScheduleResult:
  success: bool
  due_date: date
  gross_amount: Decimal
  tds_deducted: Decimal
  net_payable: Decimal
  payment_method: str          # NEFT / RTGS / CHEQUE / IMPS
  payment_scheduled: bool
  payment_reference: str | None
```

### Dependencies
- `ConfigurationTool` — reads payment terms map
- `TaxValidationTool` — TDS computation
- `VendorRepository` — payment method preference
- `ERPAdapterTool` — payment schedule in ERP
- `LoggingTool`
- `AuditTool`

### Audit Events
| Event | Trigger |
|---|---|
| `PAYMENT_SCHEDULED` | Payment schedule created |

### Used By
| Agent | Graph |
|---|---|
| PaymentAgent | InvoiceProcessingGraph |

---

## Tool: VendorMasterTool

**Category:** ERP
**File:** `app/tools/erp/vendor_master_tool.py`

### Description
Manages vendor master data synchronisation between the platform database and the connected ERP system. When an ERP is connected, the vendor master is the system of record in the ERP.

### Purpose
Ensure vendor data in the platform always reflects the ERP vendor master. Enables cross-referencing of platform vendor IDs with ERP vendor codes.

### Responsibilities
- Look up vendor by ERP vendor code
- Sync vendor payment details from ERP
- Create new vendor in ERP when a new vendor is onboarded in the platform

### Current Behaviour (Mock ERP)
Reads and writes to the platform's own `vendors` table.

### Future Behaviour (SAP)
Calls `BAPI_VENDOR_GETDETAIL` for reads and `BAPI_VENDOR_CREATE` for creates.

### Input Model
```
VendorMasterInput:
  operation: str          # GET / SYNC / CREATE
  vendor_id: UUID | None
  erp_vendor_code: str | None
  tenant_id: str
```

### Output Model
```
VendorMasterResult:
  success: bool
  vendor_id: UUID | None
  erp_vendor_code: str | None
  vendor_data: dict | None
  synced_at: datetime | None
```

### Dependencies
- `ERPAdapterTool`
- `VendorRepository`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| VendorMatchingAgent | InvoiceProcessingGraph |

---

## Tool: PurchaseOrderTool

**Category:** ERP
**File:** `app/tools/erp/purchase_order_tool.py`

### Description
Retrieves and synchronises Purchase Order data between the platform and the ERP system. When ERP is connected, POs are sourced from the ERP (not the platform DB).

### Current Behaviour (Mock ERP)
Reads from platform `purchase_orders` table.

### Future Behaviour (SAP)
Calls `BAPI_PO_GETDETAIL` to retrieve PO data from SAP.

### Responsibilities
- Retrieve PO details by PO number
- Retrieve all open POs for a vendor
- Update PO outstanding balance after invoice matching

### Used By
| Agent | Graph |
|---|---|
| POMatchingAgent | InvoiceProcessingGraph |

---

## Tool: GoodsReceiptTool

**Category:** ERP
**File:** `app/tools/erp/goods_receipt_tool.py`

### Description
Retrieves Goods Receipt data from the platform or connected ERP system. When ERP is connected, GRNs are sourced from ERP Goods Receipts (SAP: MIGO documents).

### Current Behaviour (Mock ERP)
Reads from platform `grn_records` table.

### Future Behaviour (SAP)
Queries SAP Material Documents (movement type 101) linked to the PO.

### Used By
| Agent | Graph |
|---|---|
| POMatchingAgent | InvoiceProcessingGraph |

---

## Tool: AssetTool

**Category:** ERP
**File:** `app/tools/erp/asset_tool.py`

### Description
Handles CAPEX invoice processing — creates or updates fixed asset records in the ERP when a CAPEX invoice is posted. Applicable only to PO_CAPEX and NON_PO_CAPEX profiles.

### Responsibilities
- Determine if the invoice creates a new asset or capitalises to an existing asset
- Generate the asset creation payload for the ERP
- Link the invoice document to the asset record

### Current Behaviour (Mock ERP)
Writes to platform `assets` table.

### Future Behaviour (SAP)
Calls Asset Accounting API (`BAPI_FIXEDASSET_OVRTAKE_CREATE` or AS01 equivalent).

### Used By
| Agent | Graph |
|---|---|
| ERPPostingAgent (CAPEX profiles only) | InvoiceProcessingGraph |

---

## Tool: BudgetTool

**Category:** ERP
**File:** `app/tools/erp/budget_tool.py`

### Description
Validates that an invoice does not exceed the available budget for its cost centre and GL account before ERP posting. Prevents budget overruns at the point of invoice approval.

### Responsibilities
- Retrieve available budget for a cost centre + GL account + period
- Compute remaining budget after this invoice
- Return a budget check verdict: WITHIN_BUDGET / OVER_BUDGET / NO_BUDGET_DEFINED

### MUST Do
- Perform budget check before ERP posting (not after)
- Return remaining budget amount as evidence

### Input Model
```
BudgetCheckInput:
  cost_center: str
  gl_account: str
  amount: Decimal
  currency: str
  fiscal_period: str
  document_id: UUID
  tenant_id: str
```

### Output Model
```
BudgetCheckResult:
  success: bool
  verdict: str               # WITHIN_BUDGET / OVER_BUDGET / NO_BUDGET_DEFINED
  available_budget: Decimal | None
  consumed_budget: Decimal | None
  remaining_after: Decimal | None
  overage: Decimal | None
```

### Used By
| Agent | Graph |
|---|---|
| DecisionAgent | InvoiceProcessingGraph |
| ERPPostingAgent | InvoiceProcessingGraph |

---

*END OF ERP TOOLS*

---

# WORKFLOW TOOLS

---

## Tool: WorkflowStateTool

**Category:** Workflow
**File:** `app/tools/workflow/workflow_state_tool.py`

### Description
Provides safe, typed read and write access to the `WorkflowState` object. Ensures agents update only their designated state sections, never each other's. Enforces state version incrementing and conflict detection.

### Purpose
Prevent agents from accidentally corrupting another agent's state section. Provide a typed, versioned state access layer.

### Responsibilities
- Provide typed getters and setters per state section
- Increment `state.version` on every update
- Detect optimistic locking conflicts
- Serialise/deserialise state to/from JSON for LangGraph checkpointing
- Record state transitions in execution history

### MUST Do
- Validate that the calling agent is permitted to write its declared section
- Increment version on every write
- Preserve all previous state sections on partial updates

### MUST NEVER Do
- Allow an agent to overwrite another agent's section (enforced via section ownership registry)

### Input Models
```
StateReadInput:
  workflow_id: UUID
  section: str | None    # None = full state

StateWriteInput:
  workflow_id: UUID
  section: str
  data: dict
  agent_name: str
  version_expected: int   # optimistic lock
```

### Output Models
```
StateReadResult:
  success: bool
  state_data: dict
  current_version: int

StateWriteResult:
  success: bool
  new_version: int
  conflict_detected: bool
```

### Public Methods
| Method | Description |
|---|---|
| `read(input)` | Read state or section |
| `write(input)` | Write section with version check |
| `get_execution_stage()` | Current pipeline stage |
| `set_execution_stage(stage)` | Advance pipeline stage |
| `append_execution_history(step)` | Add execution step record |
| `serialise(state)` | JSON serialisation for checkpointing |
| `deserialise(json)` | Restore state from checkpoint |

### Dependencies
- `WorkflowRepository`
- `LoggingTool`

### Used By
All agents (indirectly, through their section-specific state access)

---

## Tool: QueueTool

**Category:** Workflow
**File:** `app/tools/workflow/queue_tool.py`

### Description
Provider-agnostic message queue interface. Dispatches tasks to the configured queue backend (Celery with Redis, or Azure Service Bus). Used by FastAPI to enqueue pipeline jobs and by agents to enqueue notifications.

### Purpose
Decouple task dispatch from specific queue infrastructure. Switch from Celery to Azure Service Bus by changing one configuration value.

### Responsibilities
- Enqueue a pipeline processing job
- Enqueue a notification event
- Enqueue a retry task
- Check queue depth for monitoring
- Dead-letter failed messages after max retries

### Input Model
```
QueueMessage:
  queue_name: str
  message_type: str         # PIPELINE_START / RETRY / NOTIFICATION / EXCEPTION
  payload: dict
  delay_seconds: int = 0
  max_retries: int = 3
  correlation_id: str
  tenant_id: str
```

### Output Model
```
QueueResult:
  success: bool
  message_id: str
  queue_name: str
  provider: str             # "celery" | "azure_service_bus"
  enqueued_at: datetime
```

### Dependencies
- `QueueProviderInterface` — injected (CeleryProvider or AzureServiceBusProvider)
- `ConfigurationTool`
- `LoggingTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `queue.provider` | `celery` | Active queue provider |
| `queue.pipeline_queue` | `invoice_pipeline` | Main pipeline queue name |
| `queue.notification_queue` | `notifications` | Notification queue |
| `queue.dead_letter_queue` | `dead_letter` | Failed message queue |

### Used By
FastAPI (document upload triggers), NotificationAgent, RetryAgent

---

## Tool: RetryTool

**Category:** Workflow
**File:** `app/tools/workflow/retry_tool.py`

### Description
Executes a callable with configurable retry logic. Manages backoff strategy, retry count, and retryable exception filtering. The single retry implementation for the entire platform.

### Purpose
Centralise retry logic so it is not duplicated across tools. Every tool that might fail due to transient errors (OCR, LLM, ERP, storage) uses RetryTool instead of implementing its own retry loop.

### Responsibilities
- Execute a callable with up to `max_retries` attempts
- Apply exponential, linear, or fixed backoff between attempts
- Retry only on specified exception types
- Record each attempt in a retry log

### Input Model
```
RetryConfig:
  max_retries: int = 3
  backoff_strategy: str = "exponential"   # exponential / linear / fixed
  base_delay_seconds: float = 1.0
  max_delay_seconds: float = 60.0
  retryable_exceptions: List[str]         # exception class names
  jitter: bool = True
```

### Output Model
```
RetryResult:
  success: bool
  attempts: int
  final_result: Any | None
  last_exception: str | None
  retry_log: List[RetryAttempt]

RetryAttempt:
  attempt_number: int
  started_at: datetime
  duration_ms: int
  success: bool
  exception: str | None
  delay_before_next_ms: int | None
```

### Public Methods
| Method | Description |
|---|---|
| `execute(func, config)` | Run with retry |
| `calculate_delay(attempt, config)` | Backoff delay |

### Dependencies
- `LoggingTool`

### Used By
All tools that make external calls (LLMTool, OCRTool, ERPAdapterTool, StorageTool, VirusScanTool)

---

## Tool: ResumeTool

**Category:** Workflow
**File:** `app/tools/workflow/resume_tool.py`

### Description
Resumes a LangGraph workflow from a checkpoint after a human action (approval decision, exception resolution, vendor creation) has been recorded. Rebuilds the graph and submits the resume state.

### Purpose
Implement the human-in-the-loop resume mechanism. When a human resolves an exception or approves an invoice, the pipeline must resume from exactly the point it was interrupted.

### Responsibilities
- Load the workflow checkpoint from LangGraph's PostgreSQL checkpointer
- Validate the resume action is consistent with the pending interrupt state
- Build the resume input (human decision + timestamp + actor)
- Invoke the graph with the resume state
- Update WorkflowState with the resolution

### MUST Do
- Validate the resuming user's permission for the pending action
- Record the resume action in the audit trail before resuming

### Input Model
```
ResumeInput:
  workflow_id: UUID
  resume_type: str           # EXCEPTION_RESOLVED / VENDOR_CREATED / OCR_CORRECTED / APPROVAL_GIVEN
  resolution_data: dict      # human's decision/correction
  resolved_by: str           # user_id
  document_id: UUID
  tenant_id: str
```

### Output Model
```
ResumeResult:
  success: bool
  workflow_id: UUID
  resumed_from_stage: str
  resumed_at: datetime
  new_stage: str
```

### Dependencies
- `WorkflowRepository`
- `AuditTool`
- `AuthorizationTool`
- `LoggingTool`

### Audit Events
| Event | Trigger |
|---|---|
| `WORKFLOW_RESUMED` | Successful resume |
| `WORKFLOW_RESUME_REJECTED` | Unauthorised resume attempt |

### Used By
Called by FastAPI `POST /api/v1/workflows/{id}/resume` — not directly by agents

---

## Tool: ApprovalTool

**Category:** Workflow
**File:** `app/tools/workflow/approval_tool.py`

### Description
Manages the complete approval lifecycle: creating approval requests, routing to approvers, recording decisions, and handling delegation and escalation. Config-driven via `approval_matrix.yaml`.

### Purpose
Implement the approval engine as a reusable tool. Any future workflow that requires approval can use this tool — not just invoices.

### Responsibilities
- Determine required approval levels from the approval matrix
- Create approval request records
- Route notifications to appropriate approvers
- Record approval/rejection/delegation decisions
- Enforce SLA deadlines and escalate on breach
- Generate AI-powered approval recommendations

### MUST Do
- Read approval matrix from config — never hardcode
- Record every decision with timestamp and actor
- Enforce SLA — escalate when SLA is breached

### Input Models
```
ApprovalRequestInput:
  document_id: UUID
  workflow_id: UUID
  amount: Decimal
  business_profile: str
  department: str | None
  currency: str
  tenant_id: str

ApprovalDecisionInput:
  approval_id: UUID
  decision: str          # APPROVED / REJECTED / DELEGATED
  decided_by: str
  comments: str | None
  delegate_to: str | None
  tenant_id: str
```

### Output Models
```
ApprovalRequestResult:
  success: bool
  approval_id: UUID
  required_levels: int
  current_level: int
  approver_id: str
  approver_email: str
  sla_deadline: datetime
  ai_recommendation: str | None   # from SummaryTool/ReasoningTool

ApprovalDecisionResult:
  success: bool
  approval_id: UUID
  decision: str
  is_final_approval: bool
  next_approver: str | None
  workflow_can_proceed: bool
```

### Public Methods
| Method | Description |
|---|---|
| `create_request(input)` | Create and route approval request |
| `record_decision(input)` | Record approval/rejection |
| `escalate(approval_id)` | Escalate SLA breach |
| `delegate(approval_id, delegate_to)` | Transfer to delegate |
| `get_approval_matrix(amount, profile)` | Load applicable matrix |
| `check_sla_breaches()` | Scheduled: check and escalate |

### Dependencies
- `ApprovalRepository`
- `UserTool`
- `NotificationTool`
- `SummaryTool` — for AI recommendation
- `ConfigurationTool`
- `AuditTool`
- `LoggingTool`

### Audit Events
| Event | Trigger |
|---|---|
| `APPROVAL_REQUESTED` | New approval created |
| `APPROVAL_GRANTED` | Approved at any level |
| `APPROVAL_REJECTED` | Rejected |
| `APPROVAL_DELEGATED` | Delegated to another user |
| `APPROVAL_SLA_BREACHED` | SLA deadline passed |

### Used By
| Agent | Graph |
|---|---|
| ApprovalAgent | ApprovalGraph |

---

## Tool: ExceptionTool

**Category:** Workflow
**File:** `app/tools/workflow/exception_tool.py`

### Description
Creates, enriches, routes, and resolves exception records. Implements the complete exception lifecycle for the platform. Uses the ExceptionRegistry to look up SLA, responsible team, and resolution guidance for each exception type.

### Purpose
Provide a reusable exception management service that can be used by any AI workflow, not just invoice processing.

### Responsibilities
- Create an `ExceptionRecord` with full context
- Look up exception type metadata from the registry
- Assign to the responsible team and individual
- Set SLA deadline
- Record resolution decisions
- Resume the pipeline after resolution

### MUST Do
- Always include evidence and compared_fields in the exception record
- Set SLA deadline based on registry configuration
- Never lose the exception evidence — it must be preserved in the database

### Input Models
```
ExceptionCreateInput:
  exception_type: str
  workflow_id: UUID
  document_id: UUID
  raised_by_agent: str
  reason: str
  evidence: dict
  compared_fields: dict
  confidence: float
  tenant_id: str

ExceptionResolveInput:
  exception_id: UUID
  resolution: str
  resolved_by: str
  resolution_comment: str
  resume_workflow: bool = True
  tenant_id: str
```

### Output Models
```
ExceptionCreateResult:
  success: bool
  exception_id: UUID
  exception_type: str
  severity: str
  responsible_team: str
  assigned_to: str | None
  sla_deadline: datetime
  suggested_resolution: str

ExceptionResolveResult:
  success: bool
  exception_id: UUID
  resolution_recorded: bool
  workflow_resumed: bool
```

### Dependencies
- `ExceptionRepository`
- `ExceptionRegistry` — type → severity/team/SLA mapping
- `UserTool` — assign to team member
- `NotificationTool` — notify assignee
- `ResumeTool` — resume workflow after resolution
- `AuditTool`
- `LoggingTool`

### Audit Events
| Event | Trigger |
|---|---|
| `EXCEPTION_RAISED` | New exception created |
| `EXCEPTION_ASSIGNED` | Assigned to user |
| `EXCEPTION_RESOLVED` | Resolved |
| `EXCEPTION_ESCALATED` | SLA breach escalation |

### Used By
| Agent | Graph |
|---|---|
| ExceptionAgent | ExceptionGraph |
| All agents (raise exceptions) | InvoiceProcessingGraph |

---

## Tool: NotificationTool

**Category:** Workflow
**File:** `app/tools/workflow/notification_tool.py`

### Description
Dispatches notifications through configured channels (email, Microsoft Teams). Provider-agnostic — selects channel based on config and recipient preferences. Supports templated notifications with dynamic content.

### Purpose
Provide a single notification dispatch interface. Agents call `NotificationTool.send()` — never construct emails directly.

### Responsibilities
- Load the correct notification template for the event type
- Resolve recipient list (user, role, team, or email)
- Render template with dynamic data
- Dispatch through all configured channels
- Record delivery status

### MUST Do
- Never block the calling agent on notification delivery — use fire-and-forget for non-critical
- Record every notification dispatch (sent/failed) in the database
- Include a deep link in every notification (direct link to the relevant document/exception/approval)

### MUST NEVER Do
- Store notification content after sending (privacy)
- Send PII in notification subjects (only document IDs)

### Input Model
```
NotificationInput:
  event_type: str           # APPROVAL_REQUIRED / EXCEPTION_RAISED / INVOICE_PROCESSED / etc.
  recipients: List[str]     # user_ids, role names, or email addresses
  context_data: dict        # template variables
  document_id: UUID
  workflow_id: UUID
  deep_link: str
  priority: str = "NORMAL"  # URGENT / HIGH / NORMAL / LOW
  tenant_id: str
```

### Output Model
```
NotificationResult:
  success: bool
  notification_id: UUID
  channels_attempted: List[str]
  channels_succeeded: List[str]
  channels_failed: List[str]
  recipient_count: int
```

### Dependencies
- `NotificationProviderInterface` — EmailProvider, TeamsProvider (injected)
- `NotificationRepository`
- `UserTool` — resolve user contact details
- `ConfigurationTool` — active channels, templates
- `LoggingTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `notification.channels` | `["email"]` | Active channels |
| `notification.urgent_channels` | `["email", "teams"]` | Channels for URGENT priority |

### Used By
| Agent | Graph |
|---|---|
| NotificationAgent | NotificationGraph |
| ApprovalAgent | ApprovalGraph |
| ExceptionAgent | ExceptionGraph |

---

## Tool: AuditTool

**Category:** Workflow
**File:** `app/tools/workflow/audit_tool.py`

### Description
Writes immutable audit events to the `audit_logs` table. Every compliance-relevant action in the platform generates an audit event. The audit log has no UPDATE or DELETE permissions at the database level.

### Purpose
Provide a complete, tamper-evident audit trail for every document processed by the platform. Required for SOX, GST audit, and client compliance reporting.

### Responsibilities
- Write a structured `AuditEvent` to the database
- Ensure every event has: who, what, when, before, after, evidence
- Support querying audit trail by document, workflow, agent, or event type
- Build processing timelines from audit events

### MUST Do
- Write events synchronously (not async) — audit must be guaranteed before control returns
- Generate a unique `event_id` for every event
- Record before/after state for every state change event
- Never update or delete audit records

### MUST NEVER Do
- Batch audit writes — write immediately
- Swallow write failures — audit failure is a CRITICAL error

### Input Model
```
AuditEventInput:
  event_type: str
  agent_name: str
  actor: str                   # agent name or user_id
  workflow_id: UUID
  document_id: UUID
  before_state: dict | None
  after_state: dict | None
  evidence: dict | None
  metadata: dict
  tenant_id: str
```

### Output Model
```
AuditEventResult:
  success: bool
  event_id: UUID
  written_at: datetime
```

### Public Methods
| Method | Description |
|---|---|
| `write(input)` | Write single audit event |
| `get_trail(document_id)` | Full audit trail for document |
| `build_timeline(document_id)` | Timeline view from audit events |
| `get_decisions(document_id)` | AI decision events only |

### Dependencies
- `AuditRepository` — append-only writes
- `LoggingTool`

### Used By
All agents that make compliance-relevant decisions

---

## Tool: TimelineTool

**Category:** Workflow
**File:** `app/tools/workflow/timeline_tool.py`

### Description
Builds a human-readable processing timeline from audit events for display on the document detail page. Identifies bottlenecks and SLA compliance.

### Responsibilities
- Retrieve all audit events for a workflow
- Order chronologically
- Compute stage durations
- Identify the slowest stage (bottleneck)
- Map events to timeline step labels

### Output Model
```
TimelineResult:
  workflow_id: UUID
  steps: List[TimelineStep]
  total_duration_ms: int
  bottleneck_stage: str | None
  sla_compliant: bool

TimelineStep:
  stage: str
  agent: str
  started_at: datetime
  completed_at: datetime | None
  duration_ms: int | None
  status: str               # COMPLETED / IN_PROGRESS / FAILED / SKIPPED
  human_action: bool
  human_actor: str | None
```

### Used By
| Agent | Graph |
|---|---|
| AuditAgent | InvoiceProcessingGraph |

---

## Tool: LoggingTool

**Category:** Workflow
**File:** `app/tools/workflow/logging_tool.py`

### Description
Structured logging service used by all tools and agents. Emits JSON-structured log records to the configured log destination (stdout for Azure → Azure Log Analytics, or console for development).

### Purpose
Centralise all logging behind a single interface so log format, destination, and level can be changed without modifying tools.

### Responsibilities
- Emit structured JSON log records
- Include: timestamp, level, tool_name, workflow_id, document_id, correlation_id, duration_ms
- Support log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Automatically include correlation_id from request context

### MUST Do
- Log at INFO for normal operations
- Log at WARNING for soft failures and low confidence
- Log at ERROR for tool failures
- Log at CRITICAL for audit failures and security events
- Never log PII or full invoice content — log hashes and references

### Input Model
```
LogEntry:
  level: str
  tool_name: str
  message: str
  workflow_id: UUID | None
  document_id: UUID | None
  correlation_id: str | None
  duration_ms: int | None
  metadata: dict
```

### Used By
All tools and agents

---

## Tool: AnalyticsTool

**Category:** Workflow
**File:** `app/tools/workflow/analytics_tool.py`

### Description
Computes processing metrics and KPIs for the analytics dashboard. Queries aggregate data from the database for a given time period and tenant.

### Purpose
Power the analytics dashboard with real-time and historical metrics: STP rate, average processing time, exception rate, LLM cost, approval cycle time.

### Responsibilities
- Compute Straight-Through Processing (STP) rate
- Compute average processing time per stage
- Compute exception rate by type and team
- Compute LLM token costs by agent and model
- Compute approval cycle time distribution
- Support dimensional breakdown (by profile, by vendor, by period)

### Input Model
```
AnalyticsInput:
  metric: str           # STP_RATE / PROCESSING_TIME / EXCEPTION_RATE / LLM_COST / APPROVAL_CYCLE
  date_from: date
  date_to: date
  dimensions: List[str]   # ["profile", "vendor", "agent"]
  tenant_id: str
```

### Output Model
```
AnalyticsResult:
  metric: str
  value: float
  unit: str
  breakdown: Dict[str, float] | None
  trend: List[DataPoint] | None
  comparison_period: float | None
```

### Dependencies
- `DocumentRepository`
- `WorkflowRepository`
- `AuditRepository`
- `LoggingTool`

### Used By
FastAPI analytics routes — not called by agents directly

---

## Tool: AssignmentTool

**Category:** Workflow
**File:** `app/tools/workflow/assignment_tool.py`

### Description
Determines the correct user to assign work items (exceptions, approvals, reviews) based on role, workload, availability, and escalation rules.

### Responsibilities
- Find the primary assignee for a given role and team
- Check assignee availability (delegation rules)
- Apply round-robin load balancing within a team
- Return delegate if primary is unavailable

### Input Model
```
AssignmentInput:
  assignment_type: str       # EXCEPTION / APPROVAL / REVIEW
  role: str
  team: str | None
  amount: Decimal | None     # for amount-based routing
  document_id: UUID
  tenant_id: str
```

### Output Model
```
AssignmentResult:
  success: bool
  assigned_to: str
  assigned_role: str
  is_delegate: bool
  delegate_reason: str | None
  assignee_email: str
```

### Dependencies
- `UserRepository`
- `ConfigurationTool`
- `LoggingTool`

### Used By
| Agent | Graph |
|---|---|
| ExceptionAgent | ExceptionGraph |
| ApprovalAgent | ApprovalGraph |

---

## Tool: EscalationTool

**Category:** Workflow
**File:** `app/tools/workflow/escalation_tool.py`

### Description
Handles SLA breach detection and escalation routing. Checks all open exceptions and approvals for SLA breaches and sends escalation notifications to the next level.

### Responsibilities
- Query all open exceptions/approvals past their SLA deadline
- Determine escalation path from configuration
- Send escalation notifications
- Update the record with escalation history

### Public Methods
| Method | Description |
|---|---|
| `check_and_escalate()` | Scheduled: check all open items |
| `escalate_exception(exception_id)` | Manual escalation |
| `escalate_approval(approval_id)` | Approval SLA escalation |

### Dependencies
- `ExceptionRepository`
- `ApprovalRepository`
- `NotificationTool`
- `AssignmentTool`
- `AuditTool`
- `ConfigurationTool`

### Used By
Celery Beat scheduled task (`tasks/scheduled_tasks.py`)

---

*END OF WORKFLOW TOOLS*

---

# STORAGE TOOLS

---

## Tool: LocalStorageTool

**Category:** Storage
**File:** `app/tools/storage/local_storage_tool.py`

### Description
Implements `StorageProviderInterface` using the local filesystem. For development and testing only. Stores files in a configured base directory.

### MUST NEVER Do
- Be used in production — guarded by `storage.allow_local_in_production=false`

### Public Methods
`upload()`, `download()`, `delete()`, `exists()`, `get_access_url()`

### Dependencies
- `os`, `pathlib` (stdlib)
- `ConfigurationTool` — reads `storage.local.base_path`

### Used By
StorageTool only (in development environment)

---

## Tool: AzureBlobStorageTool

**Category:** Storage
**File:** `app/tools/storage/azure_blob_storage_tool.py`

### Description
Implements `StorageProviderInterface` using Azure Blob Storage. Production storage backend. Uses Azure Managed Identity for authentication — no storage account keys in code.

### Responsibilities
- Upload files to the configured container with deterministic blob path
- Generate SAS URLs with configurable expiry
- Support lifecycle management (hot → cool → archive tier transitions)
- Handle Azure Blob SDK exceptions and translate to standard storage error codes

### Public Methods
`upload()`, `download()`, `delete()`, `exists()`, `get_access_url()`, `set_tier()`

### Dependencies
- `azure-storage-blob` SDK
- Azure Managed Identity (via `azure-identity`)
- `ConfigurationTool`
- `LoggingTool`

### Configuration
| Key | Default | Description |
|---|---|---|
| `storage.azure.account_name` | *(from Key Vault)* | Storage account name |
| `storage.azure.container_name` | `ap-documents` | Blob container |
| `storage.azure.tier_default` | `hot` | Default access tier |
| `storage.azure.sas_expiry_hours` | `1` | SAS URL lifetime |

### Used By
StorageTool only (in production environment)

---

## Tool: DocumentVersionTool

**Category:** Storage
**File:** `app/tools/storage/document_version_tool.py`

### Description
Maintains a version history of documents when they are modified or re-uploaded. Creates a new version record with a new storage path while preserving all previous versions.

### Responsibilities
- Create a new document version on re-upload or correction
- List all versions of a document
- Restore a previous version as the current version
- Compare two versions

### Input Model
```
DocumentVersionInput:
  document_id: UUID
  new_file_bytes: bytes
  version_reason: str      # RE_UPLOAD / OCR_CORRECTION / MANUAL_CORRECTION
  created_by: str
  tenant_id: str
```

### Output Model
```
DocumentVersionResult:
  success: bool
  version_number: int
  storage_path: str
  previous_version: int | None
```

### Dependencies
- `StorageTool`
- `DocumentRepository`
- `HashTool`
- `AuditTool`
- `LoggingTool`

### Audit Events
| Event | Trigger |
|---|---|
| `DOCUMENT_VERSION_CREATED` | New version stored |

### Used By
Upload flow on re-submission

---

## Tool: ArchiveTool

**Category:** Storage
**File:** `app/tools/storage/archive_tool.py`

### Description
Moves processed documents to the archive storage tier (Azure Blob Archive) after a configurable retention period. Compresses documents before archiving.

### Responsibilities
- Identify documents eligible for archiving (processed, past retention threshold)
- Compress document via CompressionTool
- Move to archive tier in Azure Blob
- Update document record with archive status and path

### Dependencies
- `StorageTool`
- `CompressionTool`
- `DocumentRepository`
- `AuditTool`
- `ConfigurationTool` — reads `archive.retention_days`, `archive.blob_tier`

### Used By
Celery Beat scheduled task

---

## Tool: BackupTool

**Category:** Storage
**File:** `app/tools/storage/backup_tool.py`

### Description
Creates periodic backup snapshots of the document store. For Azure deployments, this wraps Azure Backup policies. For local development, performs file system copies.

### Current Behaviour
Azure Blob Storage has built-in point-in-time restore — this tool configures and verifies backup policies rather than performing raw file copies.

### Used By
Celery Beat scheduled task (verify backup policy compliance)

---

## Tool: RestoreTool

**Category:** Storage
**File:** `app/tools/storage/restore_tool.py`

### Description
Restores documents from archive or backup storage for re-processing or audit access. Handles decompression and tier restoration.

### Responsibilities
- Restore a single document from archive tier to hot tier
- Bulk restore for audit access
- Decompress restored document

### Dependencies
- `StorageTool`
- `CompressionTool`
- `AuditTool`
- `ConfigurationTool`

### Used By
Admin API and AuditAgent

---

*END OF STORAGE TOOLS*

---

# PROMPT TOOLS

---

## Tool: PromptRegistryTool

**Category:** Prompt
**File:** `app/tools/prompts/prompt_registry_tool.py`

### Description
Maintains the central registry of all prompts in the platform. Tracks available agents, their prompt versions, activation status, and change history. The administrative interface for prompt management.

### Purpose
Provide a single source of truth for what prompts exist, which versions are active, and what history exists. Powers the Admin UI prompt management screen.

### Responsibilities
- List all agents with their current active prompt version
- List all versions for a given agent
- Activate or deactivate prompt versions
- Record every activation/deactivation with timestamp and actor

### Input Models
```
PromptRegistryListInput:
  tenant_id: str
  agent_name: str | None   # None = all agents

PromptActivateInput:
  agent_name: str
  version: str
  activated_by: str
  tenant_id: str
```

### Output Models
```
PromptRegistryEntry:
  agent_name: str
  active_version: str
  available_versions: List[PromptVersionMeta]
  tenant_specific: bool

PromptVersionMeta:
  version: str
  status: str            # ACTIVE / STAGING / DEPRECATED
  content_hash: str
  created_at: datetime
  activated_at: datetime | None
  change_summary: str
```

### Public Methods
| Method | Description |
|---|---|
| `list(input)` | List agents and versions |
| `activate(input)` | Activate a version |
| `rollback(agent, tenant_id)` | Rollback to previous active |
| `deprecate(agent, version)` | Mark version as deprecated |
| `get_history(agent, tenant_id)` | Full activation history |

### Dependencies
- `PromptRepository`
- `AuditTool`
- `LoggingTool`

### Audit Events
| Event | Trigger |
|---|---|
| `PROMPT_VERSION_ACTIVATED` | Version activated |
| `PROMPT_VERSION_ROLLED_BACK` | Rollback executed |

### Used By
Admin API — `POST /api/v1/config/prompts/{agent}/activate/{v}`

---

## Tool: PromptLoaderTool

**Category:** Prompt
**File:** `app/tools/prompts/prompt_loader_tool.py`

### Description
Loads raw prompt content from the filesystem registry or database. Resolves the tenant-override chain. Returns the raw YAML content of a prompt before rendering.

### Purpose
Separate prompt loading (finding the file, resolving tenant override) from prompt rendering (filling in variables). Enables prompt preview and testing without rendering.

### Responsibilities
- Resolve prompt lookup chain: tenant-specific DB record → global DB record → filesystem YAML
- Load raw YAML prompt content
- Return prompt content without rendering

### Input Model
```
PromptLoadInput:
  agent_name: str
  version: str | None    # None = active version
  tenant_id: str
```

### Output Model
```
PromptLoadResult:
  success: bool
  raw_content: str         # YAML content
  version: str
  source: str              # "database" | "filesystem"
  tenant_specific: bool
  content_hash: str
```

### Public Methods
| Method | Description |
|---|---|
| `load(input)` | Load prompt content |
| `exists(agent, version, tenant_id)` | Check existence |
| `load_all_versions(agent, tenant_id)` | Load all versions |

### Dependencies
- `PromptRepository`
- `ConfigurationTool` — reads prompt registry path
- `LoggingTool`

### Used By
PromptTool, PromptRegistryTool

---

## Tool: PromptVersionTool

**Category:** Prompt
**File:** `app/tools/prompts/prompt_version_tool.py`

### Description
Manages the versioning lifecycle of prompts. Handles version creation, activation tracking, rollback, and version comparison. The version control system for prompts.

### Purpose
Enable safe prompt iteration — new versions can be tested in staging before activation, and any version can be rolled back in seconds if it degrades quality.

### Responsibilities
- Track the currently active version per agent per tenant
- Store activation timestamps and actor
- Support rollback to any previous version
- Compare two versions (diff)
- Support concurrent version management across multiple agents

### Input Models
```
VersionActivateInput:
  agent_name: str
  version: str
  activated_by: str
  tenant_id: str

VersionRollbackInput:
  agent_name: str
  tenant_id: str
  target_version: str | None   # None = previous active
```

### Output Models
```
VersionInfo:
  agent_name: str
  version: str
  status: str
  activated_at: datetime | None
  activated_by: str | None
  content_hash: str

VersionCompareResult:
  version_a: str
  version_b: str
  system_prompt_diff: str
  user_prompt_diff: str
  schema_changes: List[str]
```

### Public Methods
| Method | Description |
|---|---|
| `get_active(agent, tenant_id)` | Get current active version |
| `activate(input)` | Activate version (deactivates current) |
| `rollback(input)` | Roll back to previous |
| `compare(agent, v1, v2)` | Diff two versions |
| `get_history(agent, tenant_id)` | Activation history |

### Dependencies
- `PromptRepository`
- `HashTool`
- `AuditTool`
- `LoggingTool`

### Used By
PromptTool, PromptRegistryTool, PromptLoaderTool

---

## Tool: PromptTemplateTool

**Category:** Prompt
**File:** `app/tools/prompts/prompt_template_tool.py`

### Description
Renders Jinja2 prompt templates with provided variables. Validates that all required variables are present before rendering. Returns the rendered system and user prompt strings.

### Purpose
Safely render prompt templates with runtime variables. Jinja2 rendering is centralised here so that unsafe template rendering (code injection via user data) is prevented uniformly.

### Responsibilities
- Render Jinja2 template with provided variables
- Validate all required variables are present
- Sandbox template rendering (no arbitrary code execution)
- Return rendered system and user prompts separately

### MUST Do
- Use Jinja2's `SandboxedEnvironment` — never regular Environment
- Validate variable types before rendering
- Report missing variables without raising exceptions

### Input Model
```
TemplateRenderInput:
  template_content: str    # raw Jinja2 template
  variables: dict
  agent_name: str
```

### Output Model
```
TemplateRenderResult:
  success: bool
  rendered_system_prompt: str | None
  rendered_user_prompt: str | None
  missing_variables: List[str]
  rendered_length: int
```

### Dependencies
- `jinja2` with `SandboxedEnvironment`
- `LoggingTool`

### Used By
PromptTool

---

## Tool: PromptAuditTool

**Category:** Prompt
**File:** `app/tools/prompts/prompt_audit_tool.py`

### Description
Records every prompt usage event: which version was used, for which document, how many tokens, and what the outcome was. Enables prompt quality analysis and version performance comparison.

### Purpose
Provide data to answer: "Is v2 of the extraction prompt producing better confidence scores than v1?" This enables data-driven prompt improvements.

### Responsibilities
- Record prompt usage event (agent, version, document_id, tokens, outcome)
- Aggregate performance metrics per prompt version
- Detect quality regression between versions

### Input Model
```
PromptUsageEvent:
  agent_name: str
  prompt_version: str
  document_id: UUID
  workflow_id: UUID
  tokens_used: int
  outcome_confidence: float
  outcome_status: str
  tenant_id: str
```

### Output: Append-only write to `prompt_usage_log` table.

### Dependencies
- `PromptRepository`
- `LoggingTool`

### Used By
LLMTool (after every LLM call)

---

## Tool: PromptEvaluationTool

**Category:** Prompt
**File:** `app/tools/prompts/prompt_evaluation_tool.py`

### Description
Evaluates prompt quality by running a candidate version against a test dataset and comparing results to a reference. Enables safe promotion of new prompt versions.

### Purpose
Prevent prompt regressions by requiring evaluation before promotion to production. A new extraction prompt that reduces confidence scores on historical test data should not be activated.

### Responsibilities
- Run a candidate prompt version against a test dataset
- Compare extraction/classification results to reference (golden) answers
- Compute accuracy, confidence, and regression metrics
- Return a promotion recommendation

### Input Model
```
PromptEvaluationInput:
  agent_name: str
  candidate_version: str
  test_dataset_id: str
  tenant_id: str
```

### Output Model
```
PromptEvaluationResult:
  success: bool
  candidate_version: str
  accuracy_score: float
  average_confidence: float
  regression_vs_current: float    # negative = worse
  field_accuracy: Dict[str, float]
  recommendation: str             # PROMOTE / DO_NOT_PROMOTE / NEEDS_REVIEW
  test_cases_run: int
  test_cases_passed: int
```

### Used By
Admin API — prompt promotion workflow

---

*END OF PROMPT TOOLS*

---

# CONFIGURATION TOOLS

---

## Tool: ConfigurationTool

**Category:** Configuration
**File:** `app/tools/config/configuration_tool.py`

### Description
The universal configuration access interface for the entire platform. Every tool, agent, and graph that needs a configuration value calls `ConfigurationTool.get()`. Never reads `.env` directly, never reads YAML directly — that is handled internally.

### Purpose
Provide a single, tenant-aware configuration access point. Implement the configuration priority chain: environment → DB override → YAML → default.

### Responsibilities
- Implement priority chain: `env var → DB config_entries (tenant) → DB config_entries (global) → YAML → default`
- Cache configuration values in Redis to avoid repeated DB reads
- Support configuration invalidation (hot-reload without restart)
- Support tenant-specific overrides at the key level
- Provide typed accessors: `get_str`, `get_int`, `get_bool`, `get_decimal`, `get_list`

### MUST Do
- Apply tenant-specific override before global value
- Cache with TTL — invalidate when config is updated via API
- Return the declared default if no value is found at any level

### MUST NEVER Do
- Throw an exception on missing key if a default is provided
- Cache secrets — read secrets directly from Key Vault every time

### Input
```
ConfigurationTool.get(key: str, tenant_id: str, default: Any = None) → Any
```

### Examples
```
ConfigurationTool.get("ocr.confidence_threshold", tenant_id="acme", default=0.60)
ConfigurationTool.get("approval_matrix", tenant_id="acme")
ConfigurationTool.get("llm.model", tenant_id="acme", default="gpt-4o")
```

### Public Methods
| Method | Description |
|---|---|
| `get(key, tenant_id, default)` | Get any config value |
| `get_str(key, tenant_id, default)` | Typed string accessor |
| `get_int(key, tenant_id, default)` | Typed integer accessor |
| `get_bool(key, tenant_id, default)` | Typed boolean accessor |
| `get_decimal(key, tenant_id, default)` | Typed Decimal accessor |
| `get_list(key, tenant_id, default)` | Typed list accessor |
| `get_section(section, tenant_id)` | Get all keys in a section |
| `set(key, value, tenant_id)` | Write DB override (admin only) |
| `invalidate(key, tenant_id)` | Clear cache for key |
| `invalidate_all(tenant_id)` | Clear all tenant cache |

### Dependencies
- `ConfigRepository` — DB config_entries
- Redis — caching layer
- `pydantic_settings` / YAML files — base config
- Azure Key Vault — secrets (bypasses cache)

### Configuration
`configuration_tool.yaml_config_paths` — list of YAML files to load at startup.

### Used By
Every tool in the platform

---

## Tool: RuleEngineTool

**Category:** Configuration
**File:** `app/tools/config/rule_engine_tool.py`

### Description
Evaluates complex conditional rule expressions defined in YAML. Supports compound conditions (AND/OR/NOT), cross-field comparisons, range checks, and regex patterns. The execution engine for `business_rules.yaml`.

### Purpose
Enable complex multi-condition business rules to be defined in configuration without writing Python code.

### Responsibilities
- Parse rule expressions from YAML
- Evaluate compound conditions against a data dictionary
- Support operators: EQ, NEQ, GT, GTE, LT, LTE, IN, NOT_IN, REGEX, PRESENT, ABSENT
- Support logical combinators: AND, OR, NOT
- Return evaluation trace for explainability

### Input Model
```
RuleEvaluationInput:
  rule_expression: dict       # parsed from YAML
  data: dict
  rule_id: str
```

### Output Model
```
RuleEvaluationResult:
  matched: bool
  evaluation_trace: List[str]   # step-by-step evaluation for explainability
```

### Dependencies
- Pure Python — no external dependencies
- `LoggingTool`

### Used By
BusinessRuleTool, ValidationTool

---

## Tool: FeatureFlagTool

**Category:** Configuration
**File:** `app/tools/config/feature_flag_tool.py`

### Description
Manages feature flags for gradual rollout of platform features. Feature flags are tenant-specific and can be toggled via the Admin API without deployment.

### Purpose
Enable controlled rollout of new features: enable Azure DI for one tenant before rolling out to all, or enable a new validation rule for one customer as a pilot.

### Responsibilities
- Check if a feature is enabled for a given tenant
- List all feature flags and their states
- Enable/disable features via API

### Input
```
FeatureFlagTool.is_enabled(feature: str, tenant_id: str) → bool
```

### Examples
```
FeatureFlagTool.is_enabled("azure_di_ocr", tenant_id="acme")
FeatureFlagTool.is_enabled("irp_qr_validation", tenant_id="acme")
FeatureFlagTool.is_enabled("budget_check_before_posting", tenant_id="acme")
```

### Dependencies
- `ConfigurationTool` — feature flags stored as config keys with prefix `feature.`
- Redis — cached

### Used By
Any tool that implements a feature that is not yet universally enabled

---

## Tool: ThresholdTool

**Category:** Configuration
**File:** `app/tools/config/threshold_tool.py`

### Description
Retrieves configured threshold values (confidence thresholds, amount thresholds, tolerance values) with tenant and profile overrides. Provides a single typed interface for threshold access.

### Purpose
Centralise threshold configuration to prevent the same threshold being read with different default values in different tools.

### Input
```
ThresholdTool.get_confidence_threshold(stage: str, tier: str, tenant_id: str) → float
ThresholdTool.get_approval_threshold(profile: str, tenant_id: str) → Decimal
ThresholdTool.get_tolerance(profile: str, field: str, tenant_id: str) → Decimal
```

### Dependencies
- `ConfigurationTool`

### Used By
ConfidenceTool, DecisionAgent tools, ToleranceValidationTool

---

## Tool: EnvironmentTool

**Category:** Configuration
**File:** `app/tools/config/environment_tool.py`

### Description
Provides the current execution environment context (DEVELOPMENT / STAGING / PRODUCTION) and environment-specific guards. Prevents production-unsafe operations (mock ERP, local storage) from running in production.

### Purpose
Enforce environment safety — ensure that development-only tools cannot be accidentally activated in production.

### Input
```
EnvironmentTool.get_environment() → str   # "development" | "staging" | "production"
EnvironmentTool.is_production() → bool
EnvironmentTool.assert_not_production(message)  # raises if production
```

### Dependencies
- `ConfigurationTool` — reads `app.environment`

### Used By
MockERPTool, LocalStorageTool, any tool with a production guard

---

## Tool: ProviderSelectionTool

**Category:** Configuration
**File:** `app/tools/config/provider_selection_tool.py`

### Description
Determines and returns the active provider for each injectable service (LLM, OCR, Storage, ERP, Notification, Queue). Used by service factories to instantiate the correct concrete implementation.

### Purpose
Centralise provider selection logic. The `provider_config.yaml` is the single place to change which implementation is active.

### Input
```
ProviderSelectionTool.get_provider(service: str, tenant_id: str) → str
# Examples:
# get_provider("llm", "acme") → "azure_openai"
# get_provider("ocr", "acme") → "tesseract"
# get_provider("erp", "acme") → "sap"
# get_provider("storage", "acme") → "azure_blob"
```

### Dependencies
- `ConfigurationTool`
- `FeatureFlagTool`

### Used By
Service factory functions in `app/services/`

---

*END OF CONFIGURATION TOOLS*

---

# SECURITY TOOLS

---

## Tool: AuthenticationTool

**Category:** Security
**File:** `app/tools/security/authentication_tool.py`

### Description
Validates JWT tokens and extracts claims. The authentication gate for all API requests. Called by FastAPI middleware — not by agents or workflow tools.

### Purpose
Provide a single authentication implementation. All token validation logic lives here — middleware simply calls this tool.

### Responsibilities
- Validate JWT signature using the configured signing key
- Check token expiry
- Extract `user_id`, `tenant_id`, `roles` claims
- Support both internal tokens and (future) external IdP tokens

### MUST Do
- Validate signature, expiry, and issuer
- Return claims as a typed `AuthenticatedUser` object
- Never log token content

### Input Model
```
AuthInput:
  token: str
  required_audience: str | None
```

### Output Model
```
AuthenticatedUser:
  user_id: str
  tenant_id: str
  roles: List[str]
  email: str
  token_expiry: datetime
  is_service_account: bool
```

### Dependencies
- `PyJWT`
- Azure Key Vault — signing key
- `ConfigurationTool`

### Used By
FastAPI authentication middleware only

---

## Tool: AuthorizationTool

**Category:** Security
**File:** `app/tools/security/authorization_tool.py`

### Description
Checks whether an authenticated user has the required permission to perform an action. Implements RBAC (Role-Based Access Control) based on the platform's role matrix.

### Purpose
Centralise all permission checks. Every tool that performs an action on behalf of a user calls `AuthorizationTool.require_permission()` before executing.

### Responsibilities
- Check if a user's roles include permission for an action
- Support resource-level permissions (approve THIS document)
- Return clear denial reasons

### Input Model
```
AuthorizationInput:
  user: AuthenticatedUser
  action: str             # "approve_invoice" / "resolve_exception" / "view_audit"
  resource_id: UUID | None
  resource_type: str | None
```

### Output Model
```
AuthorizationResult:
  is_authorised: bool
  reason: str | None
  required_role: str | None
  user_roles: List[str]
```

### Public Methods
| Method | Description |
|---|---|
| `check(input)` | Check permission, return result |
| `require(input)` | Check permission, raise if denied |

### Dependencies
- `ConfigurationTool` — RBAC role matrix
- `LoggingTool`

### Used By
ApprovalTool, ExceptionTool, ResumeTool, Admin API routes

---

## Tool: EncryptionTool

**Category:** Security
**File:** `app/tools/security/encryption_tool.py`

### Description
Provides symmetric encryption and decryption for sensitive data fields. Used for encrypting vendor bank details and PII stored in the database.

### Purpose
Protect sensitive vendor and employee data at rest. Encrypt before storage, decrypt only for authorised operations.

### Responsibilities
- Encrypt arbitrary byte content using AES-256-GCM
- Decrypt using the correct key version
- Support key rotation (encrypt new data with new key, decrypt old data with old key)
- Read encryption keys from Azure Key Vault — never from config files

### MUST Do
- Use AES-256-GCM (authenticated encryption — prevents tampering)
- Support key versioning for rotation
- Never store keys in code, config, or environment variables

### Input Models
```
EncryptInput:
  plaintext: bytes
  context: str          # additional authenticated data (AAD)

DecryptInput:
  ciphertext: bytes
  context: str
  key_version: str
```

### Dependencies
- `cryptography` library
- Azure Key Vault — encryption keys
- `ConfigurationTool`

### Used By
VendorRepository (bank details), EmployeeRepository (PII fields)

---

## Tool: MaskingTool

**Category:** Security
**File:** `app/tools/security/masking_tool.py`

### Description
Masks PII and sensitive fields for display, logging, and API responses. Ensures sensitive data is never exposed in logs or to unauthorised API consumers.

### Purpose
Prevent PII leakage in logs, debug output, and API responses. This is a data protection compliance requirement.

### Responsibilities
- Mask GSTIN: `27AABCU9603R1ZX` → `27XXXX9603RXXX`
- Mask PAN: `AABCU9603R` → `XXXXU9603X`
- Mask account numbers: show last 4 digits only
- Mask email: `user@company.com` → `u***@company.com`
- Mask phone: `9876543210` → `XXXXXX3210`

### Input Model
```
MaskingInput:
  field_type: str     # GSTIN / PAN / ACCOUNT / EMAIL / PHONE / AMOUNT
  value: str
  reveal_last_n: int = 4
```

### Output Model
```
MaskingResult:
  masked_value: str
  field_type: str
```

### Public Methods
| Method | Description |
|---|---|
| `mask(input)` | Mask a single field |
| `mask_dict(data, fields_to_mask)` | Mask multiple fields in a dict |
| `mask_for_log(data)` | Auto-detect and mask PII for logging |

### Used By
LoggingTool (auto-mask before logging), API response serialisation

---

## Tool: PIITool

**Category:** Security
**File:** `app/tools/security/pii_tool.py`

### Description
Detects and classifies PII (Personally Identifiable Information) in text content. Used to identify PII in extracted invoice text before storage and to support GDPR/privacy compliance.

### Responsibilities
- Detect PAN, GSTIN, Aadhaar, phone numbers, email addresses, bank account numbers in text
- Classify detected PII by type
- Report PII presence without extracting the value (detection, not extraction)

### Input Model
```
PIIDetectionInput:
  text: str
  document_id: UUID
```

### Output Model
```
PIIDetectionResult:
  contains_pii: bool
  pii_types_detected: List[str]    # ["PAN", "PHONE", "EMAIL"]
  detection_count: int
```

### Dependencies
- `re` (stdlib) — pattern matching
- `LoggingTool`

### Used By
AuditAgent, compliance reporting

---

## Tool: SecretManagerTool

**Category:** Security
**File:** `app/tools/security/secret_manager_tool.py`

### Description
Retrieves secrets from Azure Key Vault. The only tool in the platform that reads secrets. All other tools that need a secret (API keys, connection strings, signing keys) call this tool.

### Purpose
Enforce that no secret ever appears in code, config files, or environment variables. All secrets flow exclusively through this tool from Key Vault.

### Responsibilities
- Retrieve a secret by name from Azure Key Vault
- Cache secrets in memory for a short TTL (reduce Key Vault round trips)
- Support secret versioning (retrieve specific version)
- Detect secret rotation and refresh cache

### MUST Do
- Use Azure Managed Identity — no client secrets for Key Vault auth
- Never log secret values — only secret names
- Cache with short TTL (5 minutes maximum)

### MUST NEVER Do
- Store secrets in the database
- Return secrets in API responses

### Input
```
SecretManagerTool.get_secret(name: str) → str
SecretManagerTool.get_secret_version(name: str, version: str) → str
```

### Dependencies
- `azure-keyvault-secrets` SDK
- `azure-identity` — Managed Identity
- In-memory cache with TTL

### Used By
LLMTool, OCRTool (Azure DI), AzureBlobStorageTool, ERPAdapterTool, EncryptionTool

---

*END OF SECURITY TOOLS*

---

## SECTION 4 — Tool Dependency Matrix

### Reading the Matrix
- **R** = Reads from / Receives output from
- **W** = Writes to / Provides input to
- **—** = No dependency
- Rows = tools that have dependencies
- Columns = tools being depended upon
- **NO circular dependencies exist** — the matrix is strictly upper-triangular when sorted by dependency level

### Platform Tool Dependencies (All tools may use these — not repeated per row)

| Tool | ConfigurationTool | LoggingTool | AuditTool | RetryTool |
|---|---|---|---|---|
| All Business Tools | R | W | W (where compliance-relevant) | W (where external calls made) |

### Cross-Category Dependencies

| Tool (Dependent) | FileTool | StorageTool | PDFTool | ImageTool | HashTool | LLMTool | PromptTool | ValidationTool | ComparisonTool | ERPAdapterTool |
|---|---|---|---|---|---|---|---|---|---|---|
| FileValidationTool | **R** | — | — | — | **R** | — | — | — | — | — |
| PDFTool | — | — | — | — | — | — | — | — | — | — |
| ImageTool | — | — | **R** | — | — | — | — | — | — | — |
| OCRTool | — | — | — | **R** | — | — | — | — | — | — |
| TesseractTool | — | — | — | — | — | — | — | — | — | — |
| AzureOCRTool | — | — | — | — | — | — | — | — | — | — |
| ExtractionTool | — | — | — | — | — | **R** | **R** | — | — | — |
| ClassificationTool | — | — | — | — | — | **R** | **R** | — | — | — |
| BusinessProfileTool | — | — | — | — | — | **R** | **R** | — | — | — |
| NormalizationTool | — | — | — | — | — | — | — | — | — | — |
| ConfidenceTool | — | — | — | — | — | — | — | — | — | — |
| GSTValidationTool | — | — | — | — | — | — | — | **R** | — | — |
| PANValidationTool | — | — | — | — | — | — | — | **R** | — | — |
| ArithmeticValidationTool | — | — | — | — | — | — | — | **R** | — | — |
| TaxValidationTool | — | — | — | — | — | — | — | **R** | — | — |
| DuplicateDetectionTool | — | — | — | — | **R** | — | — | — | **R** | — |
| ProfileValidationTool | — | — | — | — | — | — | — | **R** | — | — |
| BusinessRuleTool | — | — | — | — | — | — | — | **R** | — | — |
| VendorMatchingTool | — | — | — | — | — | — | — | — | **R** | — |
| ThreeWayMatchingTool | — | — | — | — | — | — | — | — | **R** | — |
| PostingTool | — | — | — | — | — | — | — | — | — | **R** |
| JournalBuilderTool | — | — | — | — | — | — | — | — | — | — |
| PaymentScheduleTool | — | — | — | — | — | — | — | — | — | **R** |
| ApprovalTool | — | — | — | — | — | — | — | — | — | — |
| ExceptionTool | — | — | — | — | — | — | — | — | — | — |
| NotificationTool | — | — | — | — | — | — | — | — | — | — |

### Dependency Levels Summary

```
Level 0 (no tool deps):
  ConfigurationTool, LoggingTool, HashTool, EncryptionTool, RuleEngineTool
  MaskingTool, PIITool, VarianceTool, ComparisonTool, SimilarityTool

Level 1 (depends only on Level 0):
  FileTool, AuditTool, RetryTool, NormalizationTool, AuthenticationTool
  DeskewTool, PageRotationTool, TextCleaningTool, LanguageDetectionTool
  PromptTemplateTool, ProviderSelectionTool, FeatureFlagTool, ThresholdTool

Level 2 (depends on Level 0–1):
  StorageTool, PDFTool, ImageTool, ChecksumTool, TesseractTool, AzureOCRTool
  ValidationTool, ToleranceValidationTool, AuthorizationTool, PromptLoaderTool
  PromptVersionTool, SecretManagerTool

Level 3 (depends on Level 0–2):
  FileValidationTool, ImageEnhancementTool, OCRTool, OCRConfidenceTool
  TableExtractionTool, BoundingBoxTool, GSTValidationTool, PANValidationTool
  ArithmeticValidationTool, DateValidationTool, CurrencyValidationTool
  InvoiceNumberValidationTool, PromptTool, PromptAuditTool

Level 4 (depends on Level 0–3):
  LLMTool, MandatoryFieldTool, BusinessRuleTool, DuplicateDetectionTool
  VendorMatchingTool, PromptRegistryTool, TokenTrackingTool

Level 5 (depends on Level 0–4):
  ExtractionTool, ClassificationTool, BusinessProfileTool, ConfidenceTool
  ProfileValidationTool, VendorValidationTool, POMatchingTool, GRNMatchingTool
  TaxValidationTool, MockERPTool, SAPAdapterTool, JournalBuilderTool

Level 6 (depends on Level 0–5):
  ThreeWayMatchingTool, PostingTool, ReasoningTool, SummaryTool
  ApprovalTool, ExceptionTool, NotificationTool

Level 7 (depends on Level 0–6):
  PaymentScheduleTool, ResumeTool, WorkflowStateTool, TimelineTool
```

---

## SECTION 5 — Tool Usage Matrix (Agents × Tools)

**Legend:** ✓ = Agent uses this tool directly

| Agent | FileTool | StorageTool | HashTool | VirusScanTool | FileValidationTool | PDFTool | ImageTool | OCRTool | ExtractionTool | NormalizationTool | GSTValidationTool | PANValidationTool | ArithmeticValidationTool | TaxValidationTool | DuplicateDetectionTool | BusinessRuleTool | ProfileValidationTool | VendorMatchingTool | POMatchingTool | GRNMatchingTool | ThreeWayMatchingTool | ConfidenceTool | BusinessProfileTool | ClassificationTool | ERPAdapterTool | PostingTool | PaymentScheduleTool | ApprovalTool | ExceptionTool | NotificationTool | AuditTool |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **UploadAgent** | ✓ | ✓ | ✓ | ✓ | ✓ | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ |
| **ClassificationAgent** | — | — | — | — | — | ✓ | ✓ | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | — | — | — | — | — | — | ✓ |
| **OCRAgent** | — | — | ✓ | — | — | — | ✓ | ✓ | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ |
| **ExtractionAgent** | — | — | — | — | — | — | — | — | ✓ | ✓ | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ |
| **UniversalValidationAgent** | — | — | — | — | — | — | — | — | — | — | ✓ | ✓ | ✓ | — | ✓ | ✓ | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ |
| **BusinessProfileAgent** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | — | — | — | — | — | — | ✓ | — | — | — | — | — | — | — | ✓ |
| **ProfileValidationAgent** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | ✓ | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ |
| **VendorMatchingAgent** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | — | — | — | — | — | — | — | — | — | — | — | — | ✓ |
| **DuplicateDetectionAgent** | — | — | ✓ | — | — | — | — | — | — | — | — | — | — | — | ✓ | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ |
| **TaxValidationAgent** | — | — | — | — | — | — | — | — | — | — | ✓ | ✓ | — | ✓ | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ |
| **POMatchingAgent** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | ✓ | ✓ | — | — | — | — | — | — | — | — | — | ✓ |
| **ConfidenceAgent** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | — | — | — | — | — | — | — | — | ✓ |
| **DecisionAgent** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ |
| **ExceptionAgent** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | ✓ | ✓ |
| **ApprovalAgent** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | — | ✓ | ✓ |
| **ERPPostingAgent** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | — | — | — | — | ✓ |
| **PaymentAgent** | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | — | — | — | ✓ |
| **NotificationAgent** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ | ✓ |
| **AuditAgent** | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✓ |

---

## SECTION 6 — Future Extensibility

### 6.1 Adding a New OCR Provider (e.g. Google Vision AI)

**What changes:**
1. Create `app/tools/ocr/google_vision_provider.py` implementing `OCRProviderInterface`
2. Register in `app/services/ocr_service.py` service factory
3. Update `provider_config.yaml`: `ocr.provider: google_vision`

**What does NOT change:**
- OCRTool (router — provider-agnostic already)
- OCRAgent
- Any graph
- Any other tool
- Any schema

---

### 6.2 Adding SAP ERP Integration

**What changes:**
1. Implement `app/tools/erp/sap_provider.py` (currently stub — complete the BAPI mappings)
2. Update `provider_config.yaml`: `erp.provider: sap`
3. Add SAP credentials to Azure Key Vault
4. Add SAP field mappings to `erp.field_mapping.yaml`

**What does NOT change:**
- ERPAdapterTool
- ERPPostingAgent
- JournalBuilderTool
- PostingTool
- Any graph

---

### 6.3 Adding Email Invoice Ingestion

**What changes:**
1. Create `app/api/v1/email_ingest.py` — FastAPI endpoint that receives email webhook
2. Create `app/agents/email_intake_agent.py` — downloads attachment, calls UploadAgent
3. Add email intake node to InvoiceProcessingGraph (before `upload_node`)
4. Configure email provider in `provider_config.yaml`

**What does NOT change:**
- All existing tools
- All existing agents (UploadAgent and downstream are reused)
- All existing graphs (InvoiceProcessingGraph is extended, not rewritten)

---

### 6.4 Adding Microsoft Teams Notifications

**What changes:**
1. Implement `app/notifications/teams_channel.py` implementing `NotificationProviderInterface`
2. Update `provider_config.yaml`: `notification.channels: [email, teams]`
3. Add Teams webhook URL to Key Vault

**What does NOT change:**
- NotificationTool
- NotificationAgent
- Any graph

---

### 6.5 Adding a New Business Profile

**What changes:**
1. Add new profile definition to `business_rules.yaml`:
   ```yaml
   NEW_PROFILE_NAME:
     mandatory_fields: [...]
     matching_required: true/false
     ...
   ```
2. Add profile to the `BusinessProfile` enum in `app/shared/enums.py`
3. Update `confidence_config.yaml` if profile needs custom weights

**What does NOT change:**
- BusinessProfileTool
- ProfileValidationTool
- BusinessProfileAgent
- Any graph

---

### 6.6 Adding a New Validation Rule

**What changes:**
1. Add rule to the appropriate rule set in `business_rules.yaml`:
   ```yaml
   - rule_id: "NEW_RULE_001"
     rule_name: "New Validation Check"
     severity: HIGH
     rule_type: COMPARISON
     parameters: { ... }
   ```

**What does NOT change:**
- ValidationTool
- BusinessRuleTool
- RuleEngineTool
- Any agent
- Any graph

---

### 6.7 Supporting Multi-Tenancy

**What changes:**
1. Ensure `tenant_id` is propagated in all API requests (already designed in all models)
2. Create tenant config entries in `config_entries` table
3. Optionally create tenant-specific prompts in `prompt_versions` table
4. Deploy tenant-isolated Azure Resource Groups using Bicep template parameterisation

**What does NOT change:**
- Any tool (all tools already accept `tenant_id` in inputs)
- Any agent
- Any graph

---

### 6.8 Supporting a New LLM Provider (e.g. Azure OpenAI, Anthropic Claude)

**What changes:**
1. Implement `app/services/azure_openai_provider.py` implementing `LLMProviderInterface`
2. Update `provider_config.yaml`: `llm.provider: azure_openai`
3. Add Azure OpenAI credentials to Key Vault

**What does NOT change:**
- LLMTool (router — provider-agnostic)
- ExtractionTool
- ClassificationTool
- BusinessProfileTool
- Any agent
- Any graph

---

## SECTION 7 — Engineering Best Practices

### 7.1 Naming Conventions

| Item | Convention | Example |
|---|---|---|
| Tool class name | PascalCase + "Tool" suffix | `GSTValidationTool` |
| Tool file name | snake_case + "_tool.py" suffix | `gst_validation_tool.py` |
| Tool method name | snake_case, verb-first | `validate()`, `extract()`, `compute_hash()` |
| Input model name | PascalCase + "Input" suffix | `GSTValidationInput` |
| Output model name | PascalCase + "Result" suffix | `GSTValidationResult` |
| Error codes | SCREAMING_SNAKE_CASE | `GST_FORMAT_INVALID` |
| Config keys | lowercase dot-separated | `gst.live_verification` |
| Audit event names | SCREAMING_SNAKE_CASE | `GST_VALIDATION_COMPLETED` |

### 7.2 Folder Structure

```
app/tools/
├── {category}/
│   ├── __init__.py
│   ├── {tool_name}_tool.py        # tool implementation
│   └── {provider_name}_provider.py  # provider implementation (for interface tools)
│
tests/unit/tools/
├── {category}/
│   ├── test_{tool_name}_tool.py
│   └── test_{provider_name}_provider.py
```

### 7.3 Dependency Injection Standards

- Every tool declares its dependencies as constructor parameters with type annotations
- All dependencies must be interfaces (Abstract Base Classes), never concrete classes
- Tools are never instantiated directly in business code — use the service factory
- Test fixtures provide mock implementations of all interfaces

```
# Correct — inject interface
class GSTValidationTool:
    def __init__(
        self,
        config: ConfigurationToolInterface,
        logger: LoggingToolInterface,
        audit: AuditToolInterface
    ): ...

# Wrong — concrete class
class GSTValidationTool:
    def __init__(self):
        self.config = ConfigurationTool()   # ← FORBIDDEN
```

### 7.4 Testing Standards

Every tool must have tests in `tests/unit/tools/{category}/test_{tool}_tool.py`.

**Required test cases for every tool:**
1. `test_happy_path` — valid input, expected output
2. `test_empty_input` — empty or None input fields
3. `test_invalid_input` — input that should fail validation
4. `test_boundary_values` — threshold/tolerance edge cases
5. `test_failure_returns_result` — errors return ToolResult, not exceptions
6. `test_no_external_calls` — mocks verify no real DB/LLM/storage called

**Test execution time limit:** All unit tests must complete in < 1 second.

**No integration tests at tool level** — tools are unit-tested in isolation. Integration tests live in `tests/integration/`.

### 7.5 Logging Standards

Every tool must emit a `ToolExecutionLog` via `LoggingTool`. The log must include:
- `tool_name` — class name
- `method_called` — method name
- `duration_ms` — wall clock time
- `success` — bool
- `workflow_id` — if available from input
- `document_id` — if available from input
- `input_hash` — SHA-256 of serialised input (never the input itself)

**NEVER log:**
- Raw invoice content
- PII fields (GSTIN, PAN, names, amounts in plain text)
- API keys or tokens
- Full stack traces in production (use error code + log reference)

### 7.6 Versioning Standards

Tools themselves are not versioned — they are code, and code is versioned through Git. What IS versioned:
- **Prompts** — versioned in `prompt_versions` table and filesystem
- **Business rules** — versioned via `rule_set_version` in `business_rules.yaml`
- **Approval matrix** — versioned in `approval_matrix.yaml`
- **Configuration** — change history tracked in `config_entries` table

When a tool's interface changes in a breaking way, the tool name must reflect it: `GSTValidationToolV2` in a separate file, with the old tool deprecated (not deleted until all callers are migrated).

### 7.7 Configuration Standards

Every configurable value must:
1. Have a documented key in the format `{category}.{subcategory}.{parameter}`
2. Have a documented default in the tool specification
3. Be accessed only via `ConfigurationTool.get()` — never via `os.environ` directly
4. Be documented in `app/config/settings.py` with type annotation and description

**Configuration key naming example:**
```
✓ ocr.tesseract.default_language
✓ validation.gst.strict_mode
✓ matching.vendor.fuzzy_algorithm
✓ approval.matrix.sla_hours.ap_executive
✗ TESSERACT_LANGUAGE        (environment variable format — wrong)
✗ default_language          (unqualified — wrong)
```

### 7.8 Performance Standards

| Tool Category | Target Execution Time | Notes |
|---|---|---|
| Document Tools | < 200ms | FileTool, HashTool — CPU only |
| OCR Tools | < 3s per page | Provider-dependent |
| AI/LLM Tools | < 30s | Network call — async preferred |
| Validation Tools | < 50ms | Deterministic — no I/O |
| Matching Tools | < 200ms | DB query — indexed |
| ERP Tools | < 10s | Network call — retries included |
| Workflow Tools | < 100ms | DB writes |
| Platform Tools | < 10ms | ConfigurationTool from Redis cache |

### 7.9 Security Standards

1. **No secrets in code** — use `SecretManagerTool` exclusively
2. **PII masking** — all logging calls must pass through `MaskingTool.mask_for_log()` for any data that could contain PII
3. **Input sanitisation** — all string inputs are sanitised for null bytes and control characters before processing
4. **Pydantic validation** — all inputs are Pydantic models with field validators — no raw dict processing
5. **Sandbox LLM outputs** — LLM JSON outputs are parsed through strict schema validation before use
6. **Audit sensitive actions** — every modification to financial data writes an `AuditEvent`

### 7.10 Documentation Standards

Each tool must have:
1. A docstring on the class explaining its purpose in one sentence
2. A docstring on the `execute()` / primary method explaining what it does, inputs, and outputs
3. An entry in `tools.md` (this document) with the full specification
4. A changelog entry in `CHANGELOG.md` when the tool interface changes

**No inline comments** unless the code is non-obvious. The tool specification in `tools.md` is the primary documentation — code should be self-documenting through naming.

### 7.11 New Tool Checklist

Before submitting a new tool for review, confirm:

- [ ] Tool has a single, clear responsibility
- [ ] Tool is named with PascalCase + "Tool" suffix
- [ ] Tool file is in the correct category folder
- [ ] All dependencies are injected (no `import ConcreteClass` in business tools)
- [ ] Input and output are typed Pydantic models
- [ ] `execute()` (or primary method) never raises unhandled exceptions to callers
- [ ] All errors return `ToolResult(success=False, error_code=...)` not exceptions
- [ ] `LoggingTool` is called at start and end of every method
- [ ] `AuditTool` is called for compliance-relevant actions
- [ ] All config values are read via `ConfigurationTool`
- [ ] Unit tests written for happy path and all failure modes
- [ ] Tool specification added to `tools.md`
- [ ] No PII logged
- [ ] No secrets in code

---

*END OF TOOLS.MD — Version 1.0.0*
