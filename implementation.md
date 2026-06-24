# Enterprise AI Agent Platform — Implementation Blueprint

> **Document Purpose**: Step-by-step migration plan to transform the existing functional FastAPI + Celery
> AP Automation application into the LangGraph-based, configuration-driven, multi-tenant Enterprise AI
> Agent Platform described in `architecture.md`, `tools.md`, `agents.md`, and `graphs.md`.
>
> **Constraint**: The application must remain fully working after every phase. No big-bang rewrites.
> Every phase delivers a shippable, testable increment.
>
> **Source of Truth**: `ARCHITECTURE.md` (target design), `tools.md` (112 tools), `agents.md` (19 agents),
> `graphs.md` (6 LangGraph graphs)

---

## Table of Contents

1. [Current State](#1-current-state)
2. [Migration Roadmap](#2-migration-roadmap)
3. [Folder Migration](#3-folder-migration)
4. [Agent Migration](#4-agent-migration)
5. [Tool Migration](#5-tool-migration)
6. [LangGraph Migration](#6-langgraph-migration)
7. [Database & API Migration](#7-database--api-migration)
8. [Frontend Migration](#8-frontend-migration)
9. [Implementation Order](#9-implementation-order)
10. [Risks & Testing](#10-risks--testing)
11. [Definition of Done](#11-definition-of-done)

---

## 1. Current State

### 1.1 Existing Architecture Summary

The current application is a production-grade, single-tenant, task-queue–driven AP Automation system. Invoice processing is orchestrated by a Celery pipeline where each task maps to one agent. There is no shared state object — state is passed between Celery tasks via PostgreSQL rows and function arguments. Business logic is embedded directly inside agent functions.

```
API Request → FastAPI → Celery Task Queue (Redis) →
  Sequential Tasks: intake → classify → ocr → extract →
                    validate → profile → profile_validate →
                    match → exception → approve → erp_post → payment
  (Each task reads/writes PostgreSQL directly via SQLAlchemy)
```

**Orchestration**: Celery Beat + Redis (task queue)
**State management**: PostgreSQL rows read/written per task
**AI**: OpenAI GPT-4o (extraction, classification, OCR fallback)
**OCR**: PyMuPDF + PyTesseract + OpenCV
**ERP**: Mock ERP (PostgreSQL-backed)
**Storage**: Local filesystem (Docker volume)
**Deployment**: Docker Compose (8 containers)

### 1.2 Components to Keep (no changes needed)

| Component | Location | Reason to Keep |
|---|---|---|
| PostgreSQL database | `docker-compose.yml` / Azure | Storage layer — schema extended, not replaced |
| Alembic migrations | `backend/alembic/` | Add new migrations; do not remove existing ones |
| OpenAI integration | `backend/app/agents/` | Wrap into LLMTool; keep underlying API calls |
| Tesseract OCR | `backend/app/agents/ocr_agent.py` | Wrap into TesseractTool; logic preserved |
| PyMuPDF PDF parsing | `backend/app/tools/` | Wrap into PDFTool |
| YAML prompt files | `backend/app/prompts/` | Move to `core/prompts/`; format extended |
| Seed data script | `seed/seed.py` | Keep as-is for development seeding |
| Next.js frontend | `frontend/` | Incremental migration only |
| FastAPI app structure | `backend/app/api/` | Extend; do not break existing endpoints |
| SQLAlchemy models | `backend/app/models/models.py` | Keep and extend; new tables added |
| Redis | `docker-compose.yml` | Keep as Celery broker and LangGraph cache |

### 1.3 Components to Refactor (modify in place)

| Component | Location | What Changes |
|---|---|---|
| 12 Celery agents | `backend/app/agents/` | Extract business logic into Tools; agent becomes thin orchestrator |
| Celery pipeline tasks | `backend/app/tasks/` | Replaced gradually by LangGraph nodes; Celery kept as fallback during transition |
| ERP service providers | `backend/app/services/` | Wrapped behind ERPProviderInterface; existing mock becomes MockERPTool |
| Storage service | `backend/app/services/` | Wrapped behind StorageProviderInterface; becomes StorageTool + LocalStorageTool |
| FastAPI route handlers | `backend/app/api/v1/` | New routes added; existing routes preserved with backward compatibility |
| Existing agent prompts | `backend/app/prompts/` | Extended to versioned YAML format; existing prompts become v1 |

### 1.4 Components to Replace (phased replacement)

| Component | Replaced By | Phase |
|---|---|---|
| Celery sequential pipeline | LangGraph InvoiceProcessingGraph | Phase 5 |
| Direct SQLAlchemy in agents | Repository interfaces via Tools | Phase 3 |
| Hardcoded business rules in agents | RuleEngineTool + ConfigurationTool | Phase 3 |
| `MATCHING_AGENT` (monolith) | POMatchingAgent + GRNMatchingAgent + ThreeWayMatchingAgent | Phase 4 |
| Docker Compose (production) | Azure App Service / Container Apps | Phase 8 |
| Local filesystem storage | AzureBlobStorageTool | Phase 8 |

### 1.5 Components to Wrap (not rewrite)

| Existing Code | Wrapper Tool | Strategy |
|---|---|---|
| Tesseract OCR calls | `TesseractTool` | Wrap existing calls; preserve all pre-processing logic |
| PyMuPDF PDF parsing | `PDFTool` | Wrap existing `pdf_analyzer.py`; keep algorithm |
| OpenAI GPT-4o extraction | `LLMTool` | Wrap `openai.ChatCompletion.create`; add retry and token tracking |
| OpenCV image quality | `ImageEnhancementTool` | Wrap `image_quality.py`; expose through OCRConfidenceTool |
| Duplicate detection query | `DuplicateDetectionTool` | Wrap existing SQL hash check; add Redis cache layer |
| GST/PAN regex validators | `GSTValidationTool`, `PANValidationTool` | Wrap existing regex functions; add checksum validation |
| ERP mock posting logic | `MockERPTool` | Wrap `erp_provider.py` mock; enforce interface contract |
| Approval matrix logic | `ApprovalTool` | Wrap DB-driven approval matrix query; add config YAML fallback |

---

## 2. Migration Roadmap

Migration is organised into 8 phases. Each phase is independently shippable. The application processes invoices end-to-end after every phase.

```
Phase 0: Preparation & Scaffolding          (no functional change)
Phase 1: Core Infrastructure                (WorkflowState + Tool scaffolding)
Phase 2: Tool Layer                         (112 tools; agents still use Celery)
Phase 3: Agent Refactoring                  (agents become thin; tools hold logic)
Phase 4: LangGraph Integration              (graphs replace Celery pipeline)
Phase 5: API Migration                      (new endpoints; old endpoints preserved)
Phase 6: Frontend Migration                 (incremental UI enhancements)
Phase 7: Multi-tenancy & Configuration      (platform hardening)
Phase 8: Azure Deployment                   (Docker → Azure-native)
```

---

### Phase 0 — Preparation & Scaffolding

**Objective**: Set up the new folder structure, install dependencies, and establish development conventions — without changing any existing functionality.

**Tasks**

| # | Task | Description |
|---|---|---|
| P0-01 | Create `platform/` root structure | Create `core/`, `core/state/`, `core/tools/`, `core/agents/`, `core/graphs/`, `core/prompts/`, `core/config/` directories alongside existing `backend/` |
| P0-02 | Install LangGraph | Add `langgraph>=0.2`, `langgraph-checkpoint-postgres` to `requirements.txt` |
| P0-03 | Install Pydantic v2 | Upgrade `pydantic` to v2; resolve any compatibility issues in existing models |
| P0-04 | Create `WorkflowState` skeleton | Empty Pydantic model in `core/state/workflow_state.py` with only `document_id` and `tenant_id` fields |
| P0-05 | Create `BaseAgent` interface | Abstract base class in `core/agents/base_agent.py` that defines `execute(state: WorkflowState) → WorkflowState` |
| P0-06 | Create `BaseTool` interface | Abstract base class in `core/tools/base_tool.py` |
| P0-07 | Create `BaseRepository` interface | Abstract base class in `core/repositories/base_repository.py` |
| P0-08 | Create `BaseProvider` interfaces | `OCRProviderInterface`, `LLMProviderInterface`, `ERPProviderInterface`, `StorageProviderInterface` |
| P0-09 | Set up LangGraph checkpointer table | Alembic migration to create `langgraph_checkpoints` table |
| P0-10 | Add `pytest` configuration | Create `tests/` tree mirroring `core/` structure; configure `conftest.py` |
| P0-11 | Add `mypy` and `ruff` configs | Enforce type-checking and linting from day one of new code |
| P0-12 | Document coding standards | `CONTRIBUTING.md` with tool naming, DI pattern, testing contracts |

**Dependencies**
- None — no existing code is touched in this phase

**Expected Outcome**
- New folder tree exists alongside existing `backend/`
- LangGraph is installed and importable
- CI runs linting and type-checking on new code
- Existing application is completely unaffected

---

### Phase 1 — Core Infrastructure

**Objective**: Build the foundational components that every agent and tool will depend on: WorkflowState, configuration system, dependency injection container, and provider interfaces.

**Tasks**

| # | Task | Description |
|---|---|---|
| P1-01 | Build full `WorkflowState` | Implement complete `WorkflowState` Pydantic model with all 20 sections from `agents.md` |
| P1-02 | Build `ConfigurationTool` | Load tenant config from YAML; support per-tenant overrides; cache in Redis |
| P1-03 | Build `RuleEngineTool` | Execute YAML rule definitions; return pass/fail with rule ID and message |
| P1-04 | Build `FeatureFlagTool` | Per-tenant feature flags read from config; used to gate new tool behaviour |
| P1-05 | Build `EnvironmentTool` | Detect `production`/`staging`/`development`; expose `is_production()` guard |
| P1-06 | Build `SecretManagerTool` | Azure Key Vault via Managed Identity (stub returning env vars in development) |
| P1-07 | Build `LoggingTool` | Structured JSON logging; never logs PII — only hashes and document IDs |
| P1-08 | Build DI container | `DependencyContainer` that resolves tool and repository instances per request |
| P1-09 | Migrate YAML prompts | Copy existing `backend/app/prompts/*.yaml` to `core/prompts/`; add `version: "1.0"` field |
| P1-10 | Build `PromptRegistryTool` | Load versioned prompts from `core/prompts/`; support tenant overrides |
| P1-11 | Build `AuditTool` skeleton | Write to `audit_logs` table; enforce append-only; used by all agents from Phase 3 |
| P1-12 | Build `AuthorizationTool` | Check RBAC permissions; wraps existing permission checks from FastAPI middleware |
| P1-13 | Create tenant config YAML | `core/config/tenants/default.yaml` with all thresholds, tolerances, approval matrix |

**Dependencies**
- Phase 0 complete (folder structure, base classes, checkpointer table)

**Expected Outcome**
- `WorkflowState` is importable and passes Pydantic validation
- Configuration loads from YAML and Redis cache
- All new infrastructure tools have 100% unit test coverage
- Existing Celery pipeline is unaffected

---

### Phase 2 — Tool Layer

**Objective**: Implement all 112 tools, wrapping existing logic from agents and services. Agents continue to run on Celery during this phase — tools are built but not yet wired to agents.

**Tasks**

| # | Task | Category | Wraps Existing Code? |
|---|---|---|---|
| P2-01 | Document Tools (12) | Document | `pdf_analyzer.py`, file upload logic |
| P2-02 | OCR Tools (14) | OCR | `tesseract` calls, `image_quality.py`, OpenCV |
| P2-03 | AI/LLM Tools (11) | AI/LLM | `openai.ChatCompletion` calls in extraction agent |
| P2-04 | Validation Tools (14) | Validation | GST/PAN regex, arithmetic check, duplicate query |
| P2-05 | Matching Tools (10) | Matching | Matching logic from `MATCHING_AGENT` |
| P2-06 | ERP Tools (14) | ERP | `erp_provider.py`, mock ERP PostgreSQL logic |
| P2-07 | Workflow Tools (13) | Workflow | Celery retry logic, approval matrix query, exception queue logic |
| P2-08 | Storage Tools (6) | Storage | Local filesystem storage service |
| P2-09 | Prompt Tools (6) | Prompt | YAML prompt loader; extend with versioning |
| P2-10 | Configuration Tools (6) | Config | Built in Phase 1; complete remaining 5 tools |
| P2-11 | Security Tools (6) | Security | Authentication middleware, PII masking |

**Implementation pattern for each tool category**:
1. Extract the existing algorithm from the agent/service function
2. Wrap it in the `BaseTool` interface with typed `Input` and `Output` models
3. Write unit tests against the tool interface (not the underlying implementation)
4. Verify the extracted algorithm produces identical output to the original code

**Dependencies**
- Phase 1 complete (DI container, base interfaces, ConfigurationTool, AuditTool)

**Expected Outcome**
- All 112 tools implemented and independently unit-tested
- Each tool has a typed `Input` / `Output` Pydantic model
- Existing Celery agents continue to run unchanged
- No regression in existing invoice processing

---

### Phase 3 — Agent Refactoring

**Objective**: Refactor all 12 existing agents (and add 7 new ones) to become thin orchestrators that call tools and update WorkflowState. Remove all business logic from agent functions.

**Tasks**

| # | Task | Description |
|---|---|---|
| P3-01 | Refactor `INTAKE_AGENT` → `UploadAgent` | Replace inline code with calls to FileValidationTool, VirusScanTool, StorageTool, AuditTool |
| P3-02 | Refactor `CLASSIFICATION_AGENT` → `ClassificationAgent` | Replace with calls to PDFTool, OCRConfidenceTool, LanguageDetectionTool |
| P3-03 | Refactor `OCR_AGENT` → `OCRAgent` | Replace with TesseractTool, DeskewTool, ImageEnhancementTool, TextCleaningTool |
| P3-04 | Refactor `EXTRACTION_AGENT` → `ExtractionAgent` | Replace with LLMTool, ExtractionTool, NormalizationTool, ConfidenceTool |
| P3-05 | Refactor `UNIVERSAL_VALIDATION_AGENT` → `ValidationAgent` | Replace with all 14 validation tools |
| P3-06 | Refactor `BUSINESS_PROFILE_AGENT` → `BusinessProfileAgent` | Replace with BusinessProfileTool, ClassificationTool |
| P3-07 | Refactor `PROFILE_VALIDATION_AGENT` → `ProfileValidationAgent` | Replace with ProfileValidationTool, RuleEngineTool |
| P3-08 | Split `MATCHING_AGENT` → `POMatchingAgent` | Extract PO matching sub-logic into POMatchingTool |
| P3-09 | Split `MATCHING_AGENT` → `GRNMatchingAgent` | Extract GRN matching sub-logic into GRNMatchingTool |
| P3-10 | Split `MATCHING_AGENT` → `ThreeWayMatchingAgent` | Extract three-way verdict logic into ThreeWayMatchingTool |
| P3-11 | Add new `ConfidenceAgent` | New — no existing equivalent; calls ConfidenceTool, ThresholdTool |
| P3-12 | Refactor `EXCEPTION_AGENT` → `ExceptionAgent` | Replace with ExceptionTool, AssignmentTool, EscalationTool |
| P3-13 | Refactor `APPROVAL_AGENT` → `ApprovalAgent` | Replace with ApprovalTool, AssignmentTool, NotificationTool |
| P3-14 | Refactor `ERP_POSTING_AGENT` → `ERPPostingAgent` | Replace with ERPAdapterTool, JournalBuilderTool, PostingTool |
| P3-15 | Refactor `PAYMENT_AGENT` → `PaymentAgent` | Replace with PaymentScheduleTool, VendorMasterTool |
| P3-16 | Add new `NotificationAgent` | New — extract notification calls from existing agents |
| P3-17 | Add new `RetryAgent` | New — extract retry logic from existing Celery retry decorators |
| P3-18 | Add new `HumanReviewAgent` | New — wraps LangGraph interrupt; no existing equivalent |
| P3-19 | Add new `AuditAgent` | New — promote AuditTool usage to dedicated agent |

**Celery shim strategy during Phase 3**:
- Each refactored agent is wrapped in a Celery task shim: the shim creates a minimal WorkflowState, calls the new agent's `execute()` method, and writes results back to PostgreSQL
- This keeps the Celery pipeline working while the agent internals are fully refactored
- The shim is removed in Phase 4 when LangGraph takes over orchestration

**Dependencies**
- Phase 2 complete (all 112 tools available)

**Expected Outcome**
- All 19 agents are thin orchestrators calling tools only
- Zero business logic remains inside agent functions
- All agents implement `BaseAgent.execute(state: WorkflowState) → WorkflowState`
- Celery shims keep the existing pipeline running
- Full regression test suite passes

---

### Phase 4 — LangGraph Integration

**Objective**: Replace the Celery sequential pipeline with the 6 LangGraph graphs. LangGraph becomes the primary orchestration engine. Celery is demoted to handling async side tasks (notifications, exports) only.

**Tasks**

| # | Task | Description |
|---|---|---|
| P4-01 | Configure PostgresSaver | Wire `langgraph-checkpoint-postgres` to existing PostgreSQL instance |
| P4-02 | Build `InvoiceProcessingGraph` | Implement all 14 nodes and 10 conditional edge functions |
| P4-03 | Build `ExceptionGraph` | Implement 8 nodes; wire to ExceptionAgent |
| P4-04 | Build `HumanReviewGraph` | Implement 8 nodes; wire LangGraph `interrupt()` |
| P4-05 | Build `ApprovalGraph` | Implement 9 nodes; wire LangGraph `interrupt()` for each approval level |
| P4-06 | Build `RetryGraph` | Implement 7 nodes; 4 backoff strategy implementations |
| P4-07 | Build `NotificationGraph` | Implement 8 nodes; wire to async notification queue |
| P4-08 | Build graph router | `GraphRouter` class that selects which graph to invoke based on document type and tenant config |
| P4-09 | Build resume endpoint | `POST /api/v1/workflows/{id}/resume` calling `graph.invoke(Command(resume=...))` |
| P4-10 | Build review endpoint | `GET /api/v1/workflows/{id}/review` returning review pack from checkpointed state |
| P4-11 | Build approval endpoint | `POST /api/v1/workflows/{id}/approve` for approval decisions |
| P4-12 | Migration switch flag | Feature flag `feature.use_langgraph_pipeline` — when enabled, LangGraph runs; when disabled, Celery runs |
| P4-13 | Parallel run validation | Run both pipelines on 10% of invoices; compare outputs for correctness |
| P4-14 | Celery demotion | Redirect notification and export tasks to NotificationGraph; remove invoice pipeline tasks |
| P4-15 | Smoke test suite | End-to-end test for each of the 9 business profiles through the full LangGraph pipeline |

**Dependencies**
- Phase 3 complete (all 19 agents refactored)
- PostgresSaver Alembic migration applied

**Expected Outcome**
- LangGraph processes invoices end-to-end through all 6 graphs
- Human review and approval workflows use LangGraph interrupt/resume
- Feature flag allows instant rollback to Celery pipeline
- Zero regression — all existing test cases pass through LangGraph

---

### Phase 5 — API Migration

**Objective**: Add new API endpoints for LangGraph-specific capabilities (workflow state, interrupt resume, confidence details, agent execution trace) while preserving all existing endpoints.

**Tasks**

| # | Task | Description |
|---|---|---|
| P5-01 | Add `GET /api/v1/workflows/{id}/state` | Return full WorkflowState JSON for a document |
| P5-02 | Add `GET /api/v1/workflows/{id}/timeline` | Return ordered agent execution timeline |
| P5-03 | Add `GET /api/v1/workflows/{id}/confidence` | Return confidence breakdown with ExplainableDecision |
| P5-04 | Add `GET /api/v1/workflows/{id}/agent-trace` | Return per-agent execution log with inputs, outputs, duration |
| P5-05 | Add `POST /api/v1/workflows/{id}/resume` | LangGraph resume (built in Phase 4; formalised here) |
| P5-06 | Add `GET /api/v1/workflows/{id}/review` | Human review pack (built in Phase 4; formalised here) |
| P5-07 | Add `POST /api/v1/workflows/{id}/approve` | Approval decision (built in Phase 4; formalised here) |
| P5-08 | Add `GET /api/v1/prompts` | List all prompt versions per tenant |
| P5-09 | Add `POST /api/v1/prompts/{name}/activate` | Activate a prompt version |
| P5-10 | Add `GET /api/v1/config` | Return tenant configuration (non-secret fields only) |
| P5-11 | Add `PATCH /api/v1/config` | Update tenant configuration values |
| P5-12 | Add tenant header middleware | `X-Tenant-ID` header required on all new endpoints; existing endpoints use `default` tenant |
| P5-13 | OpenAPI schema update | Regenerate and publish updated OpenAPI spec |
| P5-14 | Backward compatibility validation | Verify all existing frontend API calls still work against original endpoints |

**Dependencies**
- Phase 4 complete (LangGraph graphs live)

**Expected Outcome**
- All new endpoints documented in OpenAPI
- All existing endpoints return identical responses to pre-migration
- Frontend can access workflow state, confidence, and timeline without breaking

---

### Phase 6 — Frontend Migration

**Objective**: Incrementally enhance the Next.js frontend to surface new platform capabilities (confidence scores, agent execution trace, human review UI, workflow timeline) without breaking any existing pages.

*(Detailed breakdown in Section 8)*

**Dependencies**
- Phase 5 complete (new API endpoints available)

---

### Phase 7 — Multi-tenancy & Platform Hardening

**Objective**: Activate multi-tenancy, harden security, complete audit trail, and make the platform ready for onboarding multiple clients.

**Tasks**

| # | Task | Description |
|---|---|---|
| P7-01 | Tenant registry | Create `tenants` table; `TenantRegistrationTool`; admin API |
| P7-02 | Tenant isolation middleware | Enforce `tenant_id` scoping on all DB queries |
| P7-03 | Per-tenant config YAML | One YAML per tenant in `core/config/tenants/`; hot-reload support |
| P7-04 | Token budget enforcement | Wire `TokenTrackingTool` Redis counters; enforce per-tenant LLM budgets |
| P7-05 | Audit chain integrity | Implement running hash in `AuditTool`; add `AUDIT_CHAIN_UPDATED` events |
| P7-06 | PII masking | Wire `PIITool` and `MaskingTool` to all logging and notification paths |
| P7-07 | Secret rotation support | All secrets via `SecretManagerTool`; no hardcoded credentials |
| P7-08 | Rate limiting | Per-tenant API rate limits via Redis counters |
| P7-09 | RBAC hardening | Verify all endpoints check `AuthorizationTool` permissions |
| P7-10 | Sandbox Jinja2 | Replace any regular `jinja2.Environment` with `SandboxedEnvironment` in PromptTemplateTool |

**Dependencies**
- Phase 5 complete

---

### Phase 8 — Azure Deployment

**Objective**: Replace Docker Compose with Azure-native services. The Docker Compose setup remains available for local development.

| Docker Service | Azure Equivalent | Migration Task |
|---|---|---|
| `backend` container | Azure App Service (FastAPI) | Deploy containerised FastAPI to App Service |
| `frontend` container | Azure Static Web Apps (Next.js) | Deploy Next.js build to Static Web Apps |
| `celery_worker` container | Azure Container Apps (Celery) | Deploy worker to Container Apps with autoscale |
| `celery_beat` container | Azure Container Apps (Beat) | Deploy Beat to Container Apps |
| `postgres` container | Azure PostgreSQL Flexible Server | Migrate data; update `DATABASE_URL` |
| `redis` container | Azure Cache for Redis | Update `REDIS_URL`; no code changes needed |
| `nginx` container | Azure Front Door / App Gateway | Configure routing rules |
| File storage (volume) | Azure Blob Storage | Activate `AzureBlobStorageTool`; disable `LocalStorageTool` in production |
| Secret env vars | Azure Key Vault + Managed Identity | Wire `SecretManagerTool` to Key Vault |

---

## 3. Folder Migration

### 3.1 Complete Folder Mapping

| Current Path | Action | New Path | Notes |
|---|---|---|---|
| `backend/app/agents/` | Split + Move | `core/agents/` | 12 agents refactored into 19; old files removed after Phase 3 |
| `backend/app/agents/intake_agent.py` | Rename + Refactor | `core/agents/upload_agent.py` | Logic extracted to tools |
| `backend/app/agents/classification_agent.py` | Rename + Refactor | `core/agents/classification_agent.py` | Logic extracted to tools |
| `backend/app/agents/ocr_agent.py` | Rename + Refactor | `core/agents/ocr_agent.py` | Logic extracted to OCR tools |
| `backend/app/agents/extraction_agent.py` | Rename + Refactor | `core/agents/extraction_agent.py` | Logic extracted to AI/LLM tools |
| `backend/app/agents/validation_agent.py` | Rename + Refactor | `core/agents/validation_agent.py` | Logic extracted to validation tools |
| `backend/app/agents/business_profile_agent.py` | Rename + Refactor | `core/agents/business_profile_agent.py` | Logic extracted |
| `backend/app/agents/profile_validation_agent.py` | Rename + Refactor | `core/agents/profile_validation_agent.py` | Logic extracted |
| `backend/app/agents/matching_agent.py` | Split | `core/agents/po_matching_agent.py` | Split into 3 agents |
| `backend/app/agents/matching_agent.py` | Split | `core/agents/grn_matching_agent.py` | |
| `backend/app/agents/matching_agent.py` | Split | `core/agents/three_way_matching_agent.py` | |
| `backend/app/agents/exception_agent.py` | Rename + Refactor | `core/agents/exception_agent.py` | |
| `backend/app/agents/approval_agent.py` | Rename + Refactor | `core/agents/approval_agent.py` | |
| `backend/app/agents/erp_posting_agent.py` | Rename + Refactor | `core/agents/erp_posting_agent.py` | |
| `backend/app/agents/payment_agent.py` | Rename + Refactor | `core/agents/payment_agent.py` | |
| *(new)* | Create | `core/agents/confidence_agent.py` | New agent |
| *(new)* | Create | `core/agents/notification_agent.py` | New agent |
| *(new)* | Create | `core/agents/retry_agent.py` | New agent |
| *(new)* | Create | `core/agents/human_review_agent.py` | New agent |
| *(new)* | Create | `core/agents/audit_agent.py` | New agent |
| `backend/app/tools/` | Split + Move | `core/tools/` | Existing 3 tools become 112 tools |
| `backend/app/tools/pdf_analyzer.py` | Wrap | `core/tools/document/pdf_tool.py` | Existing logic preserved inside |
| `backend/app/tools/image_quality.py` | Wrap | `core/tools/ocr/image_enhancement_tool.py` | |
| `backend/app/tools/audit_tool.py` | Refactor | `core/tools/workflow/audit_tool.py` | Upgraded with chain hashing |
| `backend/app/services/` | Split + Wrap | `core/tools/erp/`, `core/tools/storage/` | Each service becomes one or more tools |
| `backend/app/services/erp_provider.py` | Wrap | `core/tools/erp/mock_erp_tool.py` | Behind ERPProviderInterface |
| `backend/app/services/storage_service.py` | Wrap | `core/tools/storage/local_storage_tool.py` | Behind StorageProviderInterface |
| `backend/app/services/ingestion_service.py` | Wrap | `core/tools/document/file_tool.py` | File ingestion logic |
| `backend/app/prompts/` | Move + Extend | `core/prompts/` | Add `version:`, `tenant_id:` fields to each YAML |
| `backend/app/models/models.py` | Keep + Extend | `backend/app/models/models.py` | New tables added via Alembic migrations |
| `backend/app/api/v1/` | Keep + Extend | `backend/app/api/v1/` | New routes added; existing routes unchanged |
| `backend/app/tasks/` | Demote | `backend/app/tasks/` | Invoice pipeline tasks replaced by LangGraph; notification tasks kept |
| `backend/alembic/` | Keep + Extend | `backend/alembic/` | New migrations only; existing never modified |
| `frontend/src/` | Keep + Extend | `frontend/src/` | New pages and components added alongside existing |
| `seed/seed.py` | Keep | `seed/seed.py` | No changes |
| `docker-compose.yml` | Keep (dev) | `docker-compose.yml` | Production migrated to Azure in Phase 8 |
| *(new)* | Create | `core/state/workflow_state.py` | Central WorkflowState model |
| *(new)* | Create | `core/graphs/` | 6 LangGraph graph definitions |
| *(new)* | Create | `core/config/` | Tenant YAML configurations |
| *(new)* | Create | `core/repositories/` | Repository interfaces |
| *(new)* | Create | `infra/` | Azure infrastructure-as-code (Bicep/Terraform) |
| *(new)* | Create | `tests/` | Comprehensive test suite |

### 3.2 Target Folder Structure

```
invoice-p2p/
├── core/                              # Reusable platform layer (80% reusable)
│   ├── state/
│   │   └── workflow_state.py          # Single WorkflowState Pydantic model
│   ├── agents/                        # 19 thin orchestrator agents
│   │   ├── base_agent.py
│   │   ├── upload_agent.py
│   │   ├── classification_agent.py
│   │   ├── ocr_agent.py
│   │   ├── extraction_agent.py
│   │   ├── validation_agent.py
│   │   ├── business_profile_agent.py
│   │   ├── profile_validation_agent.py
│   │   ├── po_matching_agent.py
│   │   ├── grn_matching_agent.py
│   │   ├── three_way_matching_agent.py
│   │   ├── confidence_agent.py
│   │   ├── exception_agent.py
│   │   ├── approval_agent.py
│   │   ├── erp_posting_agent.py
│   │   ├── payment_agent.py
│   │   ├── notification_agent.py
│   │   ├── retry_agent.py
│   │   ├── human_review_agent.py
│   │   └── audit_agent.py
│   ├── tools/                         # 112 tools across 11 categories
│   │   ├── base_tool.py
│   │   ├── document/                  # 12 document tools
│   │   ├── ocr/                       # 14 OCR tools
│   │   ├── ai_llm/                    # 11 AI/LLM tools
│   │   ├── validation/                # 14 validation tools
│   │   ├── matching/                  # 10 matching tools
│   │   ├── erp/                       # 14 ERP tools
│   │   ├── workflow/                  # 13 workflow tools
│   │   ├── storage/                   # 6 storage tools
│   │   ├── prompt/                    # 6 prompt tools
│   │   ├── config/                    # 6 configuration tools
│   │   └── security/                  # 6 security tools
│   ├── graphs/                        # 6 LangGraph graph definitions
│   │   ├── invoice_processing_graph.py
│   │   ├── exception_graph.py
│   │   ├── human_review_graph.py
│   │   ├── approval_graph.py
│   │   ├── retry_graph.py
│   │   └── notification_graph.py
│   ├── prompts/                       # Versioned YAML prompts
│   │   ├── v1/                        # Migrated from backend/app/prompts/
│   │   └── tenants/                   # Tenant-specific overrides
│   ├── repositories/                  # Repository interfaces + implementations
│   │   ├── base_repository.py
│   │   └── invoice_repository.py
│   └── config/                        # Tenant configuration
│       ├── default.yaml
│       └── tenants/
├── backend/                           # FastAPI application (tenant-specific: 20%)
│   ├── app/
│   │   ├── api/v1/                    # API routes (extended, not replaced)
│   │   ├── models/                    # SQLAlchemy models (extended)
│   │   ├── tasks/                     # Celery (notifications + exports only)
│   │   └── middleware/                # Auth, tenant, rate limiting
│   └── alembic/                       # All migrations (never modified retroactively)
├── frontend/                          # Next.js (extended incrementally)
│   └── src/
│       ├── pages/                     # Existing + new pages
│       └── components/                # Existing + new components
├── infra/                             # Azure IaC
│   └── bicep/
├── tests/
│   ├── unit/                          # Per-tool unit tests
│   ├── integration/                   # Agent + tool integration tests
│   └── e2e/                           # Full pipeline end-to-end tests
├── seed/
└── docker-compose.yml                 # Local development only
```

---

## 4. Agent Migration

### 4.1 INTAKE_AGENT → UploadAgent

| Field | Current | New |
|---|---|---|
| **Current responsibility** | Validate file, store to disk, create DB row, call Celery classify task | Validate file, virus scan, store via StorageTool, create WorkflowState record |
| **New responsibility** | Orchestrate file intake tools; write to WorkflowState `document.*` section |  |
| **Logic moved to Tools** | File type/size validation → `FileValidationTool`; storage → `StorageTool`; hash → `HashTool`; page count → `PageTool`; metadata → `MetadataTool` |  |
| **Remaining orchestration** | Call tools in sequence; handle virus quarantine routing; emit audit event |  |
| **Dependencies** | FileValidationTool, VirusScanTool, StorageTool, HashTool, MetadataTool, PageTool, AuditTool, AuthorizationTool |  |
| **Migration priority** | High (gateway agent — all invoices pass through here) |  |

### 4.2 CLASSIFICATION_AGENT → ClassificationAgent

| Field | Current | New |
|---|---|---|
| **Current responsibility** | Detect DIGITAL/SCANNED/HANDWRITTEN; assess image quality; choose OCR path | Same plus: explicit OCR strategy enum; language detection; provider selection |
| **Logic moved to Tools** | PDF text layer detection → `PDFTool`; image quality score → `OCRConfidenceTool`; skew measurement → `DeskewTool`; language detection → `LanguageDetectionTool`; provider selection → `ProviderSelectionTool` |  |
| **Remaining orchestration** | Call tools; map class to ocr_strategy enum; write to `classification.*` |  |
| **Dependencies** | StorageTool, PDFTool, ImageTool, OCRConfidenceTool, DeskewTool, LanguageDetectionTool, ProviderSelectionTool |  |
| **Migration priority** | High |  |

### 4.3 OCR_AGENT → OCRAgent

| Field | Current | New |
|---|---|---|
| **Current responsibility** | Run Tesseract on scanned pages; call GPT Vision for handwritten; store raw text | Same plus: explicit pre-processing pipeline; per-page confidence tracking; token budget enforcement |
| **Logic moved to Tools** | Deskew → `DeskewTool`; image enhancement → `ImageEnhancementTool`; page rotation → `PageRotationTool`; Tesseract → `TesseractTool`; GPT Vision → `LLMTool`; text cleaning → `TextCleaningTool`; confidence → `OCRConfidenceTool`; token tracking → `TokenTrackingTool` |  |
| **Remaining orchestration** | Select enhancement pipeline from classification result; call OCR provider; write to `ocr.*` |  |
| **Dependencies** | DeskewTool, ImageEnhancementTool, PageRotationTool, TesseractTool, LLMTool, OCRConfidenceTool, TextCleaningTool, TokenTrackingTool |  |
| **Migration priority** | High |  |

### 4.4 EXTRACTION_AGENT → ExtractionAgent

| Field | Current | New |
|---|---|---|
| **Current responsibility** | Call GPT-4o with raw OCR text; parse JSON response; map to invoice fields; store to DB | Same plus: per-field confidence, normalisation, missing field detection, prompt versioning, reasoning capture |
| **Logic moved to Tools** | LLM call → `LLMTool`; JSON parsing → `ExtractionTool`; normalisation → `NormalizationTool`; field confidence → `ConfidenceTool`; token budget → `TokenTrackingTool`; reasoning → `ReasoningTool`; prompt load → `PromptLoaderTool` |  |
| **Remaining orchestration** | Load prompt; call LLMTool; parse; normalise; compute confidence; write to `invoice.*` and `extraction.*` |  |
| **Dependencies** | PromptLoaderTool, LLMTool, ExtractionTool, NormalizationTool, ConfidenceTool, TokenTrackingTool, ReasoningTool |  |
| **Migration priority** | Critical (most complex logic; highest risk) |  |

### 4.5 UNIVERSAL_VALIDATION_AGENT → ValidationAgent

| Field | Current | New |
|---|---|---|
| **Current responsibility** | Run GST/PAN regex; arithmetic check; duplicate query; store validation results | Same plus: configurable rule execution order; soft vs hard failure distinction; per-rule error codes |
| **Logic moved to Tools** | Every validation rule extracted to its own tool: `MandatoryFieldTool`, `GSTValidationTool`, `PANValidationTool`, `ArithmeticValidationTool`, `DateValidationTool`, `CurrencyValidationTool`, `DuplicateDetectionTool`, `InvoiceNumberValidationTool`, `TaxValidationTool` |  |
| **Remaining orchestration** | Run tool chain in configured order; aggregate results; classify as hard/soft failure; write to `validation.*` |  |
| **Dependencies** | All 14 validation tools; ConfigurationTool; AuditTool |  |
| **Migration priority** | High |  |

### 4.6 BUSINESS_PROFILE_AGENT → BusinessProfileAgent

| Field | Current | New |
|---|---|---|
| **Current responsibility** | Rule-based + GPT classification for 9 profiles; store result | Same plus: explicit hybrid method tracking; confidence score; alternative profiles; reasoning capture |
| **Logic moved to Tools** | Rule-based detection → `BusinessProfileTool`; LLM classification → `ClassificationTool`; confidence → `ConfidenceTool`; reasoning → `ReasoningTool` |  |
| **Remaining orchestration** | Run both tools; resolve conflict; write to `profile.*` |  |
| **Dependencies** | BusinessProfileTool, ClassificationTool, PromptLoaderTool, ConfidenceTool, ReasoningTool, TokenTrackingTool |  |
| **Migration priority** | Medium |  |

### 4.7 PROFILE_VALIDATION_AGENT → ProfileValidationAgent

| Field | Current | New |
|---|---|---|
| **Current responsibility** | Run DB-driven rules per profile | Same plus: YAML rule chains; ERP-backed reference validation |
| **Logic moved to Tools** | DB rule lookup → `ProfileValidationTool`; rule execution → `RuleEngineTool`; business rules → `BusinessRuleTool` |  |
| **Remaining orchestration** | Load profile rule set; execute; write to `profile_validation.*` |  |
| **Dependencies** | ProfileValidationTool, BusinessRuleTool, RuleEngineTool, ConfigurationTool |  |
| **Migration priority** | Medium |  |

### 4.8 MATCHING_AGENT → POMatchingAgent + GRNMatchingAgent + ThreeWayMatchingAgent

The existing `MATCHING_AGENT` is a monolith containing PO fetch, GRN fetch, and three-way verdict logic in a single function. It is split into 3 separate agents.

**POMatchingAgent**

| Field | Value |
|---|---|
| **Current responsibility** | Fraction of MATCHING_AGENT: fetch PO, compare header and lines, compute score |
| **Logic moved to Tools** | ERP fetch → `PurchaseOrderTool`; matching algorithm → `POMatchingTool`; variance → `VarianceTool`; tolerance → `ToleranceValidationTool`; vendor check → `VendorMatchingTool` |
| **Remaining orchestration** | Fetch PO; run match; record variance; write to `matching.po_*` |
| **Migration priority** | High (most common exception source) |

**GRNMatchingAgent**

| Field | Value |
|---|---|
| **Current responsibility** | Fraction of MATCHING_AGENT: fetch GRN, compare quantities |
| **Logic moved to Tools** | ERP fetch → `GoodsReceiptTool`; matching → `GRNMatchingTool`; quantity variance → `VarianceTool` |
| **Remaining orchestration** | Fetch GRN; run match; record quantity variance; write to `matching.grn_*` |
| **Migration priority** | High |

**ThreeWayMatchingAgent**

| Field | Value |
|---|---|
| **Current responsibility** | Fraction of MATCHING_AGENT: combine PO + GRN result into verdict |
| **Logic moved to Tools** | Combination logic → `ThreeWayMatchingTool`; contract matching → `ContractMatchingTool`; lease matching → `LeaseMatchingTool` |
| **Remaining orchestration** | Combine results; apply tolerance; set disposition; write to `matching.three_way_*` |
| **Migration priority** | High |

### 4.9 New Agent — ConfidenceAgent

| Field | Value |
|---|---|
| **Current responsibility** | Not present in current system |
| **New responsibility** | Aggregate all confidence signals; compute overall score; set routing flags |
| **Logic moved to Tools** | Aggregation → `ConfidenceTool`; threshold → `ThresholdTool`; reasoning → `ReasoningTool` |
| **Remaining orchestration** | Collect signals from all prior state sections; call ConfidenceTool; write to `confidence.*` and `routing.*` |
| **Migration priority** | Medium (new capability; no regression risk) |

### 4.10 EXCEPTION_AGENT → ExceptionAgent

| Field | Current | New |
|---|---|---|
| **Current responsibility** | Classify exception type; assign to queue; set SLA; send notification inline | Same plus: dedicated ExceptionGraph orchestration; escalation policy; timeline tracking |
| **Logic moved to Tools** | Exception classification → `ExceptionTool`; queue assignment → `AssignmentTool`; SLA → `EscalationTool`; notification → `NotificationTool`; timeline → `TimelineTool` |  |
| **Remaining orchestration** | Read failure signals from state; call classification tools; write to `exception.*` |  |
| **Migration priority** | High |  |

### 4.11 APPROVAL_AGENT → ApprovalAgent

| Field | Current | New |
|---|---|---|
| **Current responsibility** | Query approval matrix; create approval task; send email; wait for response via polling | Same plus: LangGraph interrupt/resume instead of polling; multi-level sequential/parallel support; delegation |
| **Logic moved to Tools** | Matrix query → `ApprovalTool`; assignment → `AssignmentTool`; notification → `NotificationTool`; escalation → `EscalationTool`; authority check → `AuthorizationTool` |  |
| **Remaining orchestration** | Load matrix; create tasks per level; trigger interrupt; record decisions; write to `approval.*` |  |
| **Migration priority** | Critical (directly affects payment release) |  |

### 4.12 ERP_POSTING_AGENT → ERPPostingAgent

| Field | Current | New |
|---|---|---|
| **Current responsibility** | Build journal entry; post to mock ERP (PostgreSQL); store posting reference | Same plus: pluggable ERP providers; budget check; production mock guard |
| **Logic moved to Tools** | Journal build → `JournalBuilderTool`; ERP dispatch → `ERPAdapterTool`; provider selection → `ProviderSelectionTool`; budget → `BudgetTool`; posting → `PostingTool` |  |
| **Remaining orchestration** | Verify approval; build journal; post; write to `erp.*` |  |
| **Dependencies** | ERPAdapterTool, MockERPTool, JournalBuilderTool, PostingTool, BudgetTool, EnvironmentTool |  |
| **Migration priority** | Critical |  |

### 4.13 PAYMENT_AGENT → PaymentAgent

| Field | Current | New |
|---|---|---|
| **Current responsibility** | Calculate due date; apply TDS; compute net payable; store payment instruction | Same plus: payment method selection from vendor master; anti-fraud check on bank account changes |
| **Logic moved to Tools** | Due date → `PaymentScheduleTool`; TDS → `JournalBuilderTool`; vendor data → `VendorMasterTool` |  |
| **Remaining orchestration** | Fetch vendor; compute TDS; compute net payable; create payment instruction; write to `payment.*` |  |
| **Migration priority** | High |  |

### 4.14 New Agents — NotificationAgent, RetryAgent, HumanReviewAgent, AuditAgent

| Agent | Current State | Migration Note |
|---|---|---|
| **NotificationAgent** | Notification logic scattered across exception, approval, and payment agents | Centralise all notification dispatch; extract to `NotificationGraph` |
| **RetryAgent** | Retry decorators on individual Celery tasks | Centralise retry logic; implement all 4 backoff strategies; wire to `RetryGraph` |
| **HumanReviewAgent** | Polling loop in approval agent checking for decision updates | Replace polling with LangGraph `interrupt()`; build review pack from WorkflowState |
| **AuditAgent** | `AuditTool` called ad hoc from various agents | Promote to dedicated agent; add chain hashing; wire to `AuditGraph` segment of InvoiceProcessingGraph |

## 5. Tool Migration

The following table classifies each of the 112 tools by migration strategy: **Wrap** (existing code encapsulated behind tool interface), **Refactor** (existing logic modified to fit tool contract), **New** (no existing code to reuse), or **Config** (behaviour driven entirely by configuration with minimal code). Priority is **Critical**, **High**, **Medium**, or **Low**. Risk reflects migration difficulty.

### 5.1 Document Tools (12 tools)

| Tool | Strategy | Existing Code | Priority | Risk |
|---|---|---|---|---|
| `FileTool` | Wrap | File upload logic in `intake_agent.py`; MIME detection | High | Low |
| `StorageTool` | Refactor | `storage_service.py` — add provider interface; keep local impl | Critical | Medium |
| `PDFTool` | Wrap | `backend/app/tools/pdf_analyzer.py` — wrap as-is | High | Low |
| `ImageTool` | Wrap | OpenCV image loading in `ocr_agent.py` | Medium | Low |
| `MetadataTool` | Wrap | PyMuPDF metadata extraction in existing OCR/intake code | Medium | Low |
| `HashTool` | New | No existing SHA-256 hashing for files (duplicate detection uses different hash) | High | Low |
| `VirusScanTool` | New | No existing virus scanning — add ClamAV or Azure Defender hook | High | Medium |
| `ChecksumTool` | New | No existing file checksum verification on read-back | Low | Low |
| `DocumentTypeTool` | Refactor | Invoice type classification partially in `classification_agent.py` | Medium | Low |
| `PageTool` | Wrap | PyMuPDF page count in `pdf_analyzer.py` | Medium | Low |
| `FileValidationTool` | Refactor | File validation scattered in `intake_agent.py` — consolidate | High | Low |
| `CompressionTool` | New | No existing compression — needed for large document archiving | Low | Low |

### 5.2 OCR Tools (14 tools)

| Tool | Strategy | Existing Code | Priority | Risk |
|---|---|---|---|---|
| `OCRTool` | Refactor | OCR dispatch logic in `ocr_agent.py` — extract to provider pattern | Critical | Medium |
| `TesseractTool` | Wrap | `pytesseract` calls in `ocr_agent.py` — wrap with retry and config | Critical | Low |
| `AzureOCRTool` | New | No existing Azure OCR — stub implementing OCRProviderInterface | Low | Low |
| `OCRConfidenceTool` | Wrap | `image_quality.py` confidence heuristics — wrap as tool | High | Low |
| `DeskewTool` | Wrap | OpenCV deskew in `ocr_agent.py` pre-processing — wrap | High | Low |
| `ImageEnhancementTool` | Wrap | `backend/app/tools/image_quality.py` — wrap existing enhancement logic | High | Low |
| `TextCleaningTool` | Refactor | Text normalisation scattered in `extraction_agent.py` — extract | High | Low |
| `LanguageDetectionTool` | New | No existing language detection — add `langdetect` library | Medium | Low |
| `TableExtractionTool` | New | No structured table extraction — new capability needed | Medium | High |
| `BoundingBoxTool` | New | No bounding box extraction — needed for field-location highlighting | Low | Medium |
| `BarcodeTool` | New | No barcode reading — needed for PO reference barcodes | Low | Low |
| `QRCodeTool` | New | No QR code reading | Low | Low |
| `CoordinateExtractionTool` | New | No field coordinate extraction — needed for UI highlighting | Low | Medium |
| `PageRotationTool` | Wrap | OpenCV rotation correction in `ocr_agent.py` | Medium | Low |

### 5.3 AI/LLM Tools (11 tools)

| Tool | Strategy | Existing Code | Priority | Risk |
|---|---|---|---|---|
| `LLMTool` | Refactor | `openai.ChatCompletion` calls in `extraction_agent.py` — extract to provider interface | Critical | Medium |
| `PromptTool` | Refactor | YAML prompt loading in each agent — centralise | High | Low |
| `ExtractionTool` | Refactor | JSON parsing + field mapping in `extraction_agent.py` — extract | Critical | Medium |
| `ClassificationTool` | Refactor | LLM classification calls in `business_profile_agent.py` — extract | High | Low |
| `BusinessProfileTool` | Refactor | Rule-based profiling in `business_profile_agent.py` — extract | High | Low |
| `NormalizationTool` | Refactor | Date/currency normalisation in `extraction_agent.py` — extract | High | Low |
| `ConfidenceTool` | New | No systematic confidence scoring — new capability | High | Medium |
| `TokenTrackingTool` | New | No token usage tracking — add Redis counter per tenant | High | Low |
| `SummaryTool` | New | No summarisation — needed for exception and audit summaries | Low | Low |
| `ReasoningTool` | New | No reasoning chain capture — needed for explainability | Medium | Low |

### 5.4 Validation Tools (14 tools)

| Tool | Strategy | Existing Code | Priority | Risk |
|---|---|---|---|---|
| `ValidationTool` | Refactor | Validation orchestration in `validation_agent.py` — extract | Critical | Low |
| `MandatoryFieldTool` | Refactor | Field presence checks in `validation_agent.py` — extract | Critical | Low |
| `GSTValidationTool` | Wrap | GST regex in `validation_agent.py` — wrap; add GSTIN checksum | Critical | Low |
| `PANValidationTool` | Wrap | PAN regex in `validation_agent.py` — wrap | High | Low |
| `ArithmeticValidationTool` | Wrap | Arithmetic check in `validation_agent.py` — wrap; add tolerance | Critical | Low |
| `DateValidationTool` | Refactor | Date checks in `validation_agent.py` — extract and extend | High | Low |
| `CurrencyValidationTool` | New | No currency validation — add ISO 4217 check | Medium | Low |
| `InvoiceNumberValidationTool` | Refactor | Invoice number uniqueness check in `validation_agent.py` | High | Low |
| `TaxValidationTool` | Refactor | Tax rate check partially in `validation_agent.py` | High | Medium |
| `DuplicateDetectionTool` | Refactor | Duplicate hash query in `validation_agent.py` — extract; add Redis cache | Critical | Low |
| `ToleranceValidationTool` | New | Tolerance logic exists but is hardcoded in matching agent — extract and make configurable | High | Medium |
| `BusinessRuleTool` | Refactor | Business rules hardcoded in agents — extract to RuleEngine | High | Medium |
| `ProfileValidationTool` | Refactor | Profile rules in `profile_validation_agent.py` — extract | High | Low |
| `VendorValidationTool` | New | No vendor blacklist check — new capability | Medium | Low |

### 5.5 Matching Tools (10 tools)

| Tool | Strategy | Existing Code | Priority | Risk |
|---|---|---|---|---|
| `VendorMatchingTool` | Refactor | Vendor name comparison in `matching_agent.py` — extract | High | Low |
| `POMatchingTool` | Refactor | PO matching logic in `matching_agent.py` — extract | Critical | Medium |
| `GRNMatchingTool` | Refactor | GRN matching logic in `matching_agent.py` — extract | Critical | Medium |
| `ThreeWayMatchingTool` | Refactor | Three-way verdict in `matching_agent.py` — extract | Critical | Medium |
| `ComparisonTool` | Refactor | Field comparison utilities in `matching_agent.py` — extract | High | Low |
| `SimilarityTool` | New | No text similarity scoring — add `rapidfuzz` or similar | Medium | Low |
| `VarianceTool` | Refactor | Variance calculation in `matching_agent.py` — extract | High | Low |
| `BlanketPOTool` | New | No blanket PO support — new capability | Medium | Medium |
| `ContractMatchingTool` | New | No contract-backed matching — new capability | Medium | Medium |
| `LeaseMatchingTool` | New | No lease matching — new capability for LEASE_RENT profile | Medium | Medium |

### 5.6 ERP Tools (14 tools)

| Tool | Strategy | Existing Code | Priority | Risk |
|---|---|---|---|---|
| `ERPAdapterTool` | Refactor | `erp_provider.py` dispatch — extract to provider interface | Critical | Medium |
| `MockERPTool` | Wrap | `erp_provider.py` mock implementation — wrap behind interface | Critical | Low |
| `SAPAdapterTool` | New | SAP stub — implement ERPProviderInterface; no functional code yet | Low | Low |
| `OracleAdapterTool` | New | Oracle stub | Low | Low |
| `DynamicsAdapterTool` | New | Dynamics 365 stub | Low | Low |
| `NetSuiteAdapterTool` | New | NetSuite stub | Low | Low |
| `JournalBuilderTool` | Refactor | Journal entry building in `erp_posting_agent.py` — extract | Critical | Medium |
| `PostingTool` | Refactor | ERP submission in `erp_posting_agent.py` — extract | Critical | Medium |
| `PaymentScheduleTool` | Refactor | Due date / payment scheduling in `payment_agent.py` — extract | High | Low |
| `VendorMasterTool` | Refactor | Vendor lookup in `payment_agent.py` — extract; add interface | High | Low |
| `PurchaseOrderTool` | Refactor | PO fetch in `matching_agent.py` — extract; add ERP interface | Critical | Medium |
| `GoodsReceiptTool` | Refactor | GRN fetch in `matching_agent.py` — extract; add ERP interface | Critical | Medium |
| `AssetTool` | New | Asset register lookup for CAPEX profiles — new capability | Medium | Low |
| `BudgetTool` | New | Budget check for posting — new capability | Medium | Low |

### 5.7 Workflow Tools (13 tools)

| Tool | Strategy | Existing Code | Priority | Risk |
|---|---|---|---|---|
| `WorkflowStateTool` | New | No unified state object — new (central to LangGraph migration) | Critical | High |
| `QueueTool` | Refactor | Redis/Celery task enqueue in `tasks/` — extract to tool | High | Low |
| `RetryTool` | Refactor | Celery `@retry` decorators on tasks — extract backoff logic | High | Low |
| `ResumeTool` | New | No interrupt/resume — new LangGraph capability | Critical | High |
| `ApprovalTool` | Refactor | Approval matrix query in `approval_agent.py` — extract | Critical | Low |
| `ExceptionTool` | Refactor | Exception classification in `exception_agent.py` — extract | High | Low |
| `NotificationTool` | Refactor | Email/notification calls scattered across agents — centralise | High | Low |
| `AuditTool` | Refactor | `backend/app/tools/audit_tool.py` — upgrade with chain hashing | Critical | Low |
| `TimelineTool` | New | No structured workflow timeline — new capability | Medium | Low |
| `LoggingTool` | New | Standard Python logging — replace with structured JSON logging | High | Low |
| `AnalyticsTool` | New | No metrics aggregation — new capability | Low | Low |
| `AssignmentTool` | New | Assignment logic in `exception_agent.py` / `approval_agent.py` — extract | High | Low |
| `EscalationTool` | New | SLA escalation logic in `exception_agent.py` — extract | High | Low |

### 5.8 Storage Tools (6 tools)

| Tool | Strategy | Existing Code | Priority | Risk |
|---|---|---|---|---|
| `LocalStorageTool` | Wrap | `storage_service.py` local filesystem — wrap behind interface | Critical | Low |
| `AzureBlobStorageTool` | New | No Azure Blob — new (activated in Phase 8) | High | Low |
| `DocumentVersionTool` | New | No document versioning — new capability | Medium | Low |
| `ArchiveTool` | New | No archiving — new capability | Low | Low |
| `BackupTool` | New | No automated backup — new capability | Low | Low |
| `RestoreTool` | New | No restore — new capability | Low | Low |

### 5.9 Prompt Tools (6 tools)

| Tool | Strategy | Existing Code | Priority | Risk |
|---|---|---|---|---|
| `PromptRegistryTool` | Refactor | Prompt YAML loading in each agent — centralise | High | Low |
| `PromptLoaderTool` | Refactor | YAML load + format in agents — extract | High | Low |
| `PromptVersionTool` | New | No version management — new capability | High | Low |
| `PromptTemplateTool` | Refactor | Jinja2 formatting in agents — replace with SandboxedEnvironment | High | Medium |
| `PromptAuditTool` | New | No prompt change audit — new capability | Medium | Low |
| `PromptEvaluationTool` | New | No prompt quality evaluation — new capability | Low | Low |

### 5.10 Configuration Tools (6 tools)

| Tool | Strategy | Existing Code | Priority | Risk |
|---|---|---|---|---|
| `ConfigurationTool` | New | Config in env vars + hardcoded values — extract to YAML | Critical | Medium |
| `RuleEngineTool` | New | Rules hardcoded in agents — extract to YAML engine | High | Medium |
| `FeatureFlagTool` | New | No feature flags — new (critical for incremental migration) | Critical | Low |
| `ThresholdTool` | New | Thresholds hardcoded in agent code — extract | High | Medium |
| `EnvironmentTool` | New | `os.getenv("ENV")` checks scattered — centralise | High | Low |
| `ProviderSelectionTool` | New | Provider selection hardcoded — extract to config | High | Low |

### 5.11 Security Tools (6 tools)

| Tool | Strategy | Existing Code | Priority | Risk |
|---|---|---|---|---|
| `AuthenticationTool` | Refactor | JWT auth in FastAPI middleware — wrap as tool | High | Low |
| `AuthorizationTool` | Refactor | Permission checks in route handlers — extract to tool | High | Low |
| `EncryptionTool` | New | No field-level encryption — new capability | Medium | Medium |
| `MaskingTool` | New | No PII masking in logs — new capability | Critical | Low |
| `PIITool` | New | No PII detection — new capability | High | Medium |
| `SecretManagerTool` | New | Secrets in env vars — new (Azure Key Vault wrapper) | High | Low |

### 5.12 Tool Migration Summary

| Category | Total Tools | Wrap | Refactor | New | Critical Priority |
|---|---|---|---|---|---|
| Document | 12 | 6 | 3 | 3 | 2 |
| OCR | 14 | 5 | 3 | 6 | 1 |
| AI/LLM | 11 | 0 | 5 | 6 | 3 |
| Validation | 14 | 3 | 8 | 3 | 5 |
| Matching | 10 | 0 | 5 | 5 | 4 |
| ERP | 14 | 1 | 7 | 6 | 6 |
| Workflow | 13 | 0 | 5 | 8 | 3 |
| Storage | 6 | 1 | 0 | 5 | 1 |
| Prompt | 6 | 0 | 3 | 3 | 0 |
| Configuration | 6 | 0 | 0 | 6 | 3 |
| Security | 6 | 0 | 2 | 4 | 1 |
| **Total** | **112** | **16** | **41** | **55** | **29** |

<!-- SECTION_BOUNDARY_6 -->
## 6. LangGraph Migration

### 6.1 WorkflowState Lifecycle

WorkflowState is the single source of truth for every invoice's processing state. It is created at upload, updated by every agent node, checkpointed at every interrupt, and archived at workflow completion.

**Creation**
- Created by UploadAgent as an empty `WorkflowState` with only `document_id`, `tenant_id`, `workflow.status = UPLOADED`, and `workflow.created_at`
- Persisted to PostgreSQL via the LangGraph `PostgresSaver` checkpointer immediately after creation

**Updates**
- Every agent node receives the full `WorkflowState`, modifies only its designated section (see `agents.md` — Section 4), and returns the updated state
- LangGraph checkpoints the updated state after every successful node execution
- Agents use immutable Pydantic model update (`.model_copy(update={...})`) — no in-place mutation

**Checkpointing**
- `PostgresSaver` writes to `langgraph_checkpoints` table after each node completes
- On interrupt: state is checkpointed before `interrupt()` is called — guaranteed durability
- On resume: state is restored from the latest checkpoint for the `thread_id` (= `document_id`)

**Archiving**
- On workflow completion (`payment` node success), WorkflowState is serialised to JSON and stored in `workflow_state_archive` table for long-term audit access
- Active checkpoints (in `langgraph_checkpoints`) are retained for 30 days, then purged

**Access pattern**
```
API Layer → graph.invoke(state, config={"configurable": {"thread_id": document_id}})
         ← returns updated WorkflowState

Resume → graph.invoke(Command(resume=decision), config={"configurable": {"thread_id": document_id}})
       ← returns updated WorkflowState from checkpoint
```

### 6.2 Graph Orchestration

**Triggering graphs**

| Trigger | Method |
|---|---|
| New invoice upload | `InvoiceProcessingGraph.invoke(initial_state)` called from FastAPI upload handler |
| Exception raised | `ExceptionGraph.invoke(state)` called by InvoiceProcessingGraph conditional edge |
| Human review needed | `HumanReviewGraph.invoke(state)` called by InvoiceProcessingGraph conditional edge |
| Approval needed | `ApprovalGraph.invoke(state)` called by InvoiceProcessingGraph confidence edge |
| Operation failed | `RetryGraph.invoke(state)` called by ExceptionGraph retry node |
| Event notification | `NotificationGraph.invoke(state)` called asynchronously via Celery task |

**Graph compilation**
- All 6 graphs are compiled at application startup (not per-request)
- Compiled graphs are stored in a `GraphRegistry` singleton
- `GraphRegistry.get(graph_name)` returns the compiled, checkpointer-wired graph instance

**Thread safety**
- Each `document_id` is an independent `thread_id` in LangGraph
- Concurrent invocations on different `document_id`s are fully isolated
- No shared mutable state between threads

**Streaming (optional)**
- Graphs can be invoked with `.stream()` instead of `.invoke()` for real-time status updates
- FastAPI can expose `GET /api/v1/workflows/{id}/stream` as a Server-Sent Events endpoint for live UI updates

### 6.3 Celery Integration During Migration

Celery is retained throughout the migration for two purposes:

**During Phases 0–3** (before LangGraph takes over):
- Celery shims wrap refactored agents and keep the existing pipeline running
- Each shim: create minimal WorkflowState → call `agent.execute(state)` → write results back to PostgreSQL

**After Phase 4** (LangGraph is primary):
- Celery is demoted to handling side tasks only:
  - Async notification dispatch (triggered by NotificationGraph)
  - Document export generation
  - Audit log archiving
  - Scheduled SLA reminder tasks (Celery Beat)
- Celery Beat replaces the polling loop previously used in the approval agent

**Celery tasks retained in long term**:
```
backend/app/tasks/
├── notification_tasks.py  # Called by NotificationGraph async dispatch
├── export_tasks.py        # PDF/Excel audit exports
├── archive_tasks.py       # Long-term audit log archiving
└── sla_reminder_tasks.py  # SLA breach reminder (Celery Beat schedule)
```

### 6.4 Checkpointing

**PostgresSaver configuration**

- Table: `langgraph_checkpoints` (created by Alembic migration in Phase 0)
- Thread ID: `document_id` (UUID)
- Config key: `{"configurable": {"thread_id": document_id, "tenant_id": tenant_id}}`
- Serialiser: JSON (WorkflowState → JSON via Pydantic `.model_dump()`)

**Checkpoint events**

| Event | Checkpoint Written |
|---|---|
| Node completes successfully | Yes — state after node |
| Node raises AgentException | Yes — state at failure with error fields |
| interrupt() called | Yes — guaranteed before interrupt |
| Graph END reached | Yes — final state |

**Checkpoint retention policy**

| State | Retention |
|---|---|
| Active (in-flight invoices) | Indefinite until workflow END |
| Completed workflows | 30 days in `langgraph_checkpoints`, then purged |
| Archived state | Permanently in `workflow_state_archive` table |

**Checkpoint recovery**
- If FastAPI process restarts, all in-flight workflows resume from their latest checkpoint on next invocation
- No manual intervention required — LangGraph handles checkpoint restoration transparently

### 6.5 Pause / Resume

**Pause mechanism**: LangGraph `interrupt()`
- Called inside agent node function: `interrupt(value=InterruptContext(reason=..., review_context=...))`
- LangGraph checkpoints state, suspends the graph thread, and returns control to the caller
- The FastAPI handler receives `Interrupt` exception, records `workflow.status = UNDER_REVIEW | AWAITING_APPROVAL`, and returns HTTP 202 to the client

**Resume mechanism**: `graph.invoke(Command(resume=decision))`
- Called from FastAPI endpoint when reviewer/approver submits decision
- LangGraph restores state from checkpoint, injects the decision as the interrupt return value, and continues execution from the interrupted node

**Pause points in each graph**:

| Graph | Pause Points | Resume Trigger |
|---|---|---|
| HumanReviewGraph | After `review_notify` | `POST /workflows/{id}/resume` |
| ApprovalGraph | After `approval_notify` (per level) | `POST /workflows/{id}/approve` |
| ExceptionGraph | After `exception_notify` | `POST /workflows/{id}/exceptions/{id}/resolve` |

**Timeout handling**:
- Celery Beat schedules SLA reminder checks every hour
- `SLACheckerTask` queries `langgraph_checkpoints` for threads paused longer than SLA deadline
- On SLA breach, task calls `graph.invoke(Command(resume=SLABreachSignal()))` to trigger escalation node

### 6.6 Human Review

**Review request flow**:
1. ConfidenceAgent sets `routing.requires_human_review = True` in WorkflowState
2. InvoiceProcessingGraph routes to `HumanReviewGraph`
3. HumanReviewGraph calls `interrupt()` after notifying the reviewer
4. State is checkpointed; workflow is suspended

**Review pack construction** (from checkpointed WorkflowState):
- Flagged fields: fields where confidence < threshold
- Validation errors: from `validation.errors` and `profile_validation.errors`
- Match variances: from `matching.po_variances` and `matching.grn_variances`
- Confidence breakdown: from `confidence.contributing_factors`
- Document image URL: from `document.storage_path`
- Original extracted values: from `invoice.*`

**Review decision types**:

| Decision | Effect |
|---|---|
| `APPROVED` | Resume at node after original interrupt trigger |
| `CORRECTED` | Apply corrections to WorkflowState; resume at earliest affected node |
| `REJECTED` | Terminate workflow; emit INVOICE_REJECTED; notify submitter |
| `ESCALATE` | Assign to senior reviewer; extend SLA |

**Correction-aware resume**:
- If corrections touch `invoice.*` (extraction fields) → resume at `validate`
- If corrections touch `matching.*` (PO/GRN references) → resume at `match_po`
- If corrections touch `profile.*` (business profile) → resume at `profile_validate`
- If no corrections (pure approval) → resume at the node immediately after the interrupted node

### 6.7 Retry Strategy

**Per-agent retry** (Phases 0–3, Celery):
- Celery `@retry(max_retries=N, countdown=seconds)` on each task
- Non-retryable errors: declared in each agent config; Celery will not retry these

**LangGraph RetryGraph** (Phase 4+):
- On `AgentException` raised inside a graph node, the graph error handler routes to `RetryGraph`
- RetryGraph receives: `failed_agent`, `failure_reason`, `retry_count`, `error_type`
- RetryGraph applies the backoff strategy declared in `core/config/retry_config.yaml`
- On success: returns to original graph at the failed node
- On exhaustion: routes to ExceptionGraph with `RETRY_EXHAUSTED` severity

**Backoff strategies** (all configuration-driven):

| Strategy | Formula | When To Use |
|---|---|---|
| `EXPONENTIAL_JITTER` | `base * 2^n * rand(0.5, 1.5)` | ERP API calls, LLM calls |
| `EXPONENTIAL` | `base * 2^n` | Storage writes, database connections |
| `LINEAR` | `base * n` | Notification channel retries |
| `FIXED` | `base` (constant) | Deterministic operations that need a cool-down |

<!-- SECTION_BOUNDARY_7 -->
## 7. Database & API Migration

### 7.1 Tables to Keep (no changes)

| Table | Purpose | Changes |
|---|---|---|
| `invoices` | Invoice master record | Add `workflow_state_id` FK column |
| `invoice_line_items` | Invoice line details | No changes |
| `vendors` | Vendor master | No changes |
| `purchase_orders` | PO records | No changes |
| `goods_receipts` | GRN records | No changes |
| `approvals` | Approval records | Add `approval_level`, `delegate_id` columns |
| `exceptions` | Exception records | Add `exception_type`, `sla_deadline`, `escalation_level` columns |
| `audit_logs` | Audit trail | Add `event_chain_hash` column; ensure no UPDATE/DELETE permissions |
| `users` | User records | No changes |
| `roles` | RBAC roles | Add new roles: `INVOICE_REVIEW`, `EXCEPTION_RESOLVE_*` |
| `assets` | Asset register | No changes |
| `employees` | Employee master | No changes |
| `leases` | Lease contracts | No changes |
| `contracts` | Purchase contracts | No changes |

### 7.2 New Tables

| Table | Purpose | Added In |
|---|---|---|
| `langgraph_checkpoints` | LangGraph PostgresSaver state storage | Phase 0 (migration P0-09) |
| `workflow_state_archive` | Long-term serialised WorkflowState after completion | Phase 4 |
| `tenants` | Multi-tenant registry | Phase 7 |
| `tenant_configs` | Per-tenant config overrides (DB-backed) | Phase 7 |
| `prompt_versions` | Versioned prompt history | Phase 1 |
| `token_usage` | Per-tenant LLM token consumption tracking | Phase 2 |
| `workflow_timelines` | Ordered agent execution events per document | Phase 5 |
| `notification_logs` | Notification delivery history | Phase 4 |
| `retry_logs` | Retry attempt history per operation | Phase 4 |
| `exception_resolution_history` | Full exception resolution audit trail | Phase 4 |
| `feature_flags` | Per-tenant feature flag overrides | Phase 1 |

### 7.3 Schema Changes (existing tables)

| Table | Column Added | Type | Purpose |
|---|---|---|---|
| `invoices` | `tenant_id` | UUID | Multi-tenant scoping |
| `invoices` | `workflow_state_id` | UUID | FK to `langgraph_checkpoints` |
| `invoices` | `overall_confidence_score` | FLOAT | From ConfidenceAgent output |
| `invoices` | `business_profile` | VARCHAR | Profile enum value |
| `invoices` | `processing_graph` | VARCHAR | Which LangGraph graph was used |
| `approvals` | `approval_level` | INTEGER | Level in multi-level matrix |
| `approvals` | `delegate_id` | UUID | If approval was delegated |
| `approvals` | `authority_amount` | NUMERIC | Amount authorised at this level |
| `exceptions` | `exception_type` | VARCHAR | Classified exception type enum |
| `exceptions` | `sla_deadline` | TIMESTAMP | SLA resolution deadline |
| `exceptions` | `escalation_level` | INTEGER | How many times escalated |
| `exceptions` | `resolution_type` | VARCHAR | AUTO_FIX / MANUAL_FIX / OVERRIDE |
| `audit_logs` | `event_chain_hash` | VARCHAR | Running tamper-detection hash |
| `audit_logs` | `agent_name` | VARCHAR | Agent that emitted the event |
| `audit_logs` | `workflow_status` | VARCHAR | Status at time of event |
| `vendors` | `tds_category` | VARCHAR | TDS rate category |
| `vendors` | `payment_method` | VARCHAR | NEFT / RTGS / IMPS / CHEQUE |
| `vendors` | `bank_account_changed_at` | TIMESTAMP | Anti-fraud: last bank detail change |

### 7.4 Endpoint Mapping

#### Preserved Endpoints (no changes — backward compatible)

| Method | Path | Status |
|---|---|---|
| POST | `/api/v1/documents/upload` | Unchanged (UploadAgent triggered internally) |
| GET | `/api/v1/documents` | Unchanged |
| GET | `/api/v1/documents/{id}` | Unchanged |
| GET | `/api/v1/exceptions` | Unchanged |
| PATCH | `/api/v1/exceptions/{id}` | Unchanged |
| GET | `/api/v1/approvals` | Unchanged |
| POST | `/api/v1/approvals/{id}/approve` | Unchanged (internally calls ApprovalGraph) |
| POST | `/api/v1/approvals/{id}/reject` | Unchanged |
| GET | `/api/v1/audit-logs` | Unchanged |
| GET | `/api/v1/dashboard/stats` | Unchanged |
| POST | `/api/v1/auth/login` | Unchanged |

#### New Endpoints (Phase 5)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/workflows/{id}/state` | Full WorkflowState JSON |
| GET | `/api/v1/workflows/{id}/timeline` | Agent execution timeline |
| GET | `/api/v1/workflows/{id}/confidence` | Confidence breakdown |
| GET | `/api/v1/workflows/{id}/agent-trace` | Per-agent execution log |
| GET | `/api/v1/workflows/{id}/review` | Human review pack |
| POST | `/api/v1/workflows/{id}/resume` | Submit review decision |
| POST | `/api/v1/workflows/{id}/approve` | Submit approval decision |
| GET | `/api/v1/workflows/{id}/stream` | Server-Sent Events live updates |
| POST | `/api/v1/exceptions/{id}/resolve` | Submit exception resolution |
| GET | `/api/v1/prompts` | List prompt versions |
| POST | `/api/v1/prompts/{name}/activate` | Activate prompt version |
| GET | `/api/v1/prompts/{name}/history` | Prompt version history |
| GET | `/api/v1/config` | Tenant configuration |
| PATCH | `/api/v1/config` | Update configuration |
| GET | `/api/v1/tenants` | List tenants (admin) |
| POST | `/api/v1/tenants` | Create tenant (admin) |

### 7.5 Backward Compatibility Strategy

1. **Existing endpoints are never modified** — they continue to return identical response shapes
2. **New endpoints use `X-Tenant-ID` header** — existing endpoints default to `tenant_id = "default"`
3. **Response schema versioning** — existing response models are not changed; new fields added to new endpoints only
4. **Feature flag controls rollout** — `feature.use_langgraph_pipeline` flag allows instant rollback to Celery pipeline without endpoint changes
5. **Database changes are additive** — new columns are nullable with defaults; no existing columns modified or removed
6. **Alembic migrations are forward-only** — rollback scripts are written for every migration but not auto-applied

## 8. Frontend Migration

The Next.js frontend is migrated incrementally — one page or component at a time. No existing pages are removed or broken. New capabilities are introduced as new components that progressively replace inline content on existing pages.

### 8.1 Migration Approach

**Principle**: Every sprint delivers a working page. No frontend work begins until the backing API endpoint (Phase 5) is live.

**Strategy per page**:
1. Keep the existing page rendering its current data from current endpoints
2. Add a feature-flagged `<EnhancedView />` component that uses the new endpoints
3. Once the enhanced view is validated, replace the legacy component
4. Remove the legacy code and feature flag

**Shared components to build once, reuse everywhere**:

| Component | Purpose | Used By |
|---|---|---|
| `ConfidenceBadge` | Colour-coded confidence score pill | Document Detail, Approval Center |
| `AgentTimeline` | Vertical timeline of agent execution steps | Workflow Timeline, Document Detail |
| `WorkflowStatusBanner` | Status + interrupt reason banner | Document Detail, Exception Center |
| `FieldHighlighter` | Highlight extracted fields with confidence overlay | Document Detail |
| `ReviewDecisionPanel` | Review/approve/reject decision form | Human Review, Approval Center |
| `ExplainabilityDrawer` | Side drawer with confidence breakdown and reasoning | Document Detail, AI Confidence Panel |
| `AuditEventRow` | Single audit event display with actor, action, timestamp | Audit Trail |

### 8.2 Document Detail Page

**Current state**: Shows extracted invoice fields, status badge, and a basic action menu.

**Enhancements** (incremental):

| Sprint | Enhancement | New API Used |
|---|---|---|
| 1 | Add `WorkflowStatusBanner` showing current agent and status | `GET /workflows/{id}/state` |
| 1 | Add `ConfidenceBadge` next to overall status | `GET /workflows/{id}/confidence` |
| 2 | Add per-field confidence overlays on extracted data | `GET /workflows/{id}/confidence` |
| 2 | Add `ExplainabilityDrawer` showing confidence breakdown and contributing factors | `GET /workflows/{id}/confidence` |
| 3 | Add `AgentTimeline` sidebar showing each agent's execution step | `GET /workflows/{id}/timeline` |
| 3 | Highlight fields flagged for review in amber | `GET /workflows/{id}/review` |
| 4 | Add `ReviewDecisionPanel` when document is `UNDER_REVIEW` | `POST /workflows/{id}/resume` |
| 4 | Add live status streaming via Server-Sent Events | `GET /workflows/{id}/stream` |

### 8.3 Exception Center

**Current state**: Table of open exceptions with status, queue, and basic resolve button.

**Enhancements**:

| Sprint | Enhancement | New API Used |
|---|---|---|
| 1 | Add exception type badge and SLA countdown timer | `GET /exceptions` (extended response) |
| 1 | Add queue filter tabs (AP_TEAM, FINANCE, PROCUREMENT, COMPLIANCE, WAREHOUSE) | `GET /exceptions?queue=` |
| 2 | Add exception resolution form with `resolution_type` selector (AUTO_FIX / MANUAL_FIX / OVERRIDE) | `POST /exceptions/{id}/resolve` |
| 2 | Add resolution history accordion showing all prior attempts | `GET /exceptions/{id}/history` |
| 3 | Add escalation indicator and escalated-to badge | Extended exception response |
| 3 | Add related invoice mini-card (confidence, match score) in exception detail panel | `GET /workflows/{id}/confidence` |

### 8.4 Approval Center

**Current state**: List of invoices pending approval with approve/reject buttons.

**Enhancements**:

| Sprint | Enhancement | New API Used |
|---|---|---|
| 1 | Add approval level indicator (Level 1 of 3) and level-specific approver name | `GET /approvals` (extended response) |
| 1 | Add invoice summary card with confidence score and match disposition | `GET /workflows/{id}/state` |
| 2 | Replace basic approve/reject with `ReviewDecisionPanel` (supports delegation, comments) | `POST /workflows/{id}/approve` |
| 2 | Add SLA countdown and escalation warning for overdue approvals | Existing + SLA fields |
| 3 | Add GL account preview showing proposed journal entries before approval | `GET /workflows/{id}/state` → `erp.gl_accounts` |
| 3 | Add three-way match summary card (PO, GRN, invoice amounts side-by-side) | `GET /workflows/{id}/state` → `matching.*` |

### 8.5 Workflow Timeline

**Current state**: Not present — no timeline view exists.

**Build from scratch** (new page at `/documents/{id}/timeline`):

| Sprint | Component | Description |
|---|---|---|
| 1 | `AgentTimeline` base component | Vertical timeline with agent name, status icon, duration |
| 1 | Status icon set | COMPLETED (green), FAILED (red), SKIPPED (grey), IN_PROGRESS (spinner), INTERRUPTED (amber) |
| 2 | Expandable step detail | Click any step to expand: input state fields, output state fields, tool calls made |
| 2 | Duration bar chart | Mini bar chart showing relative time per agent step |
| 3 | Exception marker | Show exception events inline on the timeline |
| 3 | Human review marker | Show review interrupts and resume events with reviewer identity |
| 3 | Live update support | Stream new events as they arrive via SSE |

### 8.6 Audit Trail

**Current state**: Table of audit log entries with event type, timestamp, and user.

**Enhancements**:

| Sprint | Enhancement | New API Used |
|---|---|---|
| 1 | Add agent name column and workflow status at event time | Existing + new `agent_name`, `workflow_status` columns |
| 1 | Add event severity colour coding (INFO=grey, WARNING=amber, ERROR=red, CRITICAL=purple) | Existing |
| 2 | Add audit chain integrity indicator (green lock = chain valid) | Integrity check from `GET /audit-logs/{id}/integrity` |
| 2 | Add export to CSV / PDF for compliance reporting | `GET /audit-logs?format=csv` |
| 3 | Add event filter by agent, severity, date range | Query params on existing endpoint |
| 3 | Add document-level audit view (all events for one invoice) | `GET /audit-logs?document_id=` |

### 8.7 AI Confidence Panel

**Current state**: Not present.

**Build from scratch** (embedded in Document Detail as collapsible panel):

| Sprint | Component | Description |
|---|---|---|
| 1 | Overall score gauge | Circular gauge 0–100%; colour bands: HIGH=green, MEDIUM=amber, LOW=red, CRITICAL=dark red |
| 1 | Component score table | OCR confidence, extraction confidence, validation pass, match score, profile confidence |
| 2 | Contributing factors list | Positive factors (green check) and negative factors (red flag) from `confidence.contributing_factors` |
| 2 | Field-level confidence table | Every extracted field with its individual confidence score |
| 3 | LLM reasoning expandable | Collapsible section showing LLM reasoning chain from `extraction.reasoning` |
| 3 | Confidence history sparkline | How confidence score changed across retries/reviews |

### 8.8 Agent Execution Details

**Current state**: Not present.

**Build from scratch** (accessible from Workflow Timeline page):

| Sprint | Component | Description |
|---|---|---|
| 1 | Agent execution card | Agent name, status, start time, duration, output summary |
| 2 | Tool call list | Each tool called by the agent with input params (PII masked) and result |
| 2 | State diff view | Before/after WorkflowState fields for the agent's designated section |
| 3 | Retry history | If agent was retried, show each attempt with failure reason and backoff |
| 3 | Audit event link | Link each agent execution to its corresponding audit event |

### 8.9 Admin Panel Additions

| Feature | Description | Phase |
|---|---|---|
| Prompt version manager | List prompt versions; activate/rollback; preview rendered output | Phase 6 |
| Tenant configuration editor | Edit YAML config via structured form; live reload | Phase 7 |
| Token usage dashboard | Per-tenant LLM token consumption; budget remaining; trend chart | Phase 7 |
| Feature flag manager | Toggle feature flags per tenant | Phase 7 |
| Tenant registry | Create/edit tenants; assign config profiles | Phase 7 |

---

## 9. Implementation Order

The following sequence defines the exact development order from initial scaffolding to production-ready platform. Tasks within the same week can be parallelised across team members.

### Weeks 1–2: Phase 0 — Scaffolding

| Order | Task | Deliverable |
|---|---|---|
| 1 | Create new folder structure | `core/`, `tests/` directories exist |
| 2 | Install LangGraph + Pydantic v2 | `requirements.txt` updated; CI passes |
| 3 | Alembic migration: `langgraph_checkpoints` | Table created in dev DB |
| 4 | `BaseTool`, `BaseAgent`, `BaseRepository` | Abstract interfaces defined and type-checked |
| 5 | Provider interfaces (OCR, LLM, ERP, Storage) | Interface contracts defined |
| 6 | CI pipeline for `core/` | `mypy`, `ruff`, `pytest` running on new code |
| 7 | Coding standards documented | `CONTRIBUTING.md` committed |

### Weeks 3–4: Phase 1 — Core Infrastructure

| Order | Task | Deliverable |
|---|---|---|
| 8 | Full `WorkflowState` Pydantic model | All 20 sections; passes validation tests |
| 9 | `EnvironmentTool`, `FeatureFlagTool` | Feature flags working; `is_production()` guard available |
| 10 | `ConfigurationTool` | YAML loading + Redis cache; tenant override support |
| 11 | `RuleEngineTool` | YAML rule chain execution; 100% unit tested |
| 12 | `LoggingTool` | Structured JSON logging; PII masking verified |
| 13 | `AuditTool` (upgraded) | Append-only writes; chain hash; 100% tested |
| 14 | `AuthorizationTool` | RBAC checks; wraps existing middleware |
| 15 | `SecretManagerTool` | Key Vault stub (env vars in dev) |
| 16 | Prompt YAML migration | All existing prompts in `core/prompts/v1/` with `version: "1.0"` |
| 17 | `PromptRegistryTool` + `PromptLoaderTool` | Prompts loading from new location; agents still work |

### Weeks 5–8: Phase 2 — Tool Layer (four parallel workstreams)

| Workstream | Weeks | Tools |
|---|---|---|
| A — Document + OCR tools | 5–6 | `FileTool`, `StorageTool`, `PDFTool`, `OCRTool`, `TesseractTool`, `DeskewTool`, `ImageEnhancementTool`, `OCRConfidenceTool`, `TextCleaningTool` |
| B — AI/LLM + Validation tools | 5–6 | `LLMTool`, `ExtractionTool`, `ClassificationTool`, `NormalizationTool`, `ConfidenceTool`, `TokenTrackingTool`, `GSTValidationTool`, `PANValidationTool`, `ArithmeticValidationTool`, `DuplicateDetectionTool` |
| C — Matching + ERP tools | 7–8 | `POMatchingTool`, `GRNMatchingTool`, `ThreeWayMatchingTool`, `VarianceTool`, `ToleranceValidationTool`, `ERPAdapterTool`, `MockERPTool`, `JournalBuilderTool`, `PostingTool`, `PurchaseOrderTool`, `GoodsReceiptTool` |
| D — Workflow + Security tools | 7–8 | `ApprovalTool`, `ExceptionTool`, `NotificationTool`, `AssignmentTool`, `EscalationTool`, `RetryTool`, `QueueTool`, `MaskingTool`, `PIITool`, `PaymentScheduleTool`, `VendorMasterTool` |

**Gate**: All Critical-priority tools unit-tested before any agent refactoring begins.

### Weeks 9–12: Phase 3 — Agent Refactoring

| Order | Agents | Why This Order |
|---|---|---|
| 18 | `UploadAgent`, `ClassificationAgent` | Entry points — safest to refactor first |
| 19 | `OCRAgent`, `ExtractionAgent` | High-value; wrap existing LLM calls |
| 20 | `ValidationAgent` | Highest test coverage; low regression risk |
| 21 | `BusinessProfileAgent`, `ProfileValidationAgent` | Self-contained; no cross-agent dependencies |
| 22 | `POMatchingAgent`, `GRNMatchingAgent`, `ThreeWayMatchingAgent` | Split from monolith; must be done together |
| 23 | `ConfidenceAgent` | New — no regression risk; depends on all prior agents |
| 24 | `ExceptionAgent`, `RetryAgent` | Exception path — refactor after happy path is solid |
| 25 | `ApprovalAgent`, `HumanReviewAgent` | Human workflows — complex; needs review endpoint |
| 26 | `ERPPostingAgent`, `PaymentAgent` | Financial — highest caution; parallel run validation |
| 27 | `NotificationAgent`, `AuditAgent` | Side-effect agents — lowest risk |

**Gate**: All 19 agents pass full regression suite via Celery shims before Phase 4 begins.

### Weeks 13–16: Phase 4 — LangGraph Integration

| Order | Task | Dependency |
|---|---|---|
| 28 | Configure PostgresSaver; verify checkpoint write/read | Alembic migration applied |
| 29 | Build `InvoiceProcessingGraph` (nodes only, no edges) | All 19 agents complete |
| 30 | Add conditional edges to `InvoiceProcessingGraph` | Nodes working |
| 31 | Build `ExceptionGraph` | `ExceptionAgent` complete |
| 32 | Build `RetryGraph` | `RetryAgent` complete |
| 33 | Build `HumanReviewGraph` + interrupt/resume endpoints | `HumanReviewAgent` complete |
| 34 | Build `ApprovalGraph` + interrupt/resume endpoints | `ApprovalAgent` complete |
| 35 | Build `NotificationGraph` | `NotificationAgent` complete |
| 36 | Build `GraphRegistry`; compile all graphs at startup | All graphs complete |
| 37 | Feature flag `feature.use_langgraph_pipeline` | `FeatureFlagTool` available |
| 38 | Parallel run: LangGraph vs Celery on 10% of test invoices | All graphs + feature flag |
| 39 | Validate output parity; fix divergences | Parallel run results |
| 40 | Full regression suite on LangGraph pipeline | Parallel run validated |
| 41 | Enable `feature.use_langgraph_pipeline = true` in staging | Regression suite passes |
| 42 | Demote Celery to side-task-only; remove pipeline tasks | LangGraph primary |

**Gate**: Zero output differences between LangGraph and Celery pipelines on 100 test invoices.

### Weeks 17–18: Phase 5 — API Migration

| Order | Task |
|---|---|
| 43 | Add `X-Tenant-ID` middleware; default to `"default"` |
| 44 | Implement all 16 new API endpoints (Section 7.4) |
| 45 | Update OpenAPI spec; publish to `/api/docs` |
| 46 | Backward compatibility regression test: all existing endpoints return identical responses |

### Weeks 19–22: Phase 6 — Frontend Migration

| Order | Task |
|---|---|
| 47 | Build shared components: `ConfidenceBadge`, `AgentTimeline`, `WorkflowStatusBanner`, `ExplainabilityDrawer` |
| 48 | Document Detail enhancements (Sprints 1–4) |
| 49 | Workflow Timeline page (new) |
| 50 | AI Confidence Panel (embedded in Document Detail) |
| 51 | Exception Center enhancements |
| 52 | Approval Center enhancements |
| 53 | Audit Trail enhancements |
| 54 | Agent Execution Details view |
| 55 | Admin panel additions (prompt manager, config editor) |

### Weeks 23–24: Phase 7 — Multi-tenancy & Hardening

| Order | Task |
|---|---|
| 56 | Tenant registry table + admin API |
| 57 | Tenant isolation middleware + DB query scoping |
| 58 | Per-tenant config YAML + token budget enforcement |
| 59 | Audit chain integrity + PII masking on all log paths |
| 60 | RBAC hardening + Jinja2 SandboxedEnvironment |
| 61 | Full security review: secret rotation, rate limiting |

### Weeks 25–26: Phase 8 — Azure Deployment

| Order | Task |
|---|---|
| 62 | Azure PostgreSQL Flexible Server: migrate data; test connection |
| 63 | Azure Cache for Redis: update `REDIS_URL`; test Celery connectivity |
| 64 | Azure Blob Storage: activate `AzureBlobStorageTool`; migrate existing files |
| 65 | Azure App Service: deploy FastAPI container; validate health endpoint |
| 66 | Azure Container Apps: deploy Celery worker + Beat |
| 67 | Azure Static Web Apps: deploy Next.js build |
| 68 | Azure Key Vault: migrate secrets; activate `SecretManagerTool` |
| 69 | Azure Front Door: configure routing, SSL, custom domain |
| 70 | Production smoke test: upload invoice → payment scheduled, end-to-end |
| 71 | Disable `LocalStorageTool` in production; verify `storage.allow_local_in_production=false` guard |
| 72 | Verify `erp.allow_mock_in_production=false` guard in production |

---

## 10. Risks & Testing

### 10.1 Risk Register

#### High Risks

| Risk | Description | Probability | Impact | Mitigation |
|---|---|---|---|---|
| `RISK-H1` | ExtractionAgent regression — LLM output format changes during refactoring | Medium | Critical | Run extraction tool on 200 real invoices before and after; compare field-by-field |
| `RISK-H2` | WorkflowState serialisation failure — LangGraph checkpoint write fails on complex nested state | Low | Critical | Test serialisation of maximum-size WorkflowState; add field-size limits in Pydantic validators |
| `RISK-H3` | MATCHING_AGENT split introduces subtle logic gap — three-way match verdict differs from monolith | Medium | High | Parallel run both code paths on same 100 invoices; assert identical disposition |
| `RISK-H4` | PostgreSQL checkpointer lock contention under high concurrent load | Low | High | Load test with 50 concurrent invoices; measure checkpoint write latency |
| `RISK-H5` | Approval polling replaced by LangGraph interrupt — existing frontend polling breaks | Medium | High | Feature-flag the interrupt; keep polling endpoint alive until frontend is migrated |
| `RISK-H6` | ERP mock allowed in production — `erp.allow_mock_in_production` guard bypassed | Low | Critical | Add integration test that asserts the guard halts the `erp_post` node when flag is `true` in prod config |

#### Medium Risks

| Risk | Description | Probability | Impact | Mitigation |
|---|---|---|---|---|
| `RISK-M1` | Pydantic v2 upgrade breaks existing SQLAlchemy model validators | Medium | Medium | Upgrade Pydantic in isolation; run existing model tests; fix before proceeding |
| `RISK-M2` | LangGraph graph routing edge cases — invoice hits unexpected END state | Medium | Medium | Exhaustive edge case tests: all 9 profiles × all failure combinations |
| `RISK-M3` | Token budget enforcement causes invoice processing failure mid-extraction | Low | Medium | Set token budget alert at 80%; hard block at 100%; always allow one full extraction attempt |
| `RISK-M4` | Celery shims introduce duplicate processing (both old and new code runs) | Medium | Medium | Feature flag prevents both from running simultaneously; verified in parallel run phase |
| `RISK-M5` | Azure Blob Storage latency increases document processing time | Low | Medium | Benchmark latency; add async upload with callback to avoid blocking OCR |
| `RISK-M6` | Human review SLA notifications fail silently (NotificationTool failure non-blocking) | Medium | Medium | Add SLA breach detection in Celery Beat as independent safety net |

#### Low Risks

| Risk | Description | Probability | Impact | Mitigation |
|---|---|---|---|---|
| `RISK-L1` | New audit chain hash breaks existing audit log queries | Low | Low | Add `event_chain_hash` as nullable; backfill hash for historical records in migration |
| `RISK-L2` | `RuleEngineTool` YAML syntax errors break profile validation | Low | Low | YAML schema validation on load; CI validates all rule YAMLs |
| `RISK-L3` | `LanguageDetectionTool` misdetects language for multi-language invoices | Low | Low | Default to `"en"` on detection failure; log warning |
| `RISK-L4` | Frontend feature flags not cleared after migration completes | Low | Low | Feature flag cleanup task at end of each phase |

### 10.2 Regression Risk Map

| Migration Step | Regression Risk | Mitigation |
|---|---|---|
| Wrapping `PDFTool` | Low — identical algorithm | Compare page count + text extraction on 50 documents |
| Extracting LLM calls into `ExtractionTool` | High — JSON parsing edge cases | Golden dataset of 100 invoices; assert field-level parity |
| Splitting `MATCHING_AGENT` | High — verdict logic distributed | Parallel run assertion on 100 invoices; identical match scores required |
| Adding `ConfidenceAgent` | None — new capability | Test routing decisions (requires_human_review flag) on known-confidence invoices |
| LangGraph replacing Celery pipeline | High — full pipeline change | Feature flag; parallel run; 100% regression suite before flag flip |
| Adding new DB columns | Low — all nullable with defaults | Existing queries unaffected; verify with read-write test on each table |
| Tenant isolation middleware | Medium — incorrect scoping could filter valid records | Integration test: each tenant sees only their own documents |

### 10.3 Rollback Strategy

**Phase-level rollback** (available for all phases):
- Every phase ends with a tagged Git release (e.g., `v2.0-phase-3-complete`)
- `docker-compose.yml` always reflects a working state at the phase tag
- Alembic rollback scripts exist for every migration (but are not auto-applied)

**Feature flag rollback** (instant, no deployment required):
- `feature.use_langgraph_pipeline = false` → Celery pipeline resumes instantly
- `feature.use_azure_storage = false` → LocalStorageTool resumes
- `feature.use_langgraph_approval = false` → Polling-based approval resumes
- Feature flags are read at runtime from Redis; change takes effect within 30 seconds

**Database rollback**:
- New columns are nullable with defaults → removing them does not break existing code
- New tables can be dropped without affecting existing tables
- LangGraph checkpoint table is separate from all business tables

**Per-tool rollback**:
- Tools are only wired to agents after full unit test pass
- `FeatureFlagTool` gates each tool at the agent level: if a tool fails in staging, the flag is disabled and the legacy code path resumes

### 10.4 Testing Strategy

#### Unit Tests (per tool, per agent)
- Every tool has its own test file in `tests/unit/tools/{category}/`
- Test coverage requirement: 100% for Critical-priority tools; 80% for all others
- Tools are tested in isolation with mock dependencies — no database, no network
- Every test asserts typed input → typed output; no raw dict assertions
- All validation tools tested against a corpus of real and synthetic invoice data

#### Integration Tests (agent + tools)
- Every agent has an integration test in `tests/integration/agents/`
- Integration tests use a real PostgreSQL test database and a real Redis instance
- No mocking of tools within agent integration tests — only external services (ERP, Azure) are mocked
- Each integration test: feed a WorkflowState in → assert the output WorkflowState fields

#### Graph Tests (end-to-end per graph)
- `tests/integration/graphs/test_invoice_processing_graph.py` — one test per business profile (9 tests)
- `tests/integration/graphs/test_exception_graph.py` — one test per exception type and queue
- `tests/integration/graphs/test_human_review_graph.py` — approve, correct, reject, escalate paths
- `tests/integration/graphs/test_approval_graph.py` — single-level, multi-level, delegation, rejection
- `tests/integration/graphs/test_retry_graph.py` — each backoff strategy; exhaustion escalation
- Graphs tested against real PostgresSaver (test DB); no mocks inside graph tests

#### End-to-End Tests (full pipeline)
- `tests/e2e/` contains one test per invoice scenario: digital PO invoice, scanned CAPEX, handwritten non-PO, lease, employee reimbursement
- E2E tests drive the system through the FastAPI upload endpoint → assert payment record created
- Run against staging environment before every production deploy
- E2E test suite must complete in under 10 minutes

#### Parallel Run Validation (Phase 4 specific)
- 100 real historical invoices replayed through both pipelines
- Assertion: `po_match_score`, `grn_match_score`, `validation.is_valid`, `profile.business_profile`, `invoice.total_amount` must be identical between pipelines
- Any divergence blocks the phase gate

#### Performance Tests
- Upload → payment scheduled latency: p50 < 30s, p99 < 120s (current baseline measured before Phase 0)
- Confidence Agent: < 100ms compute time
- LangGraph checkpoint write: < 50ms per node
- Three-way match: < 500ms per invoice
- All LLM calls: p99 < 10s with retry

#### Security Tests
- OWASP Top 10 scan on all new endpoints
- Verify `MaskingTool` prevents PII in logs (test with known PII strings; assert they are masked)
- Verify `erp.allow_mock_in_production=false` guard cannot be bypassed
- Verify cross-tenant isolation: tenant A cannot see tenant B's documents (automated test)
- Verify audit log is truly append-only: attempt UPDATE/DELETE from test user; assert permission error

---

## 11. Definition of Done

The migration is complete when every criterion in this section is satisfied.

### 11.1 Functional Completeness

| Criterion | Verification |
|---|---|
| All 9 business profiles process end-to-end through LangGraph | 9 E2E tests pass |
| Human review interrupt/resume works for all trigger conditions | HumanReviewGraph integration tests pass |
| Multi-level approval works with delegation and SLA escalation | ApprovalGraph integration tests pass |
| All 5 exception queues (AP_TEAM, FINANCE, PROCUREMENT, COMPLIANCE, WAREHOUSE) assignable | ExceptionGraph integration tests pass |
| ERP posting works via MockERPTool; SAP/Oracle/Dynamics/NetSuite stubs are wired but inactive | ERPAdapterTool integration test confirms provider dispatch |
| Payment scheduling with TDS deduction works for all vendor categories | PaymentAgent integration test passes |
| Retry with all 4 backoff strategies works; escalates on exhaustion | RetryGraph integration tests pass |
| Notification dispatches on all configured events | NotificationGraph integration tests pass |

### 11.2 Architecture Compliance

| Criterion | Verification |
|---|---|
| No business logic inside any agent function — all in tools | Code review: grep for direct DB queries / inline calculation in `core/agents/` returns zero results |
| All tools implement `BaseTool` interface with typed Input/Output | mypy passes with strict mode on `core/tools/` |
| All agents implement `BaseAgent` interface | mypy passes on `core/agents/` |
| `WorkflowState` is the only state communication mechanism | No global variables, Redis keys, or direct DB rows passed between agents |
| Every agent node emits at least one audit event | Integration tests assert `audit_logs` row count increases per node execution |
| `erp.allow_mock_in_production=false` guard is enforced | Guard test passes: mock in prod config halts graph with CRITICAL event |
| `storage.allow_local_in_production=false` guard is enforced | Guard test passes |
| All prompts use `SandboxedEnvironment` | `grep -r "jinja2.Environment(" core/` returns zero results; only `SandboxedEnvironment` present |
| No secrets in code | `trufflehog` scan or equivalent on `core/` returns zero findings |
| NEVER log PII | Log audit test: process invoice with known PII fields; assert PII does not appear in log output |

### 11.3 Backward Compatibility

| Criterion | Verification |
|---|---|
| All existing frontend pages work without modification | Manual smoke test of Dashboard, Upload, Documents, Approvals, Exceptions, Admin, Audit pages |
| All preserved API endpoints return identical responses | Backward compatibility regression test suite passes (Section 10.4) |
| Existing `seed/seed.py` still seeds the database correctly | `python seed/seed.py` completes without errors on fresh DB |
| `docker-compose.yml` still starts the full stack for local development | `docker compose up --build -d` succeeds; all health checks pass |

### 11.4 Code Quality

| Criterion | Verification |
|---|---|
| All Critical-priority tools at 100% unit test coverage | `pytest --cov=core/tools --cov-report=term` confirms coverage |
| All agents at ≥ 80% integration test coverage | Coverage report on `core/agents/` |
| All graph conditional edges have explicit tests | One test per edge branch in graph integration tests |
| `mypy` passes with no errors on `core/` | CI mypy step is green |
| `ruff` passes with no warnings on `core/` | CI ruff step is green |
| No `TODO` or `FIXME` comments in `core/` | `grep -r "TODO\|FIXME" core/` returns zero results |

### 11.5 Performance

| Criterion | Measurement |
|---|---|
| Invoice processing latency p50 ≤ baseline | Benchmark test against pre-migration baseline |
| Invoice processing latency p99 < 120 seconds | Load test with 50 concurrent invoices |
| LangGraph checkpoint write < 50ms p99 | Instrumented test |
| Confidence agent compute time < 100ms | Unit benchmark |
| No memory leak under 1-hour sustained load | 1-hour soak test; memory stable |

### 11.6 Security

| Criterion | Verification |
|---|---|
| OWASP Top 10 scan clean on all new endpoints | OWASP ZAP or equivalent scan report |
| Cross-tenant isolation enforced | Automated isolation test (Section 10.4) passes |
| Audit log append-only enforced at DB level | DB permission test passes |
| PII never appears in application logs | Log audit test passes |
| All secrets loaded from Key Vault in production | `SecretManagerTool` integration test on staging |

### 11.7 Documentation

| Criterion | Verification |
|---|---|
| `ARCHITECTURE.md` accurately reflects final implemented structure | Reviewed and signed off |
| `tools.md` matches all 112 implemented tools | Tool list reconciled against `core/tools/` |
| `agents.md` matches all 19 implemented agents | Agent list reconciled against `core/agents/` |
| `graphs.md` matches all 6 implemented graphs | Graph list reconciled against `core/graphs/` |
| `implementation.md` (this document) marks all phases complete | All phase gates checked |
| OpenAPI spec is up to date | `/api/docs` reflects all implemented endpoints |
| `CONTRIBUTING.md` covers tool creation, agent creation, graph modification | Content reviewed |

### 11.8 Deployment

| Criterion | Verification |
|---|---|
| All Azure resources provisioned via IaC (Bicep/Terraform) | `infra/` directory contains complete IaC; `az deployment` succeeds |
| Staging environment mirrors production configuration | Config diff between staging and prod shows only connection strings differ |
| Production deploy completes with zero downtime | Blue-green deploy; no 5xx errors during deploy |
| Rollback tested: feature flag disables LangGraph in < 30 seconds | Timed rollback drill performed |
| Monitoring and alerting configured | Azure Monitor alerts for: invoice processing latency p99, exception SLA breach rate, error rate, checkpoint write failures |

---

*End of implementation.md — Enterprise AI Agent Platform Migration Blueprint*
*Phase completion tracker: Phase 0 ☐ | Phase 1 ☐ | Phase 2 ☐ | Phase 3 ☐ | Phase 4 ☐ | Phase 5 ☐ | Phase 6 ☐ | Phase 7 ☐ | Phase 8 ☐*

