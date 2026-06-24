# Enterprise AI Agent Platform — Agent Specifications

> **Document Purpose**: Complete specification of all 19 agents in the AP Automation Platform.
> Every agent is a thin LangGraph node that orchestrates tool calls and updates WorkflowState.
> No business logic lives inside agents — all logic is in the Tool Layer.
>
> **Source of truth**: `ARCHITECTURE.md` (agent tables), `tools.md` (Agent × Tool matrix)
> **Design principle**: Agents own *orchestration*; Tools own *computation*

---

## Table of Contents

1. [Agent Architecture Overview](#1-agent-architecture-overview)
2. [Agent Specifications](#2-agent-specifications)
   - [01. UploadAgent](#01-uploadagent)
   - [02. ClassificationAgent](#02-classificationagent)
   - [03. OCRAgent](#03-ocragent)
   - [04. ExtractionAgent](#04-extractionagent)
   - [05. ValidationAgent](#05-validationagent)
   - [06. BusinessProfileAgent](#06-businessprofileagent)
   - [07. ProfileValidationAgent](#07-profilevalidationagent)
   - [08. POMatchingAgent](#08-pomatchingagent)
   - [09. GRNMatchingAgent](#09-grnmatchingagent)
   - [10. ThreeWayMatchingAgent](#10-threewaymatchingagent)
   - [11. ConfidenceAgent](#11-confidenceagent)
   - [12. ExceptionAgent](#12-exceptionagent)
   - [13. ApprovalAgent](#13-approvalagent)
   - [14. ERPPostingAgent](#14-erppostingagent)
   - [15. PaymentAgent](#15-paymentagent)
   - [16. NotificationAgent](#16-notificationagent)
   - [17. RetryAgent](#17-retryagent)
   - [18. HumanReviewAgent](#18-humanreviewagent)
   - [19. AuditAgent](#19-auditagent)
3. [Agent Interaction Matrix](#3-agent-interaction-matrix)
4. [Agent State Ownership Map](#4-agent-state-ownership-map)

---

## 1. Agent Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AGENT CONTRACT                                    │
│                                                                          │
│  Input : WorkflowState (read-only access to all prior state)            │
│  Output: WorkflowState (agent writes ONLY to its designated sections)   │
│  Side effects: Audit log entry via AuditTool — mandatory                │
│  Error contract: Raise AgentException with error_code, severity         │
│  Retry contract: Declare max_retries, backoff_strategy in agent config  │
│  Human trigger: Return interrupt_required=True from precondition check  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Agent Categories

| Category | Agents | Role |
|---|---|---|
| Ingestion | UploadAgent, ClassificationAgent | Accept and triage incoming documents |
| Extraction | OCRAgent, ExtractionAgent | Convert documents to structured data |
| Validation | ValidationAgent, BusinessProfileAgent, ProfileValidationAgent | Ensure data correctness |
| Matching | POMatchingAgent, GRNMatchingAgent, ThreeWayMatchingAgent | Match invoice to purchase documents |
| Intelligence | ConfidenceAgent | Score overall extraction and match quality |
| Exception | ExceptionAgent, RetryAgent | Route and manage failures |
| Approval | ApprovalAgent, HumanReviewAgent | Obtain authorisation |
| ERP & Payment | ERPPostingAgent, PaymentAgent | Execute financial transactions |
| Notification | NotificationAgent | Communicate events to stakeholders |
| Audit | AuditAgent | Maintain immutable audit trail |

### Universal Agent Constraints (apply to ALL agents)

- Agents MUST NOT contain business logic — delegate to tools
- Agents MUST NOT read from database directly — use repository interfaces via tools
- Agents MUST NOT log PII or full invoice content — log hashes and document IDs
- Agents MUST emit at least one audit event per execution
- Agents MUST update `workflow_state.updated_at` and `workflow_state.current_agent`
- Agents MUST respect tenant isolation — never mix state across tenants
- Agents MUST declare their retry policy in agent config YAML, not in code

---

## 2. Agent Specifications

---

### 01. UploadAgent

**Category**: Ingestion | **Graph**: InvoiceProcessingGraph | **Node ID**: `upload`

#### Purpose
Accept an incoming document file, validate it meets platform intake requirements, store it durably, create the initial WorkflowState record, and hand off to ClassificationAgent.

#### Responsibility
- Validate file type, size, and format constraints
- Scan for malware and compute checksum
- Store file to configured storage provider (Azure Blob or local)
- Create initial WorkflowState with document metadata
- Emit DOCUMENT_UPLOADED audit event

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `raw_upload.file_bytes` | bytes | Raw file content from API |
| `raw_upload.filename` | str | Original filename from uploader |
| `raw_upload.tenant_id` | str | Tenant identifier |
| `raw_upload.uploaded_by` | str | User ID of uploader |
| `raw_upload.source_channel` | str | EMAIL / PORTAL / API / SFTP |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `document.id` | UUID | Platform-assigned document ID |
| `document.storage_path` | str | Full storage URI |
| `document.file_hash` | str | SHA-256 of file content |
| `document.file_size_bytes` | int | Validated file size |
| `document.mime_type` | str | Detected MIME type |
| `document.page_count` | int | Page count from PDF metadata |
| `document.upload_timestamp` | datetime | UTC timestamp |
| `document.virus_scan_result` | str | CLEAN / QUARANTINED |
| `workflow.status` | str | UPLOADED |
| `workflow.current_agent` | str | upload_agent |

#### Tools Used
| Tool | Purpose |
|---|---|
| `FileValidationTool` | Validate extension, MIME type, size limits |
| `VirusScanTool` | Malware scan before any processing |
| `HashTool` | Compute SHA-256 for deduplication and integrity |
| `StorageTool` | Persist file to storage provider |
| `MetadataTool` | Extract PDF metadata (page count, author, creation date) |
| `PageTool` | Count and validate page structure |
| `AuditTool` | Emit DOCUMENT_UPLOADED event |
| `ConfigurationTool` | Read upload limits and allowed types per tenant |
| `AuthorizationTool` | Verify uploader has INVOICE_UPLOAD permission |

#### Preconditions
- `raw_upload.tenant_id` exists and is active in tenant registry
- `raw_upload.uploaded_by` is authenticated and has `INVOICE_UPLOAD` permission
- File content is not null or empty

#### Postconditions
- `document.id` is assigned and unique
- File is stored durably with confirmed write
- `document.virus_scan_result` is CLEAN (agent halts workflow if QUARANTINED)
- Audit event DOCUMENT_UPLOADED is committed

#### Failure Handling
| Failure | Action |
|---|---|
| File fails MIME validation | Reject immediately; emit UPLOAD_REJECTED; return error to API |
| Virus detected | Quarantine file; emit VIRUS_DETECTED; halt workflow; alert security |
| Storage write fails | Retry with exponential backoff; if exhausted, emit STORAGE_FAILURE |
| Checksum mismatch on read-back | Retry storage write; escalate to ExceptionAgent on second failure |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 3 |
| Backoff strategy | Exponential |
| Base delay | 1 second |
| Max delay | 15 seconds |
| Retryable errors | StorageWriteError, NetworkTimeoutError |
| Non-retryable | ValidationError, VirusDetectedError, AuthorizationError |

#### Human Review Trigger
- Virus scan returns UNCERTAIN (ambiguous signature match)
- File passes validation but zero extractable pages are detected
- Upload source is EMAIL and attachment count exceeds `upload.max_email_attachments` config

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| DOCUMENT_UPLOADED | Successful storage | INFO |
| UPLOAD_REJECTED | Validation failure | WARNING |
| VIRUS_DETECTED | Malware found | CRITICAL |
| STORAGE_FAILURE | Write error after retries | ERROR |
| UPLOAD_QUARANTINED | Ambiguous virus result | WARNING |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `upload.duration_ms` | Histogram | Time from receipt to stored |
| `upload.file_size_bytes` | Histogram | Distribution of file sizes |
| `upload.virus_scan_duration_ms` | Histogram | Scan latency |
| `upload.success_rate` | Gauge | Success / total ratio per hour |
| `upload.rejected_by_reason` | Counter | Breakdown by rejection cause |

#### Future Extensibility
- Add SFTP ingestion channel by implementing SFTPSourceAdapter against FileIngestionInterface
- Add email attachment extraction by wiring EmailIngestionTool to UploadAgent
- Add duplicate-at-upload detection using HashTool before storage (currently done in ValidationAgent)

---

### 02. ClassificationAgent

**Category**: Ingestion | **Graph**: InvoiceProcessingGraph | **Node ID**: `classify`

#### Purpose
Determine the document class (DIGITAL, SCANNED, HANDWRITTEN, UNKNOWN), assess image quality, and route to the appropriate OCR strategy.

#### Responsibility
- Classify document rendering type using image analysis heuristics
- Measure image quality (DPI, contrast, skew, noise)
- Select OCR provider (Tesseract for scanned, GPT-4o Vision for handwritten, bypass for digital)
- Flag low-quality images for enhancement before OCR
- Update WorkflowState with classification result and recommended OCR path

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `document.id` | UUID | Document identifier |
| `document.storage_path` | str | URI to stored file |
| `document.mime_type` | str | Confirmed MIME type |
| `document.page_count` | int | Number of pages |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `classification.document_class` | str | DIGITAL / SCANNED / HANDWRITTEN / UNKNOWN |
| `classification.ocr_strategy` | str | BYPASS / TESSERACT / GPT_VISION |
| `classification.image_quality_score` | float | 0.0–1.0 per page (avg) |
| `classification.requires_enhancement` | bool | Whether DeskewTool should run |
| `classification.language_hint` | str | ISO 639-1 language code |
| `classification.confidence` | float | Classification confidence score |
| `workflow.status` | str | CLASSIFIED |

#### Tools Used
| Tool | Purpose |
|---|---|
| `StorageTool` | Retrieve file for analysis |
| `PDFTool` | Determine if PDF has native text layer |
| `ImageTool` | Load and assess page images |
| `OCRConfidenceTool` | Estimate image suitability for OCR |
| `DeskewTool` | Measure skew angle (correction deferred to OCRAgent) |
| `LanguageDetectionTool` | Detect primary language |
| `ProviderSelectionTool` | Select OCR provider based on document class |
| `AuditTool` | Emit DOCUMENT_CLASSIFIED event |

#### Preconditions
- `document.storage_path` resolves to a readable file
- `document.virus_scan_result` is CLEAN

#### Postconditions
- `classification.document_class` is set to a valid enum value
- `classification.ocr_strategy` is set and valid
- At least one audit event is committed

#### Failure Handling
| Failure | Action |
|---|---|
| File not found in storage | Emit STORAGE_RETRIEVAL_FAILURE; route to ExceptionAgent |
| All pages are blank | Set class to UNKNOWN; route to HumanReviewAgent |
| Language detection fails | Default to `classification.language_hint = "en"` and continue |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 2 |
| Backoff strategy | Linear |
| Base delay | 2 seconds |
| Retryable errors | StorageReadError |
| Non-retryable | DocumentClassUnknown (route to human, not retry) |

#### Human Review Trigger
- `classification.document_class` is UNKNOWN after classification
- `classification.image_quality_score` < `ocr.min_image_quality_threshold` (config)
- Document contains mixed classes (some pages digital, some handwritten)

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| DOCUMENT_CLASSIFIED | Classification complete | INFO |
| QUALITY_BELOW_THRESHOLD | Image quality score under config threshold | WARNING |
| CLASSIFICATION_UNKNOWN | Unable to determine document class | WARNING |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `classification.duration_ms` | Histogram | End-to-end classification time |
| `classification.class_distribution` | Counter | Counts per DIGITAL/SCANNED/HANDWRITTEN |
| `classification.avg_image_quality` | Gauge | Rolling average quality score |
| `classification.enhancement_required_rate` | Gauge | Fraction requiring enhancement |

#### Future Extensibility
- Add PDF/A compliance detection to flag archival documents for alternative handling
- Add form-type detection (structured vs unstructured invoice) to route to FormExtractionTool

---

### 03. OCRAgent

**Category**: Extraction | **Graph**: InvoiceProcessingGraph | **Node ID**: `ocr`

#### Purpose
Convert scanned or handwritten page images to raw text using the strategy selected by ClassificationAgent, applying image enhancement if required.

#### Responsibility
- Apply image pre-processing (deskew, enhance contrast, denoise) for scanned documents
- Execute the selected OCR provider (Tesseract or GPT-4o Vision)
- Compute per-page OCR confidence scores
- Clean and normalise raw OCR output
- Store raw OCR text in WorkflowState for ExtractionAgent

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `document.storage_path` | str | URI to stored file |
| `classification.document_class` | str | DIGITAL / SCANNED / HANDWRITTEN |
| `classification.ocr_strategy` | str | BYPASS / TESSERACT / GPT_VISION |
| `classification.requires_enhancement` | bool | Whether to run enhancement |
| `classification.language_hint` | str | Language code for OCR |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `ocr.raw_text` | str | Full concatenated OCR output |
| `ocr.page_texts` | list[str] | Per-page OCR text |
| `ocr.confidence_scores` | list[float] | Per-page confidence (0.0–1.0) |
| `ocr.avg_confidence` | float | Mean confidence across all pages |
| `ocr.provider_used` | str | TESSERACT / GPT_VISION / BYPASS |
| `ocr.enhancement_applied` | bool | Whether image enhancement ran |
| `ocr.word_count` | int | Total word count of output |
| `workflow.status` | str | OCR_COMPLETE |

#### Tools Used
| Tool | Purpose |
|---|---|
| `StorageTool` | Retrieve page images for processing |
| `DeskewTool` | Correct page rotation and skew |
| `ImageEnhancementTool` | Improve contrast, denoise, binarise |
| `PageRotationTool` | Correct page orientation |
| `OCRTool` | Dispatch to correct OCR provider |
| `TesseractTool` | Run Tesseract for scanned documents |
| `AzureOCRTool` | Azure Cognitive Services OCR (optional) |
| `OCRConfidenceTool` | Score output quality |
| `TextCleaningTool` | Normalise whitespace, strip artefacts |
| `TokenTrackingTool` | Track GPT Vision token consumption |
| `AuditTool` | Emit OCR_COMPLETE event |

#### Preconditions
- `classification.ocr_strategy` is TESSERACT or GPT_VISION (agent short-circuits to BYPASS if DIGITAL)
- Storage path resolves to readable file

#### Postconditions
- `ocr.raw_text` is non-empty for non-blank documents
- `ocr.avg_confidence` is recorded
- Token usage is committed to tenant quota if GPT Vision was used

#### Failure Handling
| Failure | Action |
|---|---|
| Tesseract returns empty output | Retry with enhanced image; if still empty, route to HumanReviewAgent |
| GPT Vision token budget exceeded | Emit TOKEN_BUDGET_EXCEEDED; route to ExceptionAgent |
| OCR confidence < threshold | Flag `ocr.low_confidence = True`; ConfidenceAgent will handle downstream scoring |
| Storage read failure | Retry 3 times; escalate to ExceptionAgent on exhaustion |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 3 |
| Backoff strategy | Exponential |
| Base delay | 2 seconds |
| Retryable errors | StorageReadError, OCRTimeoutError |
| Non-retryable | TokenBudgetExceededError |

#### Human Review Trigger
- `ocr.avg_confidence` < `ocr.min_acceptable_confidence` config (e.g., 0.6)
- OCR output word count < `ocr.min_word_count` config (e.g., 10)
- All retry attempts return empty text

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| OCR_COMPLETE | OCR finished successfully | INFO |
| OCR_LOW_CONFIDENCE | Confidence below threshold | WARNING |
| OCR_EMPTY_OUTPUT | No text extracted | ERROR |
| OCR_TOKEN_BUDGET_EXCEEDED | LLM quota hit | ERROR |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `ocr.duration_ms` | Histogram | Total OCR processing time |
| `ocr.avg_confidence` | Histogram | Distribution of confidence scores |
| `ocr.provider_usage` | Counter | Calls per provider |
| `ocr.enhancement_improvement` | Gauge | Confidence delta after enhancement |
| `ocr.token_usage` | Counter | GPT Vision tokens consumed |

#### Future Extensibility
- Add Google Vision OCR provider by implementing `OCRProviderInterface` in `GoogleVisionTool`
- Add AWS Textract provider for table-heavy invoices
- Add parallel page processing for large documents (currently sequential per page)

---

### 04. ExtractionAgent

**Category**: Extraction | **Graph**: InvoiceProcessingGraph | **Node ID**: `extract`

#### Purpose
Parse raw OCR text (or native PDF text) using the LLM to extract all structured invoice fields into the canonical InvoiceData schema.

#### Responsibility
- Load the versioned extraction prompt for the tenant
- Call LLM with raw text and structured output schema
- Map extracted fields to canonical InvoiceData types
- Record per-field confidence scores
- Normalise dates, currencies, and numeric formats
- Detect and record fields that could not be extracted

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `ocr.raw_text` | str | Full OCR or native text |
| `ocr.page_texts` | list[str] | Per-page text |
| `classification.document_class` | str | Guides extraction strategy |
| `workflow.tenant_id` | str | For prompt and config lookup |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `invoice.vendor_name` | str | Extracted vendor name |
| `invoice.vendor_gstin` | str | GST identification number |
| `invoice.vendor_pan` | str | PAN number |
| `invoice.invoice_number` | str | Invoice reference number |
| `invoice.invoice_date` | date | Invoice issue date |
| `invoice.due_date` | date | Payment due date |
| `invoice.po_number` | str | Purchase order reference |
| `invoice.grn_number` | str | Goods receipt reference |
| `invoice.line_items` | list[LineItem] | Itemised goods/services |
| `invoice.subtotal` | Decimal | Pre-tax total |
| `invoice.tax_amount` | Decimal | Total tax charged |
| `invoice.total_amount` | Decimal | Invoice grand total |
| `invoice.currency` | str | ISO 4217 currency code |
| `invoice.payment_terms` | str | Payment terms string |
| `invoice.bank_details` | BankDetails | Beneficiary account info |
| `extraction.field_confidences` | dict[str, float] | Per-field confidence map |
| `extraction.missing_fields` | list[str] | Fields not found in document |
| `extraction.prompt_version` | str | Version of extraction prompt used |
| `extraction.llm_model` | str | Model identifier used |
| `extraction.token_count` | int | Tokens consumed |
| `workflow.status` | str | EXTRACTED |

#### Tools Used
| Tool | Purpose |
|---|---|
| `PromptLoaderTool` | Load versioned extraction prompt for tenant |
| `LLMTool` | Call LLM with structured output schema |
| `ExtractionTool` | Parse and validate LLM JSON response |
| `NormalizationTool` | Standardise dates, currencies, numbers |
| `ConfidenceTool` | Score per-field extraction confidence |
| `TokenTrackingTool` | Track and enforce token budget |
| `ReasoningTool` | Capture LLM reasoning chain for explainability |
| `AuditTool` | Emit INVOICE_EXTRACTED event |
| `ConfigurationTool` | Read extraction config (model, temperature) |

#### Preconditions
- `ocr.raw_text` is non-empty OR `classification.document_class` is DIGITAL
- Token budget has remaining capacity for this tenant

#### Postconditions
- `invoice` section of WorkflowState is populated
- `extraction.field_confidences` entries exist for all mandatory fields
- Token consumption is committed to tenant quota

#### Failure Handling
| Failure | Action |
|---|---|
| LLM returns malformed JSON | Retry with temperature=0; if second attempt fails, route to ExceptionAgent |
| Token budget exceeded | Halt; emit TOKEN_BUDGET_EXCEEDED; notify tenant admin |
| All mandatory fields missing | Route to HumanReviewAgent |
| LLM service unavailable | Retry with exponential backoff; escalate after 3 failures |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 3 |
| Backoff strategy | Exponential |
| Base delay | 2 seconds |
| Max delay | 30 seconds |
| Retryable errors | LLMTimeoutError, LLMServiceError |
| Non-retryable | TokenBudgetExceededError, InvalidPromptError |

#### Human Review Trigger
- Mandatory field confidence < `extraction.min_field_confidence` (e.g., 0.75)
- `invoice.total_amount` is null or zero
- `invoice.vendor_gstin` and `invoice.vendor_pan` are both missing
- `extraction.missing_fields` contains more than `extraction.max_missing_fields` config items

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| INVOICE_EXTRACTED | Extraction complete | INFO |
| EXTRACTION_LOW_CONFIDENCE | Field confidence below threshold | WARNING |
| EXTRACTION_MANDATORY_FIELD_MISSING | Required field not found | WARNING |
| EXTRACTION_LLM_FAILED | LLM returned error after retries | ERROR |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `extraction.duration_ms` | Histogram | LLM call round-trip time |
| `extraction.avg_field_confidence` | Histogram | Distribution of field-level scores |
| `extraction.missing_field_rate` | Gauge | Fraction of fields not extracted |
| `extraction.token_usage` | Counter | LLM tokens per document |
| `extraction.model_usage` | Counter | Calls per model version |

#### Future Extensibility
- Add multi-page invoice extraction by splitting into page-level extraction followed by merge
- Add domain-specific extraction profiles (legal invoices, customs invoices) via config
- Add streaming LLM response handling for faster time-to-first-field

---

### 05. ValidationAgent

**Category**: Validation | **Graph**: InvoiceProcessingGraph | **Node ID**: `validate`

#### Purpose
Run universal validation checks on extracted invoice data: mandatory field presence, GST/PAN format, duplicate detection, arithmetic consistency, date logic, and currency normalisation.

#### Responsibility
- Validate all mandatory fields are present and non-empty
- Validate GST number format (15-character alphanumeric)
- Validate PAN number format (10-character alphanumeric)
- Compute arithmetic check: sum(line_items) == subtotal + tax == total
- Check invoice date is not in the future; due date is after invoice date
- Detect duplicates using invoice hash + vendor + amount fingerprint
- Normalise currency to tenant base currency
- Record all validation results in WorkflowState

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `invoice.*` | InvoiceData | All extracted invoice fields |
| `workflow.tenant_id` | str | For duplicate detection scope |
| `extraction.field_confidences` | dict | Field-level confidence scores |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `validation.is_valid` | bool | Overall validation outcome |
| `validation.errors` | list[ValidationError] | All validation failures |
| `validation.warnings` | list[ValidationWarning] | Non-blocking issues |
| `validation.duplicate_check` | DuplicateResult | Duplicate detection outcome |
| `validation.arithmetic_check` | ArithmeticResult | Sum verification result |
| `validation.gst_check` | GSTResult | GST validation outcome |
| `validation.pan_check` | PANResult | PAN validation outcome |
| `validation.date_check` | DateResult | Date consistency outcome |
| `workflow.status` | str | VALIDATED or VALIDATION_FAILED |

#### Tools Used
| Tool | Purpose |
|---|---|
| `MandatoryFieldTool` | Check all required fields are present |
| `GSTValidationTool` | Validate GST number format and checksum |
| `PANValidationTool` | Validate PAN number format |
| `ArithmeticValidationTool` | Verify line item and total arithmetic |
| `DateValidationTool` | Check date logic and freshness |
| `CurrencyValidationTool` | Normalise and validate currency codes |
| `DuplicateDetectionTool` | Detect duplicate submissions |
| `InvoiceNumberValidationTool` | Check uniqueness and format |
| `TaxValidationTool` | Validate tax rates and computations |
| `AuditTool` | Emit VALIDATION_COMPLETE event |
| `ConfigurationTool` | Load validation rules per tenant |

#### Preconditions
- `invoice` section is fully populated by ExtractionAgent
- Tenant configuration is loaded

#### Postconditions
- `validation.is_valid` reflects aggregate pass/fail
- All validation errors are recorded with field, message, and error_code
- Duplicate detection result is committed

#### Failure Handling
| Failure | Action |
|---|---|
| Arithmetic mismatch > tolerance | Record as VALIDATION_ERROR; route to ExceptionAgent |
| Duplicate invoice detected | Halt workflow; emit DUPLICATE_DETECTED; reject invoice |
| GST format invalid | Record as error; continue other validations |
| Mandatory field missing | Record as error; flag for HumanReviewAgent if critical |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 1 |
| Retryable errors | DuplicateCheckTimeoutError (Redis unavailable) |
| Non-retryable | All ValidationErrors (deterministic results) |

#### Human Review Trigger
- Duplicate detection returns POSSIBLE_DUPLICATE (not CONFIRMED)
- Arithmetic mismatch is within `validation.soft_tolerance` range
- GST is present but fails checksum (possible OCR error)
- Multiple mandatory fields missing simultaneously

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| VALIDATION_COMPLETE | All checks run | INFO |
| DUPLICATE_DETECTED | Confirmed duplicate found | WARNING |
| ARITHMETIC_MISMATCH | Sum does not reconcile | WARNING |
| VALIDATION_FAILED | One or more hard failures | ERROR |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `validation.duration_ms` | Histogram | Total validation time |
| `validation.pass_rate` | Gauge | Fraction passing all checks |
| `validation.failure_by_rule` | Counter | Failures broken down by rule type |
| `validation.duplicate_rate` | Gauge | Duplicate detection rate |

#### Future Extensibility
- Add IBAN / SWIFT validation for international invoices
- Add vendor blacklist check via `VendorValidationTool`
- Implement configurable validation rule chains per business profile

---

### 06. BusinessProfileAgent

**Category**: Validation | **Graph**: InvoiceProcessingGraph | **Node ID**: `profile`

#### Purpose
Determine which of the 9 business profiles applies to this invoice using a combination of AI classification and rule-based logic.

#### Responsibility
- Use LLM to classify invoice content against the 9 business profiles
- Apply deterministic rules to confirm or override LLM classification
- Select the matching profile and record classification confidence
- Populate `profile.business_profile` in WorkflowState
- Flag ambiguous classifications for human review

#### Business Profiles
| Profile | Description |
|---|---|
| PO_RAW_MATERIAL | Invoice backed by PO for raw materials |
| NON_PO_RAW_MATERIAL | Raw material invoice without PO |
| PO_CAPEX | Capital expenditure with PO |
| NON_PO_CAPEX | Capital expenditure without PO |
| PO_OPEX | Operating expense with PO |
| NON_PO_OPEX | Operating expense without PO |
| LEASE_RENT | Lease or rental payments |
| EMPLOYEE_REIMBURSEMENT | Employee expense claims |
| PETTY_CASH | Petty cash or small cash expenses |

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `invoice.*` | InvoiceData | Extracted invoice fields |
| `validation.is_valid` | bool | Validation must have passed |
| `workflow.tenant_id` | str | For tenant-specific profile rules |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `profile.business_profile` | str | One of 9 profile enums |
| `profile.profile_confidence` | float | Classification confidence 0.0–1.0 |
| `profile.profile_reasoning` | str | LLM reasoning for the classification |
| `profile.classification_method` | str | AI / RULES / HYBRID |
| `profile.alternative_profiles` | list[str] | Other candidate profiles |
| `workflow.status` | str | PROFILED |

#### Tools Used
| Tool | Purpose |
|---|---|
| `BusinessProfileTool` | Apply rule-based profile detection |
| `ClassificationTool` | LLM-based profile classification |
| `PromptLoaderTool` | Load profile classification prompt |
| `ReasoningTool` | Capture classification reasoning chain |
| `ConfidenceTool` | Score profile classification confidence |
| `TokenTrackingTool` | Track LLM token usage |
| `AuditTool` | Emit PROFILE_ASSIGNED event |
| `ConfigurationTool` | Load profile rules per tenant |

#### Preconditions
- `validation.is_valid` is True (or workflow is in exception path with override)
- `invoice.line_items` is non-empty for PO-type profiles

#### Postconditions
- `profile.business_profile` is set to one of the 9 valid enum values
- Classification confidence is recorded

#### Failure Handling
| Failure | Action |
|---|---|
| LLM returns unknown profile | Fall back to rule-based classification |
| Rules and LLM disagree | Set method=HYBRID; use rules result; flag for human review if confidence < threshold |
| No profile matches | Route to HumanReviewAgent |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 2 |
| Retryable errors | LLMTimeoutError |
| Non-retryable | All deterministic rule outcomes |

#### Human Review Trigger
- `profile.profile_confidence` < `profile.min_confidence` config (e.g., 0.80)
- `profile.alternative_profiles` contains more than 2 candidates with similar scores
- Rule engine and LLM disagree on profile type

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| PROFILE_ASSIGNED | Profile determined | INFO |
| PROFILE_LOW_CONFIDENCE | Confidence below threshold | WARNING |
| PROFILE_CONFLICT | Rule vs LLM disagreement | WARNING |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `profile.duration_ms` | Histogram | Classification time |
| `profile.distribution` | Counter | Invoice counts per profile type |
| `profile.confidence_distribution` | Histogram | Confidence score spread |
| `profile.method_usage` | Counter | AI vs Rules vs Hybrid usage |

#### Future Extensibility
- Add a tenth profile (e.g., IMPORT_CUSTOMS) via config YAML without code changes
- Implement online learning to improve profile classification from human corrections
- Add industry-specific profile variants (e.g., PO_RAW_MATERIAL_PHARMACEUTICAL)

---

### 07. ProfileValidationAgent

**Category**: Validation | **Graph**: InvoiceProcessingGraph | **Node ID**: `profile_validate`

#### Purpose
Run profile-specific validation rules against the invoice, using the business profile determined by BusinessProfileAgent to select the appropriate rule set.

#### Responsibility
- Load validation rules for the assigned business profile
- Validate PO reference for PO-type profiles
- Validate GRN reference for goods-based profiles
- Validate asset register for CAPEX profiles
- Validate lease agreement number for LEASE_RENT profiles
- Validate employee ID for EMPLOYEE_REIMBURSEMENT profiles
- Record all profile-specific validation results

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `invoice.*` | InvoiceData | Extracted fields |
| `profile.business_profile` | str | Assigned profile |
| `workflow.tenant_id` | str | For rule lookup |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `profile_validation.is_valid` | bool | Profile-specific validation outcome |
| `profile_validation.errors` | list[ValidationError] | Profile rule failures |
| `profile_validation.warnings` | list[ValidationWarning] | Non-blocking profile issues |
| `profile_validation.required_references` | dict | Required reference numbers and their status |
| `workflow.status` | str | PROFILE_VALIDATED or PROFILE_VALIDATION_FAILED |

#### Tools Used
| Tool | Purpose |
|---|---|
| `ProfileValidationTool` | Load and execute profile rule set |
| `BusinessRuleTool` | Apply configurable business rules |
| `ValidationTool` | Orchestrate multi-rule validation |
| `RuleEngineTool` | Execute YAML-defined rule chains |
| `AuditTool` | Emit PROFILE_VALIDATION_COMPLETE event |
| `ConfigurationTool` | Load profile-specific rule config |

#### Preconditions
- `profile.business_profile` is assigned
- Profile rule configuration exists for tenant

#### Postconditions
- `profile_validation.is_valid` reflects aggregate pass/fail for profile rules
- All rule failures documented with rule ID, field, and message

#### Failure Handling
| Failure | Action |
|---|---|
| PO reference missing on PO-type profile | Emit PROFILE_RULE_VIOLATION; route to ExceptionAgent |
| Lease number missing on LEASE_RENT profile | Emit PROFILE_RULE_VIOLATION; route to ExceptionAgent |
| Asset register lookup fails | Retry 2 times; escalate on failure |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 2 |
| Backoff strategy | Linear |
| Retryable errors | ERPLookupTimeoutError |
| Non-retryable | All rule validation results |

#### Human Review Trigger
- Profile rules produce mixed results (some pass, some fail)
- Profile requires ERP lookup and ERP is unavailable
- Invoice matches two profiles (edge case — e.g., PO_CAPEX and PO_OPEX are ambiguous)

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| PROFILE_VALIDATION_COMPLETE | All profile rules evaluated | INFO |
| PROFILE_RULE_VIOLATION | Hard rule failure | WARNING |
| PROFILE_VALIDATION_FAILED | One or more hard failures | ERROR |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `profile_validation.duration_ms` | Histogram | Rule evaluation time |
| `profile_validation.pass_rate` | Gauge | Pass rate per profile type |
| `profile_validation.failure_by_rule` | Counter | Failures by rule identifier |

#### Future Extensibility
- Add new profile rules via YAML rule definitions — no code deployment required
- Support conditional rule chains (if rule A fails, skip rules B and C)
- Add cross-invoice profile consistency checks (e.g., vendor always uses same profile)

---

### 08. POMatchingAgent

**Category**: Matching | **Graph**: InvoiceProcessingGraph | **Node ID**: `match_po`

#### Purpose
Match the invoice PO reference against the purchase order database and compute header-level and line-level match scores.

#### Responsibility
- Retrieve the purchase order from ERP using the PO number
- Match invoice header fields (vendor, date range, currency) against PO header
- Match each invoice line item against corresponding PO lines
- Compute match scores with configurable tolerance bands
- Detect over-delivery and under-delivery conditions
- Record match result in WorkflowState

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `invoice.po_number` | str | PO reference from invoice |
| `invoice.vendor_name` | str | Vendor for cross-validation |
| `invoice.line_items` | list[LineItem] | Invoice line items |
| `invoice.total_amount` | Decimal | Invoice total |
| `profile.business_profile` | str | Determines matching rules |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `matching.po_match_result` | POMatchResult | Header and line match outcome |
| `matching.po_match_score` | float | Overall PO match score 0.0–1.0 |
| `matching.po_variances` | list[Variance] | Per-field variance details |
| `matching.po_status` | str | MATCHED / PARTIAL / NOT_FOUND / SKIPPED |
| `matching.po_data` | POData | Retrieved PO from ERP |
| `workflow.status` | str | PO_MATCHED (if matched) |

#### Tools Used
| Tool | Purpose |
|---|---|
| `PurchaseOrderTool` | Retrieve PO data from ERP |
| `POMatchingTool` | Execute PO matching algorithm |
| `ComparisonTool` | Field-level comparison with tolerance |
| `VarianceTool` | Compute and classify variances |
| `ToleranceValidationTool` | Apply configured tolerance bands |
| `VendorMatchingTool` | Validate vendor identity against PO |
| `BlanketPOTool` | Handle blanket/framework POs |
| `AuditTool` | Emit PO_MATCH_COMPLETE event |
| `ConfigurationTool` | Load tolerance thresholds per profile |

#### Preconditions
- `invoice.po_number` is non-empty
- ERP adapter is available (or mock is configured)
- Profile is PO-type (PO_RAW_MATERIAL, PO_CAPEX, PO_OPEX etc.)

#### Postconditions
- `matching.po_match_status` is set to a valid enum
- Variances are recorded if match is PARTIAL
- PO data is cached in WorkflowState for use by GRNMatchingAgent

#### Failure Handling
| Failure | Action |
|---|---|
| PO not found in ERP | Set status=NOT_FOUND; route to ExceptionAgent with queue PROCUREMENT |
| PO found but vendor mismatch | Set status=PARTIAL; flag variance; route to ExceptionAgent |
| ERP unavailable | Retry 3 times; escalate to ExceptionAgent with SYSTEM_FAILURE |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 3 |
| Backoff strategy | Exponential |
| Base delay | 2 seconds |
| Retryable errors | ERPTimeoutError, ERPConnectionError |
| Non-retryable | PONotFoundError (route, not retry) |

#### Human Review Trigger
- PO match score is between `matching.soft_match_lower` and `matching.soft_match_upper` config
- PO is expired or cancelled
- Invoice amount exceeds PO remaining balance

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| PO_MATCH_COMPLETE | Matching finished | INFO |
| PO_NOT_FOUND | PO number not in ERP | WARNING |
| PO_VARIANCE_DETECTED | Field variance above tolerance | WARNING |
| PO_ERP_FAILURE | ERP unavailable after retries | ERROR |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `po_matching.duration_ms` | Histogram | ERP lookup + matching time |
| `po_matching.match_score_distribution` | Histogram | Score distribution |
| `po_matching.not_found_rate` | Gauge | Rate of PO not found |
| `po_matching.variance_rate` | Gauge | Rate of partial matches |

#### Future Extensibility
- Add contract-backed matching for framework agreements via `ContractMatchingTool`
- Support multi-PO consolidation (single invoice references multiple POs)
- Add historical PO match pattern analysis for anomaly detection

---

### 09. GRNMatchingAgent

**Category**: Matching | **Graph**: InvoiceProcessingGraph | **Node ID**: `match_grn`

#### Purpose
Match the invoice GRN reference against the goods receipt database to verify that goods have been received before payment is authorised.

#### Responsibility
- Retrieve GRN from ERP using the GRN number
- Match invoice quantity and description against GRN received quantities
- Detect over-billing (invoiced > received) and under-receipt conditions
- Compute GRN match score with line-level detail
- Record match result and variances

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `invoice.grn_number` | str | GRN reference from invoice |
| `invoice.line_items` | list[LineItem] | Invoice line items with quantities |
| `matching.po_data` | POData | PO data for cross-reference |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `matching.grn_match_result` | GRNMatchResult | GRN match outcome |
| `matching.grn_match_score` | float | GRN match score 0.0–1.0 |
| `matching.grn_variances` | list[Variance] | Per-line variance |
| `matching.grn_status` | str | MATCHED / PARTIAL / NOT_FOUND / SKIPPED |
| `matching.grn_data` | GRNData | Retrieved GRN from ERP |

#### Tools Used
| Tool | Purpose |
|---|---|
| `GoodsReceiptTool` | Retrieve GRN from ERP |
| `GRNMatchingTool` | Execute GRN matching algorithm |
| `ComparisonTool` | Quantity and description comparison |
| `VarianceTool` | Compute quantity variances |
| `ToleranceValidationTool` | Apply quantity tolerance bands |
| `AuditTool` | Emit GRN_MATCH_COMPLETE event |
| `ConfigurationTool` | Load GRN matching tolerances |

#### Preconditions
- `invoice.grn_number` is non-empty (skipped for NON_PO profiles that don't require GRN)
- ERP adapter is available

#### Postconditions
- `matching.grn_match_status` is set
- Quantity variances are recorded if applicable

#### Failure Handling
| Failure | Action |
|---|---|
| GRN not found | Route to ExceptionAgent with queue WAREHOUSE |
| Quantity overbill detected | Flag exception; route to FINANCE queue |
| GRN goods partially received | Record PARTIAL; proceed to three-way match with variance |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 3 |
| Retryable errors | ERPTimeoutError |
| Non-retryable | GRNNotFoundError |

#### Human Review Trigger
- GRN exists but quantity mismatch > `matching.grn_quantity_soft_tolerance`
- GRN status is PARTIAL_RECEIPT
- Multiple GRNs match the same invoice line

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| GRN_MATCH_COMPLETE | GRN matching finished | INFO |
| GRN_NOT_FOUND | GRN not in ERP | WARNING |
| GRN_QUANTITY_MISMATCH | Quantity variance detected | WARNING |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `grn_matching.duration_ms` | Histogram | Matching time |
| `grn_matching.match_score_distribution` | Histogram | Score spread |
| `grn_matching.overbill_rate` | Gauge | Rate of quantity overbilling |

#### Future Extensibility
- Support multi-GRN matching (partial deliveries)
- Add RFID/barcode-based quantity verification integration
- Add delivery note (challan) cross-reference

---

### 10. ThreeWayMatchingAgent

**Category**: Matching | **Graph**: InvoiceProcessingGraph | **Node ID**: `match_3way`

#### Purpose
Perform the definitive three-way match of Invoice × PO × GRN, compute an overall match confidence score, and determine whether the invoice is approved for payment, requires exception handling, or requires human review.

#### Responsibility
- Combine PO match result and GRN match result into a three-way match assessment
- Apply business-profile-specific tolerance rules
- Compute aggregate match score
- Determine match disposition: FULL_MATCH / PARTIAL_MATCH / FAILED_MATCH
- For NON_PO profiles, evaluate against contract or blanket PO if available
- Flag invoices that exceed approval authority thresholds for escalation

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `matching.po_match_result` | POMatchResult | From POMatchingAgent |
| `matching.grn_match_result` | GRNMatchResult | From GRNMatchingAgent |
| `invoice.total_amount` | Decimal | For threshold evaluation |
| `profile.business_profile` | str | For tolerance rule selection |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `matching.three_way_result` | ThreeWayResult | Combined match outcome |
| `matching.overall_match_score` | float | Aggregate match score 0.0–1.0 |
| `matching.match_disposition` | str | FULL_MATCH / PARTIAL_MATCH / FAILED_MATCH |
| `matching.exception_required` | bool | Whether exception handling is needed |
| `matching.approval_required` | bool | Whether approval workflow is needed |
| `matching.match_summary` | str | Human-readable match summary |
| `workflow.status` | str | THREE_WAY_MATCHED |

#### Tools Used
| Tool | Purpose |
|---|---|
| `ThreeWayMatchingTool` | Combine PO and GRN results into three-way verdict |
| `VarianceTool` | Aggregate all variances |
| `ToleranceValidationTool` | Apply final tolerance decision |
| `SimilarityTool` | Text similarity for description matching |
| `ContractMatchingTool` | Contract-backed matching for framework invoices |
| `LeaseMatchingTool` | Lease agreement matching for LEASE_RENT profile |
| `AuditTool` | Emit THREE_WAY_MATCH_COMPLETE event |
| `ConfigurationTool` | Load final matching thresholds |

#### Preconditions
- Both `matching.po_match_result` and `matching.grn_match_result` are populated (or SKIPPED for NON_PO)

#### Postconditions
- `matching.match_disposition` is set to FULL_MATCH, PARTIAL_MATCH, or FAILED_MATCH
- Routing flags `matching.exception_required` and `matching.approval_required` are set

#### Failure Handling
| Failure | Action |
|---|---|
| Both PO and GRN are NOT_FOUND | Set disposition=FAILED_MATCH; route to ExceptionAgent |
| Match score < `matching.failed_match_threshold` | Route to ExceptionAgent |
| Contract lookup fails | Continue with available data; flag in warnings |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 1 |
| Retryable errors | ContractLookupTimeoutError |
| Non-retryable | All matching outcome results |

#### Human Review Trigger
- Match score is between `matching.partial_lower` and `matching.partial_upper` config thresholds
- Variance exists but total amount is below `matching.auto_approve_threshold`
- Invoice is flagged as blanket PO type (requires contract-level review)

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| THREE_WAY_MATCH_COMPLETE | Matching finished | INFO |
| THREE_WAY_MATCH_FAILED | FAILED_MATCH disposition | WARNING |
| THREE_WAY_PARTIAL_MATCH | PARTIAL_MATCH disposition | WARNING |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `three_way_matching.duration_ms` | Histogram | Total matching time |
| `three_way_matching.disposition_distribution` | Counter | Counts per disposition type |
| `three_way_matching.overall_score_distribution` | Histogram | Score spread |
| `three_way_matching.auto_approve_rate` | Gauge | Fraction auto-approved |

#### Future Extensibility
- Add four-way matching (Invoice × PO × GRN × Quality Inspection)
- Implement pattern-based anomaly detection on historical match scores
- Add ML-based tolerance auto-tuning per vendor

---

### 11. ConfidenceAgent

**Category**: Intelligence | **Graph**: InvoiceProcessingGraph | **Node ID**: `confidence`

#### Purpose
Compute a single end-to-end confidence score for the invoice by aggregating OCR quality, extraction field confidence, validation results, and matching scores — and determine whether the invoice can proceed automatically or requires human review.

#### Responsibility
- Aggregate confidence signals from all prior agents
- Weight signals according to per-profile configuration
- Compute overall_confidence score (0.0–1.0)
- Apply per-profile confidence thresholds to determine routing
- Produce a human-readable confidence summary with contributing factors
- Set the `routing.requires_human_review` flag

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `ocr.avg_confidence` | float | OCR extraction confidence |
| `extraction.field_confidences` | dict | Per-field extraction scores |
| `extraction.missing_fields` | list | Missing mandatory fields |
| `validation.is_valid` | bool | Universal validation outcome |
| `validation.errors` | list | Hard validation failures |
| `profile_validation.is_valid` | bool | Profile validation outcome |
| `matching.overall_match_score` | float | Three-way match score |
| `matching.match_disposition` | str | FULL / PARTIAL / FAILED |
| `profile.profile_confidence` | float | Business profile classification confidence |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `confidence.overall_score` | float | Aggregated confidence 0.0–1.0 |
| `confidence.component_scores` | dict[str, float] | Score per component |
| `confidence.confidence_band` | str | HIGH / MEDIUM / LOW / CRITICAL |
| `confidence.summary` | str | Human-readable confidence explanation |
| `confidence.contributing_factors` | list[Factor] | Positive and negative contributors |
| `routing.requires_human_review` | bool | Human review routing flag |
| `routing.auto_approve_eligible` | bool | Eligible for auto-approval |
| `workflow.status` | str | CONFIDENCE_SCORED |

#### Tools Used
| Tool | Purpose |
|---|---|
| `ConfidenceTool` | Aggregate and weight confidence signals |
| `ReasoningTool` | Produce explainable confidence breakdown |
| `ThresholdTool` | Apply per-profile confidence thresholds |
| `AuditTool` | Emit CONFIDENCE_SCORED event |
| `ConfigurationTool` | Load confidence weights per profile |

#### Preconditions
- All upstream agents have completed their state sections
- Confidence thresholds are configured for the business profile

#### Postconditions
- `confidence.overall_score` is set (0.0–1.0)
- `routing.requires_human_review` is set
- Confidence breakdown is recorded in state for explainability

#### Failure Handling
| Failure | Action |
|---|---|
| Confidence calculation error | Default to LOW confidence band; set `requires_human_review=True` |
| Missing upstream scores | Use available scores with penalty; log WARNING |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 1 |
| Retryable errors | ConfigurationLoadError |
| Non-retryable | All computation errors (deterministic) |

#### Human Review Trigger
- `confidence.confidence_band` is LOW or CRITICAL
- Any upstream hard failure is present in state
- `matching.match_disposition` is PARTIAL or FAILED

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| CONFIDENCE_SCORED | Scoring complete | INFO |
| CONFIDENCE_LOW | Score in LOW band | WARNING |
| CONFIDENCE_CRITICAL | Score in CRITICAL band | ERROR |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `confidence.duration_ms` | Histogram | Scoring computation time |
| `confidence.score_distribution` | Histogram | Distribution of overall scores |
| `confidence.band_distribution` | Counter | Counts per confidence band |
| `confidence.auto_approve_rate` | Gauge | Fraction eligible for auto-approval |

#### Future Extensibility
- Add model-drift detection by comparing confidence distributions over time
- Add vendor-specific confidence adjustments based on historical accuracy
- Add confidence calibration feedback loop from human review corrections

---

### 12. ExceptionAgent

**Category**: Exception | **Graph**: ExceptionGraph | **Node ID**: `exception`

#### Purpose
Classify exceptions, assign them to the correct resolution queue, set SLA deadlines, and route them to the appropriate team for resolution.

#### Responsibility
- Classify exception type and severity from state errors and flags
- Assign exception to one of five queues: AP_TEAM, FINANCE, PROCUREMENT, COMPLIANCE, WAREHOUSE
- Set SLA deadline based on exception type and tenant config
- Notify responsible team via NotificationAgent
- Track exception status through resolution

#### Exception Queues
| Queue | Owner | Typical Issues |
|---|---|---|
| AP_TEAM | Accounts Payable | Missing fields, format errors, general issues |
| FINANCE | Finance Manager | Tolerance breaches, payment terms disputes, amount mismatches |
| PROCUREMENT | Procurement Team | PO not found, PO mismatch, vendor discrepancies |
| COMPLIANCE | Compliance Officer | GST/PAN failures, duplicate invoices, policy violations |
| WAREHOUSE | Warehouse Manager | GRN not found, quantity mismatches, receipt disputes |

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `validation.errors` | list | Universal validation failures |
| `profile_validation.errors` | list | Profile-specific failures |
| `matching.match_disposition` | str | Match outcome |
| `matching.po_status` | str | PO match status |
| `matching.grn_status` | str | GRN match status |
| `confidence.confidence_band` | str | Overall confidence assessment |
| `routing.requires_human_review` | bool | Human review flag |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `exception.exception_id` | UUID | Platform exception identifier |
| `exception.exception_type` | str | Classified exception type |
| `exception.severity` | str | LOW / MEDIUM / HIGH / CRITICAL |
| `exception.assigned_queue` | str | Resolution queue |
| `exception.sla_deadline` | datetime | Resolution deadline |
| `exception.resolution_status` | str | OPEN / IN_PROGRESS / RESOLVED |
| `exception.assigned_to` | str | User or team ID |
| `workflow.status` | str | EXCEPTION_RAISED |

#### Tools Used
| Tool | Purpose |
|---|---|
| `ExceptionTool` | Classify and create exception record |
| `AssignmentTool` | Assign exception to queue and user |
| `EscalationTool` | Set escalation rules and SLA |
| `NotificationTool` | Alert responsible team |
| `TimelineTool` | Record exception timeline event |
| `AuditTool` | Emit EXCEPTION_RAISED event |
| `ConfigurationTool` | Load SLA rules per exception type |
| `WorkflowStateTool` | Update workflow status |

#### Preconditions
- At least one error, flag, or failure condition is present in WorkflowState
- Exception queue configuration exists for tenant

#### Postconditions
- Exception record is created with unique ID
- SLA deadline is set
- Assigned team/user is notified
- Exception is visible in the exception management UI

#### Failure Handling
| Failure | Action |
|---|---|
| Assignment fails | Default to AP_TEAM queue; log error |
| Notification fails | Log notification failure; continue exception creation |
| Configuration missing for exception type | Use default SLA; log WARNING |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 2 |
| Retryable errors | NotificationServiceError, QueueWriteError |
| Non-retryable | All classification results |

#### Human Review Trigger
- Exception severity is CRITICAL
- Exception involves a compliance queue (COMPLIANCE)
- Same invoice has generated exceptions 3+ times across resubmissions

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| EXCEPTION_RAISED | Exception created | WARNING |
| EXCEPTION_ASSIGNED | Team/user assigned | INFO |
| EXCEPTION_ESCALATED | SLA breach approaching | WARNING |
| EXCEPTION_RESOLVED | Exception resolved | INFO |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `exception.raised_per_type` | Counter | Exception volume by type |
| `exception.resolution_time_ms` | Histogram | Time from raised to resolved |
| `exception.sla_breach_rate` | Gauge | Fraction breaching SLA |
| `exception.queue_distribution` | Counter | Volume per queue |

#### Future Extensibility
- Add ML-based exception prediction (flag invoices likely to generate exceptions before processing)
- Add smart re-assignment based on historical resolution patterns
- Add integration with ServiceNow or Jira for enterprise ticket management

---

### 13. ApprovalAgent

**Category**: Approval | **Graph**: ApprovalGraph | **Node ID**: `approve`

#### Purpose
Determine the approval matrix for this invoice, create approval tasks for all required approvers, manage the approval workflow, and record approvals or rejections.

#### Responsibility
- Load the tenant approval matrix based on invoice amount and business profile
- Determine all required approvers and approval levels
- Create approval tasks for each level
- Enforce sequential vs parallel approval based on config
- Record each approval/rejection decision with timestamp and comments
- Escalate if approval is not received within SLA
- Update WorkflowState upon final approval or rejection

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `invoice.total_amount` | Decimal | For approval threshold lookup |
| `invoice.currency` | str | Currency for threshold comparison |
| `profile.business_profile` | str | For profile-specific matrix |
| `matching.match_disposition` | str | FULL / PARTIAL affects levels |
| `workflow.tenant_id` | str | Tenant approval matrix |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `approval.approval_id` | UUID | Approval workflow identifier |
| `approval.approval_levels` | list[ApprovalLevel] | Required approvers per level |
| `approval.current_level` | int | Active approval level index |
| `approval.decisions` | list[ApprovalDecision] | Per-approver decisions |
| `approval.final_decision` | str | APPROVED / REJECTED / PENDING |
| `approval.approved_at` | datetime | Final approval timestamp |
| `approval.rejection_reason` | str | Reason if rejected |
| `approval.approver_comments` | list[str] | Approver annotations |
| `workflow.status` | str | APPROVED / REJECTED / APPROVAL_PENDING |

#### Tools Used
| Tool | Purpose |
|---|---|
| `ApprovalTool` | Load matrix and create approval record |
| `AssignmentTool` | Assign approval tasks to users |
| `NotificationTool` | Send approval requests and reminders |
| `EscalationTool` | Escalate if approval SLA breached |
| `TimelineTool` | Record approval timeline |
| `AuditTool` | Emit APPROVAL_REQUESTED / APPROVED / REJECTED |
| `ConfigurationTool` | Load approval matrix config |
| `AuthorizationTool` | Verify approver authority level |

#### Preconditions
- `matching.match_disposition` is FULL_MATCH or PARTIAL_MATCH (partial requires explicit override)
- Approval matrix configuration exists for tenant and amount range

#### Postconditions
- All required approval levels have decisions
- `approval.final_decision` is set
- All approval decisions are audit-logged with approver identity

#### Failure Handling
| Failure | Action |
|---|---|
| Approver not found | Escalate to manager; notify AP_TEAM |
| Approval SLA breached | Auto-escalate to next authority level |
| Approval rejected | Set status=REJECTED; notify submitter; close workflow |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | N/A (approval waits for human action) |
| SLA for Level 1 | Configurable per tenant (e.g., 24 hours) |
| SLA for Level 2+ | Configurable per tenant (e.g., 48 hours) |
| Escalation path | Level N approver → Level N+1 on SLA breach |

#### Human Review Trigger
- All approval flows are inherently human-triggered via LangGraph interrupt
- Invoice amount exceeds single-approver authority limit
- Approver has a conflict-of-interest flag set in user profile

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| APPROVAL_REQUESTED | Approval task created | INFO |
| APPROVAL_REMINDER_SENT | SLA approaching | INFO |
| INVOICE_APPROVED | Final approval received | INFO |
| INVOICE_REJECTED | Approval rejected | WARNING |
| APPROVAL_ESCALATED | SLA breached | WARNING |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `approval.time_to_decision_ms` | Histogram | Duration from request to decision |
| `approval.approval_rate` | Gauge | Fraction approved vs rejected |
| `approval.escalation_rate` | Gauge | Fraction requiring escalation |
| `approval.level_distribution` | Counter | Approvals per level |

#### Future Extensibility
- Add mobile push notification for approver convenience
- Add delegated approval (approver delegates authority to deputy)
- Add bulk approval for low-risk, high-volume invoices meeting all criteria

---

### 14. ERPPostingAgent

**Category**: ERP & Payment | **Graph**: InvoiceProcessingGraph | **Node ID**: `erp_post`

#### Purpose
Post the approved invoice to the ERP system as an accounts payable journal entry and create the payment liability record.

#### Responsibility
- Build the double-entry journal from approved invoice data
- Select the correct GL accounts based on business profile and chart of accounts config
- Post journal entry to ERP via the active ERP adapter (Mock / SAP / Oracle / Dynamics / NetSuite)
- Record ERP posting reference in WorkflowState
- Handle ERP posting failures with retry and exception routing
- Guard against posting in mock mode in production environments

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `invoice.*` | InvoiceData | Complete invoice data |
| `approval.final_decision` | str | Must be APPROVED |
| `profile.business_profile` | str | For GL account selection |
| `matching.po_data` | POData | For cost centre assignment |
| `workflow.tenant_id` | str | For chart of accounts lookup |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `erp.posting_id` | str | ERP journal entry reference |
| `erp.gl_accounts` | list[GLEntry] | Debit/credit GL lines |
| `erp.cost_centre` | str | Assigned cost centre |
| `erp.posting_status` | str | POSTED / FAILED |
| `erp.posted_at` | datetime | Posting timestamp |
| `erp.erp_provider` | str | Provider used (MOCK/SAP/ORACLE etc.) |
| `workflow.status` | str | ERP_POSTED |

#### Tools Used
| Tool | Purpose |
|---|---|
| `ERPAdapterTool` | Dispatch to active ERP provider |
| `MockERPTool` | Mock ERP (development/testing — blocked in production) |
| `SAPAdapterTool` | SAP posting stub |
| `OracleAdapterTool` | Oracle Financials posting stub |
| `DynamicsAdapterTool` | Microsoft Dynamics 365 stub |
| `NetSuiteAdapterTool` | NetSuite posting stub |
| `JournalBuilderTool` | Build double-entry journal entries |
| `PostingTool` | Submit journal to ERP and handle response |
| `BudgetTool` | Check and consume budget allocation |
| `AuditTool` | Emit ERP_POSTING_COMPLETE event |
| `ConfigurationTool` | Load ERP config and GL account mapping |

#### Preconditions
- `approval.final_decision` is APPROVED
- `erp.allow_mock_in_production=false` guard passes (mock must not run in production)
- Chart of accounts is configured for tenant

#### Postconditions
- `erp.posting_id` is non-empty and references a committed ERP record
- Journal entry is balanced (debits = credits)
- Budget allocation is consumed if budget checking is enabled

#### Failure Handling
| Failure | Action |
|---|---|
| ERP unavailable | Retry with exponential backoff; queue for async retry via RetryAgent |
| Journal imbalanced | Halt; emit JOURNAL_IMBALANCE; route to FINANCE queue exception |
| Budget exceeded | Halt; emit BUDGET_EXCEEDED; route to FINANCE exception |
| Mock used in production | Halt with CRITICAL error; alert platform administrator |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 5 |
| Backoff strategy | Exponential with jitter |
| Base delay | 5 seconds |
| Max delay | 300 seconds |
| Retryable errors | ERPTimeoutError, ERPConnectionError |
| Non-retryable | JournalImbalanceError, BudgetExceededError, MockInProductionError |

#### Human Review Trigger
- Budget check fails (amount exceeds budget remaining)
- ERP returns partial success (some lines posted, some failed)
- Posting reference returned by ERP does not pass format validation

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| ERP_POSTING_COMPLETE | Journal posted successfully | INFO |
| ERP_POSTING_FAILED | Posting failed after retries | ERROR |
| BUDGET_EXCEEDED | Budget limit hit | ERROR |
| MOCK_IN_PRODUCTION_BLOCKED | Safety guard triggered | CRITICAL |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `erp_posting.duration_ms` | Histogram | ERP round-trip time |
| `erp_posting.success_rate` | Gauge | Posting success rate |
| `erp_posting.retry_count` | Histogram | Retries per successful posting |
| `erp_posting.provider_usage` | Counter | Posts per ERP provider |

#### Future Extensibility
- Activate SAPAdapterTool by implementing SAP RFC/BAPI calls behind ERPProviderInterface
- Add asynchronous posting with callback webhook for ERP providers that use async APIs
- Add reversals/credit note handling via separate posting path

---

### 15. PaymentAgent

**Category**: ERP & Payment | **Graph**: InvoiceProcessingGraph | **Node ID**: `payment`

#### Purpose
Calculate the payment schedule, apply TDS deductions, compute net payable amount, and create the payment instruction record.

#### Responsibility
- Calculate payment due date from invoice date and payment terms
- Apply TDS (Tax Deducted at Source) based on vendor category and rate config
- Compute net payable = gross amount − TDS − any advance payments
- Determine payment method (NEFT, RTGS, IMPS, Cheque) from vendor master
- Create payment instruction for treasury/banking system
- Schedule payment according to payment run calendar

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `invoice.total_amount` | Decimal | Gross invoice amount |
| `invoice.due_date` | date | Payment due date from invoice |
| `invoice.payment_terms` | str | Terms string (e.g., NET30) |
| `invoice.bank_details` | BankDetails | Beneficiary account |
| `erp.posting_id` | str | ERP reference for linkage |
| `matching.po_data` | POData | For advance payment lookup |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `payment.payment_id` | UUID | Payment instruction ID |
| `payment.due_date` | date | Calculated payment due date |
| `payment.gross_amount` | Decimal | Total before deductions |
| `payment.tds_amount` | Decimal | TDS deducted |
| `payment.net_payable` | Decimal | Final amount to pay |
| `payment.payment_method` | str | NEFT / RTGS / IMPS / CHEQUE |
| `payment.payment_status` | str | SCHEDULED / PENDING / PAID |
| `payment.scheduled_date` | date | Planned payment run date |
| `workflow.status` | str | PAYMENT_SCHEDULED |

#### Tools Used
| Tool | Purpose |
|---|---|
| `PaymentScheduleTool` | Calculate due date and schedule |
| `VendorMasterTool` | Retrieve vendor payment method and TDS category |
| `JournalBuilderTool` | Build TDS deduction journal entry |
| `PostingTool` | Post TDS deduction to ERP |
| `AuditTool` | Emit PAYMENT_SCHEDULED event |
| `ConfigurationTool` | Load TDS rates and payment calendar |
| `NotificationTool` | Notify vendor of payment schedule |

#### Preconditions
- `erp.posting_status` is POSTED
- Vendor master record exists with bank account details
- TDS rate configuration exists for vendor category

#### Postconditions
- `payment.net_payable` is computed and non-negative
- Payment instruction is created in treasury system
- Vendor is notified of scheduled payment date

#### Failure Handling
| Failure | Action |
|---|---|
| Vendor bank details missing | Route to AP_TEAM exception queue |
| TDS rate not configured | Use default rate; emit TDS_RATE_NOT_FOUND warning |
| Net payable is negative | Halt; emit NEGATIVE_PAYABLE; route to FINANCE exception |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 3 |
| Retryable errors | ERPPostingError, VendorMasterTimeoutError |
| Non-retryable | NegativePayableError |

#### Human Review Trigger
- Net payable differs from invoice total by more than `payment.max_deduction_variance`
- Vendor bank account is flagged as recently changed (anti-fraud check)
- Payment amount exceeds `payment.high_value_threshold` requiring dual authorisation

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| PAYMENT_SCHEDULED | Payment instruction created | INFO |
| TDS_DEDUCTED | TDS amount computed and posted | INFO |
| PAYMENT_FAILED | Payment run failure | ERROR |
| HIGH_VALUE_PAYMENT | Amount exceeds threshold | WARNING |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `payment.scheduling_duration_ms` | Histogram | Time to compute and schedule |
| `payment.tds_rate_distribution` | Histogram | TDS rates applied |
| `payment.payment_method_usage` | Counter | NEFT/RTGS/IMPS/Cheque counts |
| `payment.on_time_payment_rate` | Gauge | Payments made by due date |

#### Future Extensibility
- Add SWIFT/SEPA payment instruction generation for international vendors
- Add early payment discount calculation (dynamic discounting)
- Add payment run consolidation (batch multiple invoices to same vendor)

---

### 16. NotificationAgent

**Category**: Notification | **Graph**: NotificationGraph | **Node ID**: `notify`

#### Purpose
Dispatch targeted notifications to stakeholders at key workflow events, using the configured notification channels and templates for the tenant.

#### Responsibility
- Determine notification recipients based on event type and workflow state
- Load the correct notification template for the event
- Render notification content with event-specific data
- Dispatch via configured channels (Email, Teams, SMS, Webhook)
- Record notification delivery status
- Suppress duplicate notifications within cooldown windows

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `workflow.status` | str | Current workflow status (determines template) |
| `workflow.tenant_id` | str | For channel config lookup |
| `invoice.invoice_number` | str | For notification content |
| `exception.assigned_queue` | str | For exception notifications |
| `approval.approval_levels` | list | For approval request notifications |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `notifications.sent` | list[NotificationRecord] | Dispatched notifications |
| `notifications.failed` | list[NotificationRecord] | Failed dispatches |
| `notifications.last_sent_at` | datetime | Timestamp of last dispatch |

#### Tools Used
| Tool | Purpose |
|---|---|
| `NotificationTool` | Orchestrate notification dispatch |
| `PromptTemplateTool` | Render notification templates |
| `QueueTool` | Enqueue async notifications |
| `AuditTool` | Emit NOTIFICATION_SENT event |
| `ConfigurationTool` | Load channel config per tenant |
| `MaskingTool` | Mask PII in notification content |

#### Preconditions
- At least one recipient is determinable from WorkflowState
- Notification channel is configured for the event type

#### Postconditions
- All dispatched notifications have delivery status recorded
- Failed notifications are queued for retry

#### Failure Handling
| Failure | Action |
|---|---|
| Channel unavailable | Retry via fallback channel; log failure |
| Template rendering fails | Send plain-text fallback notification |
| All channels fail | Log NOTIFICATION_ALL_CHANNELS_FAILED; do not block workflow |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 3 |
| Backoff strategy | Linear |
| Base delay | 10 seconds |
| Retryable errors | ChannelUnavailableError, NetworkTimeoutError |
| Non-retryable | InvalidRecipientError |

#### Human Review Trigger
- Notification failures do not trigger human review (non-blocking agent)

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| NOTIFICATION_SENT | Notification dispatched | INFO |
| NOTIFICATION_FAILED | Dispatch failure | WARNING |
| NOTIFICATION_ALL_CHANNELS_FAILED | All channels failed | ERROR |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `notification.dispatch_duration_ms` | Histogram | Channel dispatch time |
| `notification.delivery_rate` | Gauge | Successful delivery rate |
| `notification.channel_usage` | Counter | Dispatches per channel |
| `notification.failure_rate` | Gauge | Failure rate per channel |

#### Future Extensibility
- Add Microsoft Teams channel via TeamsNotificationAdapter
- Add Slack integration via SlackNotificationAdapter
- Add notification preference management per user (opt-in/opt-out per event type)

---

### 17. RetryAgent

**Category**: Exception | **Graph**: RetryGraph | **Node ID**: `retry`

#### Purpose
Manage the retry lifecycle for failed operations — tracking attempt counts, applying backoff strategies, and escalating to ExceptionAgent when retry limits are exhausted.

#### Responsibility
- Track retry attempt count per document and per operation
- Enforce maximum retry limits from configuration
- Compute next retry time using configured backoff strategy
- Re-enqueue failed operations for processing
- Escalate to ExceptionAgent when retry budget is exhausted
- Reset retry counters on successful completion

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `workflow.document_id` | UUID | Document being retried |
| `workflow.failed_agent` | str | Agent that failed |
| `workflow.failure_reason` | str | Error code and description |
| `workflow.retry_count` | int | Current retry attempt number |
| `workflow.tenant_id` | str | For retry config lookup |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `retry.attempt_number` | int | Updated attempt count |
| `retry.next_retry_at` | datetime | Scheduled retry time |
| `retry.backoff_seconds` | int | Computed backoff duration |
| `retry.escalated` | bool | Whether escalated to exception |
| `workflow.status` | str | RETRY_SCHEDULED or RETRY_EXHAUSTED |

#### Tools Used
| Tool | Purpose |
|---|---|
| `RetryTool` | Manage retry state and backoff computation |
| `QueueTool` | Re-enqueue operation for retry |
| `ExceptionTool` | Create exception when retries exhausted |
| `NotificationTool` | Notify on retry exhaustion |
| `TimelineTool` | Record retry timeline event |
| `AuditTool` | Emit RETRY_SCHEDULED / RETRY_EXHAUSTED events |
| `ConfigurationTool` | Load retry config per operation type |

#### Preconditions
- A retryable failure has been recorded in WorkflowState
- `workflow.retry_count` is below configured maximum

#### Postconditions
- Next retry is scheduled or escalation is triggered
- Retry count is incremented in WorkflowState

#### Failure Handling
| Failure | Action |
|---|---|
| Queue write fails | Log error; attempt direct retry of queue write once |
| Max retries exhausted | Escalate to ExceptionAgent; emit RETRY_EXHAUSTED |

#### Retry Policy (RetryAgent's own retry policy)
| Parameter | Value |
|---|---|
| Max retries for queue write | 2 |
| Retryable errors | QueueWriteError |
| Non-retryable | MaxRetriesExhaustedError |

#### Human Review Trigger
- Retry count reaches `retry.human_review_threshold` (e.g., halfway to max)
- Same failure recurs across 3+ consecutive retries (systematic failure)

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| RETRY_SCHEDULED | Retry enqueued | INFO |
| RETRY_EXHAUSTED | Max attempts reached | ERROR |
| RETRY_SUCCEEDED | Retry attempt succeeded | INFO |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `retry.attempts_per_document` | Histogram | Distribution of retry counts |
| `retry.exhaustion_rate` | Gauge | Fraction reaching max retries |
| `retry.success_rate_by_attempt` | Histogram | Success rate per attempt number |

#### Future Extensibility
- Add adaptive retry with circuit-breaker pattern per downstream service
- Add retry storm prevention (rate-limit retries per ERP per time window)

---

### 18. HumanReviewAgent

**Category**: Approval | **Graph**: HumanReviewGraph | **Node ID**: `human_review`

#### Purpose
Suspend the workflow at a LangGraph interrupt checkpoint, present the invoice and flagged issues to a human reviewer, accept the reviewer's decision, and resume the workflow based on that decision.

#### Responsibility
- Identify the specific fields or decisions requiring human review
- Invoke LangGraph `interrupt()` to checkpoint state to PostgreSQL
- Expose the review task via the FastAPI endpoint `GET /api/v1/workflows/{id}/review`
- Accept reviewer decision via `POST /api/v1/workflows/{id}/resume`
- Apply the reviewer's corrections to WorkflowState
- Resume the appropriate downstream graph node
- Enforce review SLA with escalation

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `routing.requires_human_review` | bool | Must be True |
| `confidence.contributing_factors` | list | Factors that triggered review |
| `validation.errors` | list | Validation failures for display |
| `matching.*` | MatchResults | Matching details for reviewer |
| `invoice.*` | InvoiceData | Current extracted data for review |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `human_review.reviewer_id` | str | Identity of reviewer |
| `human_review.review_decision` | str | APPROVED / REJECTED / CORRECTED |
| `human_review.corrections` | dict | Field corrections made by reviewer |
| `human_review.review_comments` | str | Reviewer notes |
| `human_review.reviewed_at` | datetime | Review completion timestamp |
| `human_review.resume_node` | str | LangGraph node to resume from |
| `workflow.status` | str | UNDER_REVIEW / REVIEW_COMPLETE |

#### Tools Used
| Tool | Purpose |
|---|---|
| `ResumeTool` | Manage LangGraph interrupt/resume lifecycle |
| `WorkflowStateTool` | Checkpoint and restore state |
| `AssignmentTool` | Assign review task to appropriate reviewer |
| `NotificationTool` | Alert reviewer and send reminders |
| `EscalationTool` | Escalate if review SLA is breached |
| `TimelineTool` | Record review timeline |
| `AuditTool` | Emit HUMAN_REVIEW_REQUESTED / REVIEW_COMPLETE |
| `AuthorizationTool` | Verify reviewer has INVOICE_REVIEW permission |
| `MaskingTool` | Mask PII fields not relevant to the review |

#### Preconditions
- `routing.requires_human_review` is True
- LangGraph PostgreSQL checkpointing is configured
- A reviewer with appropriate permissions is available in the system

#### Postconditions
- `human_review.review_decision` is set
- All reviewer corrections are applied to WorkflowState before resume
- Resume node is set to the correct downstream agent

#### Failure Handling
| Failure | Action |
|---|---|
| Checkpoint write fails | Retry 3 times; if exhausted, alert platform admin |
| Review SLA breached | Escalate to senior reviewer; notify AP team |
| Resume request from unauthorised user | Reject with 403; log UNAUTHORISED_RESUME_ATTEMPT |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries (checkpoint) | 3 |
| Review SLA | Configurable per tenant (default: 48 hours) |
| Escalation SLA | Configurable per tenant (default: 72 hours) |

#### Human Review Trigger
- This agent IS the human review mechanism; it is triggered by `routing.requires_human_review = True`

#### Audit Events
| Event | Trigger | Severity |
|---|---|---|
| HUMAN_REVIEW_REQUESTED | Review task created | INFO |
| HUMAN_REVIEW_REMINDER | SLA reminder sent | INFO |
| HUMAN_REVIEW_COMPLETE | Reviewer decision received | INFO |
| HUMAN_REVIEW_ESCALATED | SLA breached | WARNING |
| UNAUTHORISED_RESUME_ATTEMPT | Unauthorised resume request | ERROR |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `human_review.time_to_review_ms` | Histogram | Duration from request to decision |
| `human_review.decision_distribution` | Counter | Approved/Rejected/Corrected counts |
| `human_review.correction_field_frequency` | Counter | Most-corrected fields |
| `human_review.sla_breach_rate` | Gauge | Fraction exceeding review SLA |

#### Future Extensibility
- Add AI-assisted review suggestions (pre-fill corrections based on similar past reviews)
- Add mobile review interface for approver on-the-go
- Build correction feedback loop to improve ExtractionAgent accuracy over time

---

### 19. AuditAgent

**Category**: Audit | **Graph**: InvoiceProcessingGraph | **Node ID**: `audit`

#### Purpose
Maintain the immutable, append-only audit trail for every invoice's complete lifecycle — from upload through payment — and produce audit reports on demand.

#### Responsibility
- Commit all audit events to the immutable `audit_logs` table
- Enforce append-only policy (no UPDATE or DELETE on audit records)
- Validate audit event completeness before commit
- Produce structured audit timelines for compliance reporting
- Support audit export for regulatory requests
- Detect and alert on suspicious event patterns (e.g., rapid successive status changes)

#### WorkflowState Input
| Field | Type | Description |
|---|---|---|
| `workflow.document_id` | UUID | Document being audited |
| `workflow.tenant_id` | str | Tenant scope |
| `workflow.status` | str | Current workflow status |
| All agent output sections | Various | Source of audit event content |

#### WorkflowState Output
| Field | Type | Description |
|---|---|---|
| `audit.last_event_id` | UUID | ID of most recent audit record |
| `audit.event_count` | int | Total events recorded for this document |
| `audit.trail_hash` | str | Running hash of audit chain (tamper detection) |
| `workflow.status` | str | AUDIT_COMPLETE (at end of workflow) |

#### Tools Used
| Tool | Purpose |
|---|---|
| `AuditTool` | Primary audit record creation and chain management |
| `LoggingTool` | Structured operational logging |
| `AnalyticsTool` | Aggregate audit metrics |
| `TimelineTool` | Build timeline view from audit events |
| `EncryptionTool` | Sign audit records for tamper evidence |
| `StorageTool` | Archive audit logs to long-term storage |
| `AuthorizationTool` | Verify audit report access is authorised |

#### Preconditions
- Database connection to `audit_logs` table is available
- `workflow.document_id` and `workflow.tenant_id` are set

#### Postconditions
- Every significant state transition has a corresponding audit record
- Audit chain hash is updated to include all new records
- Records are stored in an append-only fashion (verified by DB constraints)

#### Failure Handling
| Failure | Action |
|---|---|
| Audit DB write fails | Retry 5 times with exponential backoff; alert platform admin if exhausted |
| Chain hash mismatch detected | Emit AUDIT_CHAIN_INTEGRITY_FAILURE; halt workflow; alert security |
| Audit table lock contention | Retry with jitter; log delay |

#### Retry Policy
| Parameter | Value |
|---|---|
| Max retries | 5 |
| Backoff strategy | Exponential with jitter |
| Base delay | 1 second |
| Max delay | 30 seconds |
| Retryable errors | DBWriteError, DBConnectionError |
| Non-retryable | AuditChainIntegrityError |

#### Human Review Trigger
- Audit chain integrity check fails (possible tampering detected)
- Same document has audit events from two different tenant IDs (isolation breach)

#### Audit Events
AuditAgent creates meta-audit events (auditing the audit system):

| Event | Trigger | Severity |
|---|---|---|
| AUDIT_RECORD_COMMITTED | New record persisted | INFO |
| AUDIT_CHAIN_UPDATED | Running hash updated | INFO |
| AUDIT_CHAIN_INTEGRITY_FAILURE | Hash mismatch | CRITICAL |
| AUDIT_EXPORT_REQUESTED | Compliance export started | INFO |
| AUDIT_EXPORT_COMPLETE | Export delivered | INFO |

#### Metrics Collected
| Metric | Type | Description |
|---|---|---|
| `audit.write_duration_ms` | Histogram | DB write latency |
| `audit.events_per_document` | Histogram | Event count distribution |
| `audit.chain_verification_failures` | Counter | Integrity check failures |
| `audit.export_requests` | Counter | Compliance export volume |

#### Future Extensibility
- Add blockchain anchoring for highest-assurance audit chains (financial regulations)
- Add SIEM integration (Splunk/Sentinel) for security event forwarding
- Add automated compliance report generation (ISO 27001, SOX evidence packs)

---

## 3. Agent Interaction Matrix

The following matrix documents which agents communicate directly with which other agents through WorkflowState or through explicit graph routing decisions.

**Legend**: `W` = writes state consumed by target | `R` = routes to target | `T` = triggers target graph | `I` = interrupts for target

|  | Upload | Classify | OCR | Extract | Validate | BizProfile | ProfileVal | POMatch | GRNMatch | 3WayMatch | Confidence | Exception | Approval | ERPPost | Payment | Notify | Retry | HumanRev | Audit |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Upload** | — | W | | | | | | | | | | R | | | | T | | | W |
| **Classify** | | — | W | | | | | | | | | R | | | | | | I | W |
| **OCR** | | | — | W | | | | | | | | R | | | | | | I | W |
| **Extract** | | | | — | W | | | | | | | R | | | | | | I | W |
| **Validate** | | | | | — | W | | | | | | R | | | | | | I | W |
| **BizProfile** | | | | | | — | W | | | | | R | | | | | | I | W |
| **ProfileVal** | | | | | | | — | W | | | | R | | | | | | I | W |
| **POMatch** | | | | | | | | — | W | | | R | | | | | R | I | W |
| **GRNMatch** | | | | | | | | | — | W | | R | | | | | R | I | W |
| **3WayMatch** | | | | | | | | | | — | W | R | W | | | | | I | W |
| **Confidence** | | | | | | | | | | | — | R | W | | | | | I | W |
| **Exception** | | | | | | | | | | | | — | | | | T | T | | W |
| **Approval** | | | | | | | | | | | | R | — | W | | T | | I | W |
| **ERPPost** | | | | | | | | | | | | R | | — | W | T | R | | W |
| **Payment** | | | | | | | | | | | | R | | | — | T | R | | W |
| **Notify** | | | | | | | | | | | | | | | | — | | | W |
| **Retry** | | | | | | | | | | | | R | | | | | — | | W |
| **HumanRev** | | | W | W | W | W | W | W | | W | W | R | W | | | T | | — | W |
| **Audit** | | | | | | | | | | | | | | | | | | | — |

### Key Interaction Flows

**Critical Path (Happy Path)**
```
Upload → Classify → OCR → Extract → Validate → BizProfile →
ProfileVal → POMatch → GRNMatch → 3WayMatch → Confidence →
Approval → ERPPost → Payment → Notify → Audit
```

**Exception Path**
```
Any agent → Exception (via R routing) → Notify (via T trigger) →
[Human resolves] → Retry (via T trigger) → [Original agent]
```

**Human Review Path**
```
Any agent (interrupt flag) → HumanReview (via I) →
[Reviewer corrects state] → Resume at flagged agent
```

**Retry Path**
```
Failed agent → Retry → [Re-enter failed agent] OR
→ Exception (if retries exhausted)
```

---

## 4. Agent State Ownership Map

Each agent is the sole writer of its designated state section. No agent may write to another agent's section.

| State Section | Owner Agent | Downstream Readers |
|---|---|---|
| `raw_upload.*` | API Layer | UploadAgent |
| `document.*` | UploadAgent | All agents |
| `classification.*` | ClassificationAgent | OCRAgent, ExtractionAgent |
| `ocr.*` | OCRAgent | ExtractionAgent, ConfidenceAgent |
| `invoice.*` | ExtractionAgent | All validation and matching agents |
| `extraction.*` | ExtractionAgent | ConfidenceAgent |
| `validation.*` | ValidationAgent | BusinessProfileAgent, ConfidenceAgent |
| `profile.*` | BusinessProfileAgent | ProfileValidationAgent, POMatchingAgent |
| `profile_validation.*` | ProfileValidationAgent | ConfidenceAgent |
| `matching.*` | POMatchingAgent, GRNMatchingAgent, ThreeWayMatchingAgent | ConfidenceAgent, ERPPostingAgent |
| `confidence.*` | ConfidenceAgent | HumanReviewAgent, ApprovalAgent |
| `routing.*` | ConfidenceAgent | HumanReviewAgent, ApprovalAgent |
| `exception.*` | ExceptionAgent | NotificationAgent, RetryAgent |
| `approval.*` | ApprovalAgent | ERPPostingAgent |
| `erp.*` | ERPPostingAgent | PaymentAgent |
| `payment.*` | PaymentAgent | NotificationAgent, AuditAgent |
| `human_review.*` | HumanReviewAgent | Any agent resumed post-review |
| `retry.*` | RetryAgent | Any agent being retried |
| `notifications.*` | NotificationAgent | AuditAgent |
| `audit.*` | AuditAgent | No downstream readers (terminal) |
| `workflow.*` | Every agent (own status updates only) | LangGraph router |

---

*End of agents.md — Enterprise AI Agent Platform*

