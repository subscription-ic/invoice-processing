# AI Agent Platform — Enterprise Architecture Document

**Version:** 1.0.0
**Status:** Architecture Design Phase
**Prepared for:** AP Automation Platform → Reusable Enterprise AI Agent Platform
**Date:** 2026-06-09
**Architect:** Principal Enterprise AI Architect

---

## EXECUTIVE SUMMARY

This document redesigns the existing invoice-processing application into a **configuration-driven, multi-tenant AI Agent Platform** that can be demonstrated to any enterprise client with approximately **20% customization effort**. The existing workflow is preserved exactly. All 12 agents are retained. Only the architectural layering, separation of concerns, and deployment topology are redesigned. The platform eliminates Docker in favour of **Azure-native services** (Azure App Service, Azure Container Apps, Azure Functions, Azure Service Bus, Azure Blob Storage, Azure Database for PostgreSQL Flexible Server).

---

## SECTION 1 — Overall System Architecture

### 1.1 Layered Architecture Overview

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                         BROWSER / EXTERNAL CLIENTS                              ║
║              (Next.js SPA · Mobile PWA · API Clients · Email Ingest)            ║
╚══════════════════════════╤═══════════════════════════════════════════════════════╝
                           │  HTTPS / REST / WebSocket / SSE
╔══════════════════════════▼═══════════════════════════════════════════════════════╗
║                        NEXT.JS FRONTEND LAYER                                   ║
║   Pages: Dashboard · Upload · Documents · Approvals · Exceptions · Admin        ║
║   State: Zustand   API Client: React Query + Axios   UI: MUI + AG Grid          ║
║   RULE: Never calls agents directly. Only calls FastAPI REST endpoints.         ║
╚══════════════════════════╤═══════════════════════════════════════════════════════╝
                           │  REST / JSON over HTTPS
╔══════════════════════════▼═══════════════════════════════════════════════════════╗
║                        FASTAPI API GATEWAY LAYER                                ║
║   Routers: /documents · /workflows · /approvals · /exceptions · /audit          ║
║            /vendors · /po · /grn · /config · /analytics · /notifications        ║
║   Responsibilities:                                                              ║
║     · Authentication + Authorization (JWT + RBAC)                               ║
║     · Request validation (Pydantic schemas)                                     ║
║     · Enqueue work to Celery / Service Bus                                      ║
║     · Poll and return WorkflowState                                              ║
║     · WebSocket / SSE for real-time status updates                              ║
║   RULE: FastAPI never calls agents. It only manages queues and reads state.     ║
╚══════════════════════════╤═══════════════════════════════════════════════════════╝
                           │  Task Dispatch (Celery / Azure Service Bus)
╔══════════════════════════▼═══════════════════════════════════════════════════════╗
║                     ORCHESTRATION LAYER — LANGGRAPH                             ║
║   Graphs: InvoiceProcessingGraph · ApprovalGraph · ExceptionGraph               ║
║           HumanReviewGraph · RetryGraph · NotificationGraph                     ║
║   Responsibilities:                                                              ║
║     · Owns the complete workflow state machine                                  ║
║     · Routes between agents using conditional edges                             ║
║     · Handles human-in-the-loop interrupts                                      ║
║     · Supports resume, retry, rollback                                          ║
║     · Persists checkpoints to PostgreSQL (LangGraph checkpointer)              ║
╚══════════════════════════╤═══════════════════════════════════════════════════════╝
                           │  WorkflowState passed through graph nodes
╔══════════════════════════▼═══════════════════════════════════════════════════════╗
║                         AGENT LAYER (19 Agents)                                 ║
║   Each agent:                                                                   ║
║     1. Receives WorkflowState                                                   ║
║     2. Calls reusable Tools (never direct DB, never direct LLM)                 ║
║     3. Updates its own WorkflowState section                                    ║
║     4. Returns WorkflowState                                                    ║
║   Agents contain ZERO business logic — only orchestration calls.                ║
╚══════════════════════════╤═══════════════════════════════════════════════════════╝
                           │  Tool invocations
╔══════════════════════════▼═══════════════════════════════════════════════════════╗
║                    REUSABLE TOOL LAYER (40+ Tools)                              ║
║   ALL business logic lives here.                                                ║
║   Tools are: stateless · independently testable · provider-agnostic            ║
║   Categories: Document · OCR · Extraction · Validation · Matching               ║
║               Financial · Compliance · ERP · Notification · Audit               ║
╚══════════════════════════╤═══════════════════════════════════════════════════════╝
                           │  Repository pattern
╔══════════════════════════▼═══════════════════════════════════════════════════════╗
║                      REPOSITORY LAYER                                           ║
║   One repository per domain aggregate.                                          ║
║   Tools never touch SQLAlchemy directly — always via repository.                ║
║   Repositories: DocumentRepo · WorkflowRepo · VendorRepo · PORepo               ║
║                 GRNRepo · ApprovalRepo · ExceptionRepo · AuditRepo              ║
║                 ConfigRepo · PromptRepo · NotificationRepo · UserRepo           ║
╚══════════════════════════╤═══════════════════════════════════════════════════════╝
                           │  SQLAlchemy ORM
╔══════════════════════════▼═══════════════════════════════════════════════════════╗
║                    PERSISTENCE + EXTERNAL SERVICES LAYER                        ║
║                                                                                 ║
║  ┌─────────────────────┐  ┌───────────────┐  ┌─────────────────────────────┐  ║
║  │  Azure PostgreSQL   │  │  Azure Blob   │  │   Azure Redis Cache         │  ║
║  │  Flexible Server    │  │  Storage      │  │   (Celery broker + results) │  ║
║  │  (primary DB +      │  │  (documents,  │  │                             │  ║
║  │   LangGraph state)  │  │   exports)    │  └─────────────────────────────┘  ║
║  └─────────────────────┘  └───────────────┘                                   ║
║  ┌─────────────────────┐  ┌───────────────┐  ┌─────────────────────────────┐  ║
║  │  Azure Service Bus  │  │  Azure AI     │  │   External: OpenAI / Azure  │  ║
║  │  (async queuing)    │  │  Document Int.│  │   OpenAI / Tesseract        │  ║
║  └─────────────────────┘  └───────────────┘  └─────────────────────────────┘  ║
╚══════════════════════════════════════════════════════════════════════════════════╝
```

### 1.2 Layer Responsibility Table

| Layer | Owns | Does NOT Own |
|---|---|---|
| Frontend | UI state, user interactions | Business logic, agent calls |
| FastAPI | API contracts, auth, queue dispatch | Workflow logic, DB queries |
| LangGraph | Graph execution, state machine, routing | Business rules |
| Agents | Tool orchestration, state updates | Business logic, direct DB access |
| Tools | Business logic, provider adapters | State management, DB access |
| Repositories | Data access patterns, queries | Business rules |
| Database | Persistence, consistency | Any processing |

---

## SECTION 2 — Project Folder Structure

```
invoice-p2p/
│
├── backend/
│   └── app/
│       │
│       ├── agents/                     # 19 Agent classes — NO business logic
│       │   ├── base_agent.py           # Abstract BaseAgent (receive→tools→update→return)
│       │   ├── upload_agent.py
│       │   ├── classification_agent.py
│       │   ├── ocr_agent.py
│       │   ├── extraction_agent.py
│       │   ├── universal_validation_agent.py
│       │   ├── business_profile_agent.py
│       │   ├── profile_validation_agent.py
│       │   ├── vendor_matching_agent.py
│       │   ├── duplicate_detection_agent.py
│       │   ├── tax_validation_agent.py
│       │   ├── po_matching_agent.py
│       │   ├── confidence_agent.py
│       │   ├── decision_agent.py
│       │   ├── exception_agent.py
│       │   ├── approval_agent.py
│       │   ├── erp_posting_agent.py
│       │   ├── payment_agent.py
│       │   ├── notification_agent.py
│       │   └── audit_agent.py
│       │
│       ├── graphs/                     # LangGraph graph definitions ONLY
│       │   ├── invoice_processing_graph.py
│       │   ├── exception_graph.py
│       │   ├── approval_graph.py
│       │   ├── human_review_graph.py
│       │   ├── retry_graph.py
│       │   ├── notification_graph.py
│       │   └── graph_registry.py      # Maps workflow_type → graph
│       │
│       ├── tools/                     # ALL business logic lives here
│       │   ├── document/
│       │   │   ├── pdf_tool.py
│       │   │   ├── image_tool.py
│       │   │   ├── file_tool.py
│       │   │   ├── metadata_tool.py
│       │   │   └── virus_scan_tool.py
│       │   ├── ocr/
│       │   │   ├── ocr_tool.py        # Provider-agnostic interface
│       │   │   ├── tesseract_provider.py
│       │   │   └── azure_di_provider.py  # plug in later
│       │   ├── extraction/
│       │   │   ├── extraction_tool.py
│       │   │   ├── normalization_tool.py
│       │   │   └── prompt_tool.py
│       │   ├── validation/
│       │   │   ├── validation_tool.py
│       │   │   ├── gst_tool.py
│       │   │   ├── pan_tool.py
│       │   │   ├── tax_validation_tool.py
│       │   │   ├── business_rule_tool.py
│       │   │   └── arithmetic_tool.py
│       │   ├── matching/
│       │   │   ├── vendor_tool.py
│       │   │   ├── po_tool.py
│       │   │   ├── grn_tool.py
│       │   │   ├── matching_tool.py
│       │   │   ├── comparison_tool.py
│       │   │   └── duplicate_tool.py
│       │   ├── financial/
│       │   │   ├── currency_tool.py
│       │   │   ├── confidence_tool.py
│       │   │   └── tds_tool.py
│       │   ├── storage/
│       │   │   ├── storage_tool.py    # Provider-agnostic interface
│       │   │   ├── local_provider.py
│       │   │   └── azure_blob_provider.py
│       │   ├── erp/
│       │   │   ├── erp_tool.py        # Provider-agnostic interface
│       │   │   ├── mock_erp_provider.py
│       │   │   ├── sap_provider.py    # stub
│       │   │   └── oracle_provider.py # stub
│       │   ├── notification/
│       │   │   ├── notification_tool.py
│       │   │   ├── email_provider.py
│       │   │   └── teams_provider.py  # future
│       │   ├── approval/
│       │   │   ├── approval_tool.py
│       │   │   └── approval_matrix_tool.py
│       │   ├── exception/
│       │   │   ├── exception_tool.py
│       │   │   └── exception_registry.py
│       │   └── platform/
│       │       ├── hash_tool.py
│       │       ├── audit_tool.py
│       │       ├── logging_tool.py
│       │       ├── retry_tool.py
│       │       ├── queue_tool.py
│       │       ├── configuration_tool.py
│       │       ├── database_tool.py
│       │       ├── user_tool.py
│       │       ├── timeline_tool.py
│       │       ├── analytics_tool.py
│       │       └── prompt_version_tool.py
│       │
│       ├── schemas/                   # Pydantic models — request/response contracts
│       │   ├── workflow_state.py      # THE central WorkflowState object
│       │   ├── document_schema.py
│       │   ├── extraction_schema.py
│       │   ├── validation_schema.py
│       │   ├── matching_schema.py
│       │   ├── approval_schema.py
│       │   ├── exception_schema.py
│       │   ├── erp_schema.py
│       │   ├── audit_schema.py
│       │   └── api_schemas.py         # HTTP request/response bodies
│       │
│       ├── repositories/              # Data access — one file per aggregate
│       │   ├── base_repository.py
│       │   ├── document_repository.py
│       │   ├── workflow_repository.py
│       │   ├── vendor_repository.py
│       │   ├── po_repository.py
│       │   ├── grn_repository.py
│       │   ├── approval_repository.py
│       │   ├── exception_repository.py
│       │   ├── audit_repository.py
│       │   ├── config_repository.py
│       │   ├── prompt_repository.py
│       │   ├── notification_repository.py
│       │   └── user_repository.py
│       │
│       ├── api/                       # FastAPI routers ONLY — no logic
│       │   ├── v1/
│       │   │   ├── documents.py       # /api/v1/documents/{document_id}
│       │   │   ├── workflows.py       # /api/v1/workflows/{workflow_id}
│       │   │   ├── approvals.py       # /api/v1/approvals/{approval_id}
│       │   │   ├── exceptions.py      # /api/v1/exceptions/{exception_id}
│       │   │   ├── vendors.py         # /api/v1/vendors/{vendor_id}
│       │   │   ├── po.py              # /api/v1/po/{po_id}
│       │   │   ├── grn.py             # /api/v1/grn/{grn_id}
│       │   │   ├── audit.py           # /api/v1/audit/{document_id}
│       │   │   ├── analytics.py       # /api/v1/analytics/...
│       │   │   ├── notifications.py   # /api/v1/notifications/...
│       │   │   ├── config.py          # /api/v1/config/...
│       │   │   └── health.py          # /api/v1/health
│       │   └── router.py              # Assembles all v1 routers
│       │
│       ├── models/                    # SQLAlchemy ORM models
│       │   ├── base.py
│       │   ├── document_models.py
│       │   ├── workflow_models.py
│       │   ├── vendor_models.py
│       │   ├── approval_models.py
│       │   ├── exception_models.py
│       │   ├── audit_models.py
│       │   ├── config_models.py
│       │   ├── prompt_models.py
│       │   └── user_models.py
│       │
│       ├── prompts/                   # Versioned prompt registry
│       │   ├── registry/
│       │   │   ├── classification/
│       │   │   │   ├── v1.yaml
│       │   │   │   └── v2.yaml
│       │   │   ├── extraction/
│       │   │   │   ├── v1.yaml
│       │   │   │   └── v2.yaml
│       │   │   ├── business_profile/
│       │   │   ├── validation/
│       │   │   └── decision/
│       │   └── loader.py              # PromptLoader — loads by agent + version
│       │
│       ├── config/                    # All configuration
│       │   ├── settings.py            # Pydantic BaseSettings (env vars)
│       │   ├── business_rules.yaml    # Validation rules per profile
│       │   ├── approval_matrix.yaml   # Approval rules
│       │   ├── confidence_config.yaml # Thresholds per stage
│       │   ├── country_config.yaml    # Country-specific tax/compliance
│       │   ├── tolerance_config.yaml  # Matching tolerances
│       │   └── provider_config.yaml   # LLM, OCR, Storage, ERP providers
│       │
│       ├── services/                  # Provider adapters (infrastructure concern)
│       │   ├── llm_service.py         # OpenAI / Azure OpenAI adapter
│       │   ├── ocr_service.py         # Tesseract / Azure DI adapter
│       │   ├── storage_service.py     # Local / Azure Blob adapter
│       │   ├── erp_service.py         # Mock / SAP / Oracle adapter
│       │   └── queue_service.py       # Celery / Azure Service Bus adapter
│       │
│       ├── tasks/                     # Celery task definitions
│       │   ├── pipeline_tasks.py      # Triggers LangGraph graphs
│       │   └── scheduled_tasks.py     # SLA checks, cleanup, reports
│       │
│       ├── shared/                    # Cross-cutting, no dependencies on above
│       │   ├── constants.py
│       │   ├── enums.py
│       │   └── types.py
│       │
│       ├── utils/                     # Pure utility functions (no I/O)
│       │   ├── date_utils.py
│       │   ├── string_utils.py
│       │   ├── number_utils.py
│       │   └── crypto_utils.py
│       │
│       ├── exceptions/                # Custom exception hierarchy
│       │   ├── base_exception.py
│       │   ├── validation_exceptions.py
│       │   ├── agent_exceptions.py
│       │   ├── erp_exceptions.py
│       │   └── auth_exceptions.py
│       │
│       ├── audit/                     # Audit event system
│       │   ├── audit_event.py         # AuditEvent schema
│       │   ├── audit_writer.py        # Writes to audit_log table
│       │   └── audit_middleware.py    # FastAPI middleware
│       │
│       ├── storage/                   # Storage abstraction
│       │   ├── base_storage.py
│       │   ├── local_storage.py
│       │   └── azure_blob_storage.py
│       │
│       ├── notifications/             # Notification engine
│       │   ├── notification_router.py
│       │   ├── email_channel.py
│       │   └── teams_channel.py
│       │
│       ├── logging/                   # Structured logging
│       │   ├── structured_logger.py
│       │   ├── agent_logger.py
│       │   └── log_schemas.py
│       │
│       └── main.py                    # FastAPI app entry point
│
├── frontend/                          # Next.js — unchanged structure
│   └── src/
│       ├── pages/
│       ├── components/
│       ├── api/
│       └── store/
│
├── alembic/                           # DB migrations
│   └── versions/
│
├── seed/
│   └── seed.py
│
├── tests/
│   ├── unit/tools/                    # One test file per tool
│   ├── unit/agents/
│   ├── integration/
│   └── e2e/
│
├── azure/                             # Azure deployment manifests
│   ├── bicep/                         # Infrastructure as Code
│   │   ├── main.bicep
│   │   ├── app_service.bicep
│   │   ├── database.bicep
│   │   ├── redis.bicep
│   │   ├── service_bus.bicep
│   │   └── blob_storage.bicep
│   └── pipelines/
│       ├── backend-deploy.yml
│       └── frontend-deploy.yml
│
├── .env.example
└── requirements.txt
```

### 2.1 Folder Responsibility Summary

| Folder | Responsibility | Owns | Does NOT Own |
|---|---|---|---|
| `agents/` | Orchestrate tool calls | Tool sequencing, state updates | Business logic |
| `graphs/` | LangGraph state machines | Node/edge definitions, routing | Agent logic |
| `tools/` | All business logic | Rules, calculations, provider calls | State, DB access |
| `schemas/` | Data contracts | Shape of data in/out | Validation logic |
| `repositories/` | Data access | SQL queries, ORM mapping | Business rules |
| `api/` | HTTP contracts | Routes, auth, request parsing | Workflow logic |
| `models/` | DB schema | SQLAlchemy table definitions | Business logic |
| `prompts/` | Prompt versions | YAML prompt files, versioning | LLM calls |
| `config/` | Configuration | YAML/env config files | Code logic |
| `services/` | Infrastructure adapters | Provider switching | Business logic |
| `tasks/` | Async job definitions | Celery task wrappers | Workflow logic |
| `shared/` | Cross-cutting constants | Enums, types, constants | Nothing else |
| `utils/` | Pure functions | Stateless string/date/number utils | I/O of any kind |
| `exceptions/` | Error taxonomy | Custom exception classes | Error handling logic |
| `audit/` | Audit trail | Writing audit events | Business decisions |
| `storage/` | File I/O abstraction | Provider-agnostic file ops | Document logic |
| `notifications/` | Message delivery | Channel routing | Notification triggers |
| `logging/` | Structured logs | Log schemas, emitters | Business logic |

---

## SECTION 3 — LangGraph Design

### 3.1 Graph Registry

```
GraphRegistry
    ├── invoice_processing    → InvoiceProcessingGraph
    ├── exception_handling    → ExceptionGraph
    ├── approval_routing      → ApprovalGraph
    ├── human_review          → HumanReviewGraph
    ├── retry_pipeline        → RetryGraph
    └── notification_dispatch → NotificationGraph
```

### 3.2 Graph 1: InvoiceProcessingGraph

```
[START]
   │
   ▼
[upload_node]────────── FAIL ──────────────────────────────► [exception_node]
   │                                                               │
 PASS                                                          [END: FAILED]
   │
   ▼
[classification_node]── FAIL ──────────────────────────────► [exception_node]
   │
 PASS (DIGITAL / SCANNED / HANDWRITTEN)
   │
   ▼
[ocr_node]─────────────── LOW_QUALITY ────────────────────► [human_review_interrupt]
   │                                                               │
 PASS                                                         RESUME (human fixes)
   │◄─────────────────────────────────────────────────────────────┘
   ▼
[extraction_node]
   │
   ▼
[universal_validation_node]
   │
   ├── HARD_FAIL (missing mandatory fields) ──────────────► [exception_node]
   │
   └── SOFT_FAIL / PASS
              │
              ▼
        [business_profile_node]
              │
              ▼
        [profile_validation_node]
              │
              ├── FAIL ──────────────────────────────────► [exception_node]
              │
              └── PASS
                     │
                     ▼
              [vendor_matching_node]
                     │
                     ├── NO_MATCH ──────────────────────► [human_review_interrupt]
                     │                                         │
                     └── MATCHED                          RESUME (human resolves)
                            │◄────────────────────────────────┘
                            ▼
                     [duplicate_detection_node]
                            │
                            ├── DUPLICATE ──────────────► [exception_node]
                            │
                            └── UNIQUE
                                   │
                                   ▼
                            [tax_validation_node]
                                   │
                                   ├── FAIL ────────────► [exception_node]
                                   │
                                   └── PASS
                                          │
                                          ▼
                                   [po_matching_node]
                                          │
                                          ├── NO_PO (NON_PO profiles) → skip
                                          │
                                          └── PO_FOUND
                                                 │
                                                 ▼
                                          [confidence_node]
                                                 │
                                                 ▼
                                          [decision_node]
                                                 │
                                         ┌───────┴────────────┐
                                         │                    │
                                   AUTO_APPROVE         NEEDS_APPROVAL
                                         │                    │
                                         ▼                    ▼
                                  [erp_posting_node]   [approval_node]
                                         ▲                    │
                                         │               ┌────┴────┐
                                         │            APPROVED   REJECTED
                                         │               │         │
                                         └───────────────┘    [exception_node]
                                                 │
                                                 ▼
                                          [payment_node]
                                                 │
                                                 ▼
                                          [notification_node]
                                                 │
                                                 ▼
                                          [audit_node]
                                                 │
                                                 ▼
                                              [END: COMPLETED]
```

**Node Definitions:**

| Node Name | Agent Called | State Section Updated | Conditional Routing |
|---|---|---|---|
| `upload_node` | UploadAgent | `document`, `metadata` | PASS / FAIL |
| `classification_node` | ClassificationAgent | `classification` | DIGITAL / SCANNED / HANDWRITTEN / FAIL |
| `ocr_node` | OCRAgent | `ocr` | PASS / LOW_QUALITY / FAIL |
| `extraction_node` | ExtractionAgent | `extraction` | PASS / PARTIAL / FAIL |
| `universal_validation_node` | UniversalValidationAgent | `validation` | PASS / SOFT_FAIL / HARD_FAIL |
| `business_profile_node` | BusinessProfileAgent | `business_profile` | 9 profile types |
| `profile_validation_node` | ProfileValidationAgent | `validation.profile` | PASS / FAIL |
| `vendor_matching_node` | VendorMatchingAgent | `matching.vendor` | MATCHED / NO_MATCH |
| `duplicate_detection_node` | DuplicateDetectionAgent | `matching.duplicate` | UNIQUE / DUPLICATE |
| `tax_validation_node` | TaxValidationAgent | `validation.tax` | PASS / FAIL |
| `po_matching_node` | POMatchingAgent | `matching.po_grn` | MATCHED / TOLERANCE / NO_MATCH / SKIP |
| `confidence_node` | ConfidenceAgent | `confidence` | HIGH / MEDIUM / LOW |
| `decision_node` | DecisionAgent | `decision` | AUTO_APPROVE / NEEDS_APPROVAL / REJECT |
| `exception_node` | ExceptionAgent | `exceptions` | RESOLVED / PENDING |
| `approval_node` | ApprovalAgent | `approval` | APPROVED / REJECTED / PENDING |
| `erp_posting_node` | ERPPostingAgent | `erp` | POSTED / FAILED |
| `payment_node` | PaymentAgent | `erp.payment` | SCHEDULED / FAILED |
| `notification_node` | NotificationAgent | `notifications` | SENT / FAILED |
| `audit_node` | AuditAgent | `audit` | always PASS |

### 3.3 Graph 2: ExceptionGraph

```
[START: exception triggered]
        │
        ▼
[classify_exception_node]
        │
        ├── AUTO_RESOLVABLE ─────► [auto_resolve_node] ──► [resume_pipeline_node]
        │
        ├── NEEDS_HUMAN ─────────► [assign_exception_node]
        │                                  │
        │                          [notify_team_node]
        │                                  │
        │                          [await_resolution_interrupt]  ← human acts
        │                                  │
        │                          [validate_resolution_node]
        │                                  │
        │                          [resume_pipeline_node]
        │
        └── TERMINAL_FAILURE ─────► [close_rejected_node]
                                           │
                                        [END: REJECTED]
```

### 3.4 Graph 3: ApprovalGraph

```
[START: document needs approval]
        │
        ▼
[load_approval_matrix_node]
        │
        ▼
[determine_approval_levels_node]
        │
   ┌────┴──────────────────────┐
   │                           │
SINGLE_LEVEL              MULTI_LEVEL
   │                           │
   ▼                           ▼
[send_to_approver_node]   [send_level_1_node]
   │                           │
[await_interrupt]         [await_interrupt]
   │                           │
APPROVED/REJECTED         APPROVED → [send_level_2_node] → ... → [send_level_N_node]
   │                      REJECTED → [return_rejected_node]
   ▼
[finalize_approval_node]
        │
        ▼
     [END]
```

### 3.5 Graph 4: HumanReviewGraph

```
[START: human review needed]
        │
        ▼
[prepare_review_package_node]   ← assembles context, evidence, recommendations
        │
        ▼
[assign_reviewer_node]          ← picks reviewer based on exception type + role
        │
        ▼
[notify_reviewer_node]          ← email / Teams notification with deep link
        │
        ▼
[await_human_decision_interrupt] ← LangGraph interrupt() — awaits human input
        │
        ▼ (human submits decision via API)
[record_decision_node]           ← captures: who, what decision, evidence, timestamp
        │
        ▼
[resume_main_graph_node]         ← injects result back into InvoiceProcessingGraph
        │
        ▼
     [END]
```

### 3.6 Graph 5: RetryGraph

```
[START: agent failure detected]
        │
        ▼
[evaluate_retry_eligibility_node]
        │
        ├── RETRY_ALLOWED (count < max) ──► [apply_backoff_node]
        │                                          │
        │                                   [re_invoke_agent_node]
        │                                          │
        │                                   back to main graph node
        │
        └── MAX_RETRIES_EXCEEDED ──────────► [escalate_exception_node]
```

### 3.7 Graph 6: NotificationGraph

```
[START: notification event emitted]
        │
        ▼
[load_notification_template_node]
        │
        ▼
[resolve_recipients_node]
        │
        ▼
[fan_out_channels_node]          ← parallel dispatch
        │
   ┌────┼────┬────┐
   ▼    ▼    ▼    ▼
email teams sms  webhook
   │    │    │    │
   └────┴────┴────┘
        │
[record_notification_node]
        │
     [END]
```

### 3.8 Human-in-the-Loop Design

LangGraph's `interrupt()` primitive is used for all human decision points.

```
When interrupt is raised:
  1. LangGraph checkpoints the full WorkflowState to PostgreSQL
  2. FastAPI exposes the pending state at: GET /api/v1/workflows/{id}/pending-action
  3. Human reviews via UI and submits decision: POST /api/v1/workflows/{id}/resume
  4. FastAPI calls graph.update_state() + graph.invoke(config, input=None)
  5. LangGraph resumes from the exact checkpoint — no data loss
```

**Resume Logic ensures:**
- State is never reprocessed from scratch
- Every human action is audit-logged with timestamp, user_id, decision, rationale
- SLA clock is paused while awaiting human input
- Deep link in notification routes directly to the review screen

---

## SECTION 4 — Workflow State

### 4.1 Central WorkflowState Object

This is the **single source of truth** passed through every graph node. Every agent updates only its designated section.

```
WorkflowState:
  │
  ├── # IDENTITY
  ├── workflow_id: UUID
  ├── document_id: UUID
  ├── tenant_id: str
  ├── correlation_id: str
  ├── version: int
  │
  ├── # DOCUMENT
  ├── document:
  │     ├── file_name, file_path, file_size_bytes, mime_type
  │     ├── sha256_hash, page_count, upload_timestamp
  │     ├── uploaded_by, virus_scan_result
  │
  ├── # CLASSIFICATION
  ├── classification:
  │     ├── document_type: DIGITAL / SCANNED / HANDWRITTEN
  │     ├── image_quality_score: float (0.0–1.0)
  │     ├── ocr_strategy, confidence, explanation
  │
  ├── # OCR
  ├── ocr:
  │     ├── raw_text, structured_blocks: List[TextBlock]
  │     ├── ocr_provider_used, processing_time_ms
  │     ├── quality_warnings, confidence
  │
  ├── # EXTRACTION
  ├── extraction:
  │     ├── invoice_number, invoice_date
  │     ├── vendor_name, vendor_gstin, vendor_pan
  │     ├── buyer_name, buyer_gstin
  │     ├── line_items: List[LineItem]
  │     ├── subtotal, tax_amount, total_amount, currency
  │     ├── payment_terms, due_date, po_reference
  │     ├── prompt_version_used, model_used, tokens_used
  │     └── extraction_confidence
  │
  ├── # VALIDATION
  ├── validation:
  │     ├── universal:
  │     │     ├── gst_valid, pan_valid, arithmetic_valid
  │     │     ├── mandatory_fields_present
  │     │     ├── results: List[ValidationResult]
  │     │     └── overall_status: PASS / SOFT_FAIL / HARD_FAIL
  │     ├── profile:
  │     │     ├── rules_applied, results, overall_status
  │     └── tax:
  │           ├── tds_applicable, tds_rate, gstin_verified
  │           └── results: List[ValidationResult]
  │
  ├── # BUSINESS PROFILE
  ├── business_profile:
  │     ├── detected_profile: one of 9 profiles
  │     ├── detection_method: AI / RULE / HYBRID
  │     ├── profile_rules_version, confidence, explanation
  │
  ├── # MATCHING
  ├── matching:
  │     ├── vendor:
  │     │     ├── matched_vendor_id, match_method, match_score, match_evidence
  │     ├── duplicate:
  │     │     ├── is_duplicate, duplicate_of, similarity_score, compared_fields
  │     └── po_grn:
  │           ├── po_id, grn_ids, match_type
  │           ├── quantity_variance, value_variance, within_tolerance
  │           └── match_details: List[MatchDetail]
  │
  ├── # CONFIDENCE
  ├── confidence:
  │     ├── overall_score: float (0.0–1.0)
  │     ├── per_stage_scores: dict
  │     ├── confidence_tier: HIGH / MEDIUM / LOW
  │     └── factors: List[ConfidenceFactor]
  │
  ├── # DECISION
  ├── decision:
  │     ├── decision: AUTO_APPROVE / NEEDS_APPROVAL / REJECT
  │     ├── decision_reason, rules_triggered
  │     ├── amount_threshold_applied, escalation_reason
  │
  ├── # EXCEPTIONS
  ├── exceptions:
  │     ├── has_exceptions: bool
  │     ├── exception_list: List[ExceptionRecord]
  │     └── resolution_status
  │
  ├── # APPROVAL
  ├── approval:
  │     ├── approval_matrix_version, required_levels, current_level
  │     ├── approvals: List[ApprovalRecord]
  │     └── final_status
  │
  ├── # ERP
  ├── erp:
  │     ├── erp_provider, posting_status
  │     ├── erp_document_number, erp_posting_timestamp
  │     └── payment:
  │           ├── due_date, gross_amount, tds_deducted
  │           ├── net_payable, payment_method, payment_status
  │
  ├── # AUDIT
  ├── audit:
  │     └── events: List[AuditEvent]
  │
  ├── # EXECUTION METADATA
  ├── execution:
  │     ├── current_stage, current_agent, next_action
  │     ├── processing_started_at, processing_completed_at
  │     ├── total_processing_time_ms, stage_timings: dict
  │     ├── retry_count, retry_history: List[RetryRecord]
  │     ├── human_review_status
  │     ├── human_review_requested_at, human_review_resolved_at
  │     ├── pipeline_version
  │     └── execution_history: List[ExecutionStep]
  │
  └── # NOTIFICATIONS
      notifications:
            ├── events_sent: List[NotificationRecord]
            └── pending_events: List[str]
```

---

## SECTION 5 — Agent Architecture

### 5.1 BaseAgent Contract

```
BaseAgent (abstract):
  method: execute(state: WorkflowState) → WorkflowState
  method: handle_failure(state, error) → WorkflowState
  method: log_execution(state, result) → None
  method: write_audit(state, before, after) → None
  method: calculate_confidence(results) → float
  method: should_escalate(state) → bool
```

No agent is permitted to call the database directly, call OpenAI directly, read another agent's state section, or raise unhandled exceptions to the graph.

### 5.2 Agent Specifications

#### Agent 1: UploadAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Validate, store, and register incoming documents |
| **Inputs** | `state.document` (file_path, file_name, mime_type) |
| **Outputs** | `state.document` (sha256_hash, blob_path, virus_scan_result, page_count) |
| **Tools Used** | `FileTool`, `StorageTool`, `HashTool`, `VirusScanTool`, `MetadataTool` |
| **Failure Handling** | Unsupported format → HARD_FAIL; Virus found → QUARANTINE; Storage failure → retry 3× |
| **Retry Logic** | 3 retries with exponential backoff for storage errors |
| **Confidence** | Binary: stored = 1.0, failed = 0.0 |
| **Human Escalation** | Only on virus detection |
| **Audit Events** | DOCUMENT_RECEIVED, DOCUMENT_STORED, VIRUS_DETECTED |

#### Agent 2: ClassificationAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Determine document type and select appropriate OCR strategy |
| **Inputs** | `state.document.blob_path` |
| **Outputs** | `state.classification` (document_type, ocr_strategy, image_quality_score) |
| **Tools Used** | `PDFTool`, `ImageTool`, `PromptTool` |
| **Failure Handling** | Unrecognised document → SOFT_FAIL, classify as UNKNOWN |
| **Retry Logic** | 2 retries on LLM timeout |
| **Confidence** | LLM confidence + image quality score |
| **Human Escalation** | image_quality_score < 0.3 AND LLM confidence < 0.6 |
| **Audit Events** | CLASSIFICATION_COMPLETED |

#### Agent 3: OCRAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Extract raw text using strategy selected by ClassificationAgent |
| **Inputs** | `state.classification.ocr_strategy`, `state.document.blob_path` |
| **Outputs** | `state.ocr` (raw_text, structured_blocks, provider_used) |
| **Tools Used** | `OCRTool` (dispatches to Tesseract or Azure DI based on config), `ImageTool` |
| **Failure Handling** | OCR error → retry alternate provider; empty text → escalate |
| **Retry Logic** | 3 retries, then alternate provider, then human review |
| **Confidence** | Word confidence scores averaged from provider |
| **Human Escalation** | OCR output empty or confidence below threshold |
| **Audit Events** | OCR_COMPLETED, OCR_QUALITY_WARNING |

#### Agent 4: ExtractionAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Extract structured invoice fields from raw OCR text using LLM |
| **Inputs** | `state.ocr.raw_text` |
| **Outputs** | `state.extraction` (all invoice fields, line items) |
| **Tools Used** | `ExtractionTool`, `PromptTool`, `NormalizationTool`, `CurrencyTool` |
| **Failure Handling** | LLM timeout → retry; low confidence fields → flag for human review |
| **Retry Logic** | 3 retries with exponential backoff; prompt version fallback |
| **Confidence** | Per-field LLM confidence aggregated |
| **Human Escalation** | Mandatory fields missing AND LLM confidence < 0.5 |
| **Audit Events** | EXTRACTION_COMPLETED, EXTRACTION_LOW_CONFIDENCE |

#### Agent 5: UniversalValidationAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Apply universal validation rules (GST, PAN, arithmetic) |
| **Inputs** | `state.extraction` |
| **Outputs** | `state.validation.universal` |
| **Tools Used** | `GSTTool`, `PANTool`, `ArithmeticTool`, `ValidationTool` |
| **Failure Handling** | Individual rule failures accumulate; HARD_FAIL only on critical rules |
| **Retry Logic** | No retry — deterministic rules |
| **Confidence** | Ratio of passed rules to total rules |
| **Human Escalation** | HARD_FAIL on any critical rule |
| **Audit Events** | UNIVERSAL_VALIDATION_COMPLETED |

#### Agent 6: BusinessProfileAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Detect which of 9 business profiles applies to this invoice |
| **Inputs** | `state.extraction`, `state.validation.universal` |
| **Outputs** | `state.business_profile` |
| **Tools Used** | `BusinessRuleTool`, `PromptTool`, `ConfigurationTool` |
| **Failure Handling** | Cannot determine profile → UNKNOWN → human review |
| **Retry Logic** | 2 LLM retries |
| **Confidence** | Rule score × 0.4 + LLM score × 0.6 |
| **Human Escalation** | UNKNOWN profile or tie between profiles |
| **Audit Events** | PROFILE_DETECTED |

#### Agent 7: ProfileValidationAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Apply profile-specific validation rules loaded from configuration |
| **Inputs** | `state.business_profile.detected_profile`, `state.extraction` |
| **Outputs** | `state.validation.profile` |
| **Tools Used** | `BusinessRuleTool`, `ValidationTool`, `ConfigurationTool` |
| **Failure Handling** | Each rule failure recorded individually with explanation |
| **Retry Logic** | No retry — deterministic |
| **Confidence** | Ratio of passed profile-specific rules |
| **Human Escalation** | HARD_FAIL on critical profile rules |
| **Audit Events** | PROFILE_VALIDATION_COMPLETED |

#### Agent 8: VendorMatchingAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Match extracted vendor to vendor master database |
| **Inputs** | `state.extraction.vendor_name`, `state.extraction.vendor_gstin` |
| **Outputs** | `state.matching.vendor` |
| **Tools Used** | `VendorTool`, `ComparisonTool` |
| **Failure Handling** | No match → raise NO_MATCH exception → human review |
| **Retry Logic** | No retry — data-driven |
| **Confidence** | Match score from similarity algorithm |
| **Human Escalation** | NO_MATCH → human resolves or creates new vendor |
| **Audit Events** | VENDOR_MATCHED, VENDOR_NOT_FOUND |

#### Agent 9: DuplicateDetectionAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Detect if invoice has already been processed |
| **Inputs** | `state.extraction.invoice_number`, `state.matching.vendor.matched_vendor_id`, `state.extraction.total_amount` |
| **Outputs** | `state.matching.duplicate` |
| **Tools Used** | `DuplicateTool`, `HashTool` |
| **Failure Handling** | Near-duplicate (0.7–0.95 score) → human confirms |
| **Retry Logic** | No retry |
| **Confidence** | Similarity score of matched fields |
| **Human Escalation** | Near-duplicate ambiguity |
| **Audit Events** | DUPLICATE_DETECTED, UNIQUE_CONFIRMED |

#### Agent 10: TaxValidationAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Validate GST, TDS applicability, GSTIN verification |
| **Inputs** | `state.extraction`, `state.matching.vendor` |
| **Outputs** | `state.validation.tax` |
| **Tools Used** | `TaxValidationTool`, `GSTTool`, `PANTool`, `ConfigurationTool` |
| **Failure Handling** | Invalid GSTIN → exception; incorrect TDS → flag for finance team |
| **Retry Logic** | No retry — deterministic |
| **Human Escalation** | GSTIN mismatch, TDS calculation error |
| **Audit Events** | TAX_VALIDATION_COMPLETED |

#### Agent 11: POMatchingAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Perform 2-way or 3-way match between Invoice / PO / GRN |
| **Inputs** | `state.extraction.po_reference`, `state.matching.vendor`, `state.business_profile` |
| **Outputs** | `state.matching.po_grn` |
| **Tools Used** | `POTool`, `GRNTool`, `MatchingTool`, `ComparisonTool`, `ConfigurationTool` |
| **Failure Handling** | No PO for NON_PO profiles → skip; PO not found → exception |
| **Confidence** | Match percentage across quantity and value |
| **Human Escalation** | Tolerance breach or partial GRN match |
| **Audit Events** | PO_MATCH_COMPLETED, THREE_WAY_MATCH_RESULT |

#### Agent 12: ConfidenceAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Aggregate all per-stage confidence scores into overall score |
| **Inputs** | All previous state sections |
| **Outputs** | `state.confidence` |
| **Tools Used** | `ConfidenceTool`, `ConfigurationTool` |
| **Failure Handling** | Missing scores default to 0.5; always produces result |
| **Audit Events** | CONFIDENCE_CALCULATED |

#### Agent 13: DecisionAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Make final routing decision: auto-approve, approval required, or reject |
| **Inputs** | `state.confidence`, `state.validation`, `state.matching`, `state.exceptions` |
| **Outputs** | `state.decision` |
| **Tools Used** | `BusinessRuleTool`, `ConfigurationTool` |
| **Human Escalation** | Conflicting rules — ambiguous decision |
| **Audit Events** | DECISION_MADE |

#### Agent 14: ExceptionAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Classify, enrich, and route all exceptions with full context |
| **Inputs** | Any state + the triggering failure |
| **Outputs** | `state.exceptions` |
| **Tools Used** | `ExceptionTool`, `ExceptionRegistry`, `UserTool`, `TimelineTool` |
| **Failure Handling** | Always succeeds — capturing the exception IS the success |
| **Audit Events** | EXCEPTION_RAISED, EXCEPTION_ASSIGNED |

#### Agent 15: ApprovalAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Route the invoice through the configured approval matrix |
| **Inputs** | `state.decision`, `state.extraction.total_amount`, `state.business_profile` |
| **Outputs** | `state.approval` |
| **Tools Used** | `ApprovalTool`, `ApprovalMatrixTool`, `UserTool`, `NotificationTool` |
| **Failure Handling** | Approver unavailable → route to delegate; SLA breach → escalate |
| **Audit Events** | APPROVAL_REQUESTED, APPROVAL_GRANTED, APPROVAL_REJECTED |

#### Agent 16: ERPPostingAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Post the approved invoice to the configured ERP system |
| **Inputs** | `state.extraction`, `state.matching`, `state.approval`, `state.validation.tax` |
| **Outputs** | `state.erp` |
| **Tools Used** | `ERPTool` (provider-agnostic), `ConfigurationTool` |
| **Failure Handling** | ERP unavailable → retry 5× with backoff; dead-letter queue after max |
| **Retry Logic** | 5 retries with exponential backoff |
| **Audit Events** | ERP_POSTING_INITIATED, ERP_POSTING_COMPLETED, ERP_POSTING_FAILED |

#### Agent 17: PaymentAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Calculate net payable, apply TDS, determine payment due date |
| **Inputs** | `state.erp`, `state.extraction`, `state.validation.tax` |
| **Outputs** | `state.erp.payment` |
| **Tools Used** | `TDSTool`, `CurrencyTool`, `ConfigurationTool` |
| **Failure Handling** | Calculation errors → exception with full arithmetic trail |
| **Audit Events** | PAYMENT_SCHEDULED |

#### Agent 18: NotificationAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Dispatch all relevant notifications at end of processing |
| **Inputs** | `state.decision`, `state.approval`, `state.exceptions`, `state.erp` |
| **Outputs** | `state.notifications` |
| **Tools Used** | `NotificationTool`, `UserTool`, `ConfigurationTool` |
| **Failure Handling** | Channel failure → retry 3×; fallback channel; never blocks pipeline |
| **Audit Events** | NOTIFICATION_SENT, NOTIFICATION_FAILED |

#### Agent 19: AuditAgent

| Attribute | Detail |
|---|---|
| **Purpose** | Write the complete immutable audit trail to the audit log |
| **Inputs** | Full WorkflowState |
| **Outputs** | `state.audit` (confirmed written) |
| **Tools Used** | `AuditTool`, `TimelineTool` |
| **Failure Handling** | CRITICAL — blocks completion; alerts ops team; dead-letter fallback |
| **Retry Logic** | 5 retries; dead-letter queue after failure |
| **Audit Events** | AUDIT_TRAIL_WRITTEN |

---

## SECTION 6 — Reusable Tool Architecture

### 6.1 Tool Design Principles

| Principle | Rule |
|---|---|
| Single Responsibility | Each tool solves exactly one problem |
| Stateless | Tools receive inputs, return outputs, hold no state |
| Provider-Agnostic | Tools program to interfaces, not to specific vendors |
| Independently Testable | Every tool can be unit-tested without agents or graphs |
| Dependency Injected | Dependencies injected, not imported |
| Reusable | Any tool can be used in any future AI agent project |

### 6.2 Tool Catalogue

#### PDFTool
| | |
|---|---|
| **Purpose** | Extract pages, images, and metadata from PDF files |
| **Inputs** | `file_path: str`, `options: PDFOptions` |
| **Outputs** | `PDFResult(pages: List[PageImage], metadata: dict, page_count: int)` |
| **Dependencies** | PyMuPDF |
| **Methods** | `extract_pages()`, `extract_images()`, `extract_metadata()`, `get_page_count()` |
| **Exceptions** | `PDFCorruptedException`, `PDFPasswordProtectedException` |
| **Future Extensions** | PDF/A validation, digital signatures, form field extraction |

#### ImageTool
| | |
|---|---|
| **Purpose** | Assess image quality and pre-process for OCR |
| **Inputs** | `image: bytes`, `options: ImageOptions` |
| **Outputs** | `ImageResult(quality_score: float, dpi: int, is_skewed: bool, preprocessed: bytes)` |
| **Dependencies** | OpenCV, Pillow |
| **Methods** | `assess_quality()`, `deskew()`, `denoise()`, `enhance_contrast()`, `resize_for_ocr()` |
| **Future Extensions** | Barcode/QR extraction, stamp detection, signature detection |

#### FileTool
| | |
|---|---|
| **Purpose** | File format validation, MIME type detection, size checks |
| **Inputs** | `file_path: str` |
| **Outputs** | `FileResult(mime_type: str, is_valid: bool, size_bytes: int, extension: str)` |
| **Dependencies** | python-magic |
| **Methods** | `validate_format()`, `detect_mime()`, `check_size_limit()` |
| **Future Extensions** | Excel, XML invoice formats, EDI |

#### MetadataTool
| | |
|---|---|
| **Purpose** | Extract and normalize file metadata |
| **Methods** | `extract_pdf_metadata()`, `extract_image_metadata()` |
| **Future Extensions** | Microsoft Office metadata, email metadata |

#### VirusScanTool
| | |
|---|---|
| **Purpose** | Scan uploaded files for malware before any processing |
| **Inputs** | `file_path: str` |
| **Outputs** | `ScanResult(is_clean: bool, threat_name: str, scan_provider: str)` |
| **Dependencies** | ClamAV (local) or Azure Defender for Storage |
| **Methods** | `scan_file()` |
| **Exceptions** | `VirusThreatDetectedException`, `ScanProviderUnavailableException` |

#### HashTool
| | |
|---|---|
| **Purpose** | Generate and verify cryptographic hashes for document integrity |
| **Inputs** | `file_path: str` OR `content: bytes` |
| **Outputs** | `HashResult(sha256: str, md5: str)` |
| **Methods** | `compute_sha256()`, `compute_md5()`, `verify_hash()` |
| **Future Extensions** | Digital signing, blockchain anchoring |

#### OCRTool (Provider Interface)
| | |
|---|---|
| **Purpose** | Provider-agnostic OCR — dispatches based on config |
| **Inputs** | `image: bytes`, `document_type: str`, `options: OCROptions` |
| **Outputs** | `OCRResult(raw_text: str, blocks: List[TextBlock], confidence: float, provider: str)` |
| **Dependencies** | `TesseractProvider` or `AzureDIProvider` (injected via config) |
| **Methods** | `extract_text()`, `extract_structured_blocks()` |
| **Future Extensions** | Google Vision, AWS Textract — add provider, change config |

#### ExtractionTool
| | |
|---|---|
| **Purpose** | Use LLM to extract structured invoice data from OCR text |
| **Inputs** | `raw_text: str`, `prompt: VersionedPrompt`, `llm_client: LLMService` |
| **Outputs** | `ExtractionResult(fields: dict, confidence_per_field: dict, model_used: str, tokens: int)` |
| **Methods** | `extract_fields()`, `validate_extracted_schema()` |

#### NormalizationTool
| | |
|---|---|
| **Purpose** | Normalize extracted field values to canonical formats |
| **Methods** | `normalize_date()`, `normalize_amount()`, `normalize_name()`, `normalize_gstin()` |

#### PromptTool
| | |
|---|---|
| **Purpose** | Load, render, and version-manage prompts for LLM calls |
| **Inputs** | `agent: str`, `prompt_version: str`, `variables: dict` |
| **Outputs** | `RenderedPrompt(system: str, user: str, version: str, hash: str)` |
| **Methods** | `load_prompt()`, `render_template()`, `get_active_version()` |

#### CurrencyTool
| | |
|---|---|
| **Purpose** | Parse, validate, and convert currency values |
| **Methods** | `parse_amount()`, `format_amount()`, `convert_currency()` |

#### ValidationTool
| | |
|---|---|
| **Purpose** | Execute a set of validation rules and return structured results |
| **Inputs** | `rules: List[ValidationRule]`, `data: dict` |
| **Outputs** | `ValidationReport(results: List[ValidationResult], overall_status: str)` |
| **Each ValidationResult contains** | rule_name, status, reason, evidence, confidence, recommendation |

#### GSTTool
| | |
|---|---|
| **Purpose** | Validate GSTIN format and optionally verify against GST portal |
| **Methods** | `validate_format()`, `verify_online()` |

#### PANTool
| | |
|---|---|
| **Purpose** | Validate PAN format and entity type |
| **Methods** | `validate_format()` |

#### ArithmeticTool
| | |
|---|---|
| **Purpose** | Verify invoice arithmetic — line items, tax, totals |
| **Outputs** | `ArithmeticResult(is_valid: bool, computed values, variance: Decimal)` |

#### BusinessRuleTool
| | |
|---|---|
| **Purpose** | Execute configurable business rules loaded from YAML |
| **Inputs** | `rule_set: str`, `data: dict`, `config: BusinessRulesConfig` |
| **Outputs** | `RuleResult(triggered_rules: List[str], passed: bool, explanation: str)` |
| **Future Extensions** | Rule versioning, visual rule editor, customer-specific rules |

#### TaxValidationTool
| | |
|---|---|
| **Purpose** | Validate TDS rates, GST rates, compliance rules |
| **Methods** | `calculate_tds()`, `validate_gst_rate()`, `check_threshold_applicability()` |

#### VendorTool
| | |
|---|---|
| **Purpose** | Search vendor master using exact, fuzzy, and GSTIN strategies |
| **Methods** | `exact_match()`, `fuzzy_match()`, `gstin_match()`, `pan_match()` |

#### DuplicateTool
| | |
|---|---|
| **Purpose** | Detect duplicate invoices using hash and field comparison |
| **Methods** | `check_exact_duplicate()`, `check_near_duplicate()` |

#### POTool
| | |
|---|---|
| **Purpose** | Retrieve PO data and validate PO existence and status |
| **Methods** | `find_po()`, `check_po_status()`, `get_remaining_value()` |

#### GRNTool
| | |
|---|---|
| **Purpose** | Retrieve GRN data for goods receipt verification |
| **Methods** | `find_grns_for_po()`, `get_received_quantities()` |

#### MatchingTool
| | |
|---|---|
| **Purpose** | Perform 2-way and 3-way matching logic with tolerance |
| **Methods** | `three_way_match()`, `two_way_match()`, `check_tolerance()` |

#### ComparisonTool
| | |
|---|---|
| **Purpose** | Compare two values with configurable strategy (exact, fuzzy, percentage) |
| **Methods** | `compare_strings()`, `compare_decimals()`, `compare_dates()`, `fuzzy_compare()` |

#### ERPTool (Provider Interface)
| | |
|---|---|
| **Purpose** | Provider-agnostic ERP posting operations |
| **Providers** | `MockERPProvider`, `SAPProvider (stub)`, `OracleProvider (stub)` |
| **Methods** | `post_invoice()`, `get_status()`, `reverse_posting()` |

#### NotificationTool
| | |
|---|---|
| **Purpose** | Dispatch notifications through configured channels |
| **Channels** | `EmailChannel`, `TeamsChannel` |
| **Methods** | `send()`, `get_template()`, `resolve_recipients()` |

#### ApprovalTool
| | |
|---|---|
| **Purpose** | Create, route, and track approval requests |
| **Methods** | `create_request()`, `submit_decision()`, `escalate()`, `get_status()` |

#### ExceptionTool
| | |
|---|---|
| **Purpose** | Create and enrich exception records with full context |
| **Methods** | `raise_exception()`, `enrich_exception()`, `resolve_exception()`, `get_history()` |

#### AuditTool
| | |
|---|---|
| **Purpose** | Write structured, immutable audit events |
| **Methods** | `write_event()`, `get_timeline()` |

#### ConfidenceTool
| | |
|---|---|
| **Purpose** | Aggregate per-stage confidence scores into an overall score |
| **Methods** | `calculate_weighted_score()`, `determine_tier()`, `identify_risk_factors()` |

#### ConfigurationTool
| | |
|---|---|
| **Purpose** | Load and cache configuration values by key and tenant |
| **Methods** | `get()`, `get_section()`, `invalidate_cache()` |
| **Future Extensions** | Hot-reload without restart, feature flags |

#### RetryTool
| | |
|---|---|
| **Purpose** | Execute a function with configurable retry logic |
| **Methods** | `execute_with_retry()`, `calculate_backoff()` |

#### StorageTool (Provider Interface)
| | |
|---|---|
| **Purpose** | Provider-agnostic file storage operations |
| **Providers** | `LocalStorageProvider` (dev), `AzureBlobProvider` (prod) |
| **Methods** | `upload()`, `download()`, `delete()`, `get_url()`, `exists()` |

#### PromptVersionTool
| | |
|---|---|
| **Purpose** | Manage versioned prompts: load, activate, rollback |
| **Methods** | `get_active_version()`, `activate_version()`, `rollback()`, `get_history()` |

#### UserTool
| | |
|---|---|
| **Purpose** | Resolve users, roles, and delegates for routing decisions |
| **Methods** | `find_approver()`, `find_delegate()`, `get_team_members()` |

#### TimelineTool
| | |
|---|---|
| **Purpose** | Build a human-readable processing timeline from audit events |
| **Methods** | `build_timeline()`, `identify_bottlenecks()` |

#### AnalyticsTool
| | |
|---|---|
| **Purpose** | Compute processing metrics for dashboards |
| **Methods** | `processing_volume()`, `exception_rate()`, `approval_cycle_time()`, `stp_rate()` |

---

## SECTION 7 — Prompt Architecture

### 7.1 Prompt File Structure

```
app/prompts/registry/
├── classification/
│   ├── v1.yaml     ← production (active)
│   └── v2.yaml     ← candidate (staging/testing)
├── extraction/
│   ├── v1.yaml
│   └── v2.yaml
├── business_profile/
│   └── v1.yaml
├── validation/
│   └── v1.yaml
└── decision/
    └── v1.yaml
```

### 7.2 Prompt YAML Schema

```yaml
metadata:
  agent: extraction
  version: "2.0.0"
  author: "platform-team"
  created_at: "2026-01-15"
  description: "Improved extraction prompt with better line item handling"
  model_compatibility: ["gpt-4o", "gpt-4o-mini"]
  deprecated: false
  change_log:
    - version: "2.0.0"
      change: "Added explicit line item extraction instructions"
      date: "2026-01-15"
    - version: "1.0.0"
      change: "Initial version"
      date: "2025-11-01"

system_prompt: |
  You are an enterprise invoice data extraction specialist.
  [prompt content]

user_prompt_template: |
  Extract structured data from the following invoice text:
  {{ ocr_text }}
  Return JSON matching this schema: {{ json_schema }}

output_schema:
  type: object
  required: [invoice_number, invoice_date, ...]
```

### 7.3 Prompt Lifecycle

```
DRAFT ──► STAGING ──► PRODUCTION ──► DEPRECATED

PRODUCTION: one active version per agent at any time
STAGING: new version under testing
ROLLBACK: activate previous version via API in seconds

Database table: prompt_versions
Columns: agent, version, status, content_hash,
         activated_at, deactivated_at, created_by
```

### 7.4 Prompt Management API

```
GET    /api/v1/config/prompts                          → list all prompts + active versions
GET    /api/v1/config/prompts/{agent}                  → prompt for agent
GET    /api/v1/config/prompts/{agent}/history          → version history
GET    /api/v1/config/prompts/{agent}/versions/{v}     → specific version content
POST   /api/v1/config/prompts/{agent}/activate/{v}     → activate a version
POST   /api/v1/config/prompts/{agent}/rollback         → rollback to previous
```

### 7.5 Customer-Specific Prompts

Prompt lookup order per request:
1. Customer-specific prompt for this `tenant_id` + agent + active version
2. If not found → global active version
3. Render template with context variables
4. Log: agent, version, hash, tokens consumed

---

## SECTION 8 — Configuration Driven Architecture

### 8.1 Configuration Layers

```
Priority Order (highest wins):
1. Environment Variables (.env / Azure App Configuration)
2. Tenant-specific DB config (config_entries table)
3. Application YAML files (app/config/*.yaml)
4. Hardcoded defaults in settings.py
```

### 8.2 Environment Settings (settings.py — Pydantic BaseSettings)

```
DATABASE_URL, REDIS_URL, OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT,
AZURE_STORAGE_CONNECTION_STRING, AZURE_SERVICE_BUS_CONNECTION_STRING,
OCR_PROVIDER (tesseract|azure_di), STORAGE_PROVIDER (local|azure_blob),
ERP_PROVIDER (mock|sap|oracle), LLM_PROVIDER (openai|azure_openai),
DEFAULT_LLM_MODEL, NOTIFICATION_PROVIDER (email|teams),
SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, TEAMS_WEBHOOK_URL
```

### 8.3 YAML Configuration Files

**business_rules.yaml**
```yaml
profiles:
  PO_RAW_MATERIAL:
    mandatory_fields: [invoice_number, po_number, gstin, grn_reference]
    matching_required: true
    tolerance_percent: 2.5
    require_three_way_match: true
  NON_PO_OPEX:
    mandatory_fields: [invoice_number, vendor_name, gstin]
    matching_required: false
    require_department_approval: true
```

**approval_matrix.yaml**
```yaml
approval_matrix:
  - profile: "*"
    amount_from: 0
    amount_to: 10000
    levels:
      - level: 1
        role: AP_EXECUTIVE
        sla_hours: 4
  - profile: "*"
    amount_from: 10001
    amount_to: 100000
    levels:
      - level: 1
        role: AP_MANAGER
        sla_hours: 8
      - level: 2
        role: FINANCE_CONTROLLER
        sla_hours: 24
```

**confidence_config.yaml**
```yaml
stage_weights:
  extraction: 0.30
  validation: 0.20
  vendor_matching: 0.20
  po_matching: 0.20
  tax_validation: 0.10

thresholds:
  auto_approve_minimum: 0.85
  human_review_below: 0.60
  reject_below: 0.30

tiers:
  HIGH:   { min: 0.85, max: 1.00 }
  MEDIUM: { min: 0.60, max: 0.85 }
  LOW:    { min: 0.00, max: 0.60 }
```

**tolerance_config.yaml**
```yaml
matching_tolerances:
  quantity_tolerance_percent: 2.0
  value_tolerance_percent: 2.5
  date_tolerance_days: 5
  by_profile:
    PO_CAPEX:
      value_tolerance_percent: 0.5
    PETTY_CASH:
      value_tolerance_percent: 10.0
```

**country_config.yaml**
```yaml
countries:
  IN:
    currency: INR
    gst_applicable: true
    tds_applicable: true
    gstin_format: "^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
    pan_format: "^[A-Z]{5}[0-9]{4}[A-Z]{1}$"
    tds_sections:
      194C: { rate: 1.0, threshold: 30000 }
      194J: { rate: 10.0, threshold: 30000 }
```

**provider_config.yaml**
```yaml
providers:
  llm:
    default: openai
    model: gpt-4o
    fallback: azure_openai
  ocr:
    default: tesseract
    fallback: azure_di
  storage:
    default: azure_blob
  erp:
    default: mock
  notification:
    default: email
    channels: [email]
```

### 8.4 Configuration API

```
GET    /api/v1/config                → get all config keys
GET    /api/v1/config/{section}      → get config section
PUT    /api/v1/config/{key}          → update config value (admin only)
GET    /api/v1/config/approval-matrix → view current approval matrix
GET    /api/v1/config/business-rules  → view current business rules
GET    /api/v1/config/tolerance       → view current tolerances
GET    /api/v1/config/confidence      → view confidence thresholds
```

---

## SECTION 9 — ERP Integration Strategy

### 9.1 ERP Abstraction Architecture

```
ERPPostingAgent
      │
      ▼
  ERPTool (interface)
      │
      ▼
┌─────────────────────────────────────────────────────────┐
│                  ERP PROVIDER INTERFACE                 │
│                                                         │
│  def post_invoice(payload: ERPPayload) → ERPResult      │
│  def get_status(document_number: str) → ERPStatus       │
│  def reverse_posting(document_number: str) → ERPResult  │
│  def get_cost_centers() → List[CostCenter]              │
│  def get_gl_accounts() → List[GLAccount]                │
│  def validate_payload(payload: ERPPayload) → bool       │
└──────────┬──────────────────────────────────────────────┘
           │
   ┌───────┼────────────────────────────────────┐
   │       │                 │                  │
   ▼       ▼                 ▼                  ▼
MockERP  SAPProvider    OracleProvider   DynamicsProvider
(active) (stub)         (stub)           (stub)
```

### 9.2 Universal ERPPayload

```
ERPPayload:
  document_id, vendor_erp_code, po_number
  invoice_number, invoice_date, posting_date, fiscal_year
  currency, gross_amount, tax_amount, tds_amount, net_payable
  payment_terms, due_date
  cost_center, gl_account, profit_center
  line_items: List[ERPLineItem]
  tax_lines: List[ERPTaxLine]
  reference_documents: List[str]
```

### 9.3 ERP Provider Registration

```yaml
# provider_config.yaml
erp:
  provider: sap  ← change this one line to switch ERP
  sap:
    host: "sap.company.com"
    client: "100"
    system_id: "PRD"
  oracle:
    base_url: "https://oracle.company.com/api"
  mock:
    delay_ms: 200
```

When SAP is plugged in: only `SAPProvider` is written. No agent changes, no graph changes, no tool interface changes.

---

## SECTION 10 — Logging Architecture

### 10.1 AgentExecutionLog Schema

```
AgentExecutionLog:
  log_id: UUID
  workflow_id: UUID
  document_id: UUID
  agent_name: str
  stage: str
  started_at / completed_at / duration_ms

  # LLM Details
  prompt_version: str
  model_used: str
  prompt_tokens / completion_tokens / total_tokens / estimated_cost_usd

  # Tool Calls
  tools_called: List[ToolCallLog]
    └── ToolCallLog: tool_name, inputs_hash, duration_ms, success, error

  # Results
  confidence_before / confidence_after
  result_status: SUCCESS / FAIL / EXCEPTION / ESCALATED

  # Failures
  retry_count: int
  errors: List[ErrorLog]
    └── ErrorLog: error_type, message, stack_trace, timestamp, retry_number

  # Human Actions
  human_action_required: bool
  human_action_taken: str
  human_actor: str

  # Audit
  audit_events_written: List[str]
```

### 10.2 Log Destinations

```
AgentExecutionLog  → PostgreSQL (agent_execution_logs)
                   → Azure Log Analytics (structured JSON)
                   → Console (dev only)

AuditEvent         → PostgreSQL (audit_logs — immutable, append-only)

StructuredAppLog   → Azure Application Insights
                   → Console (dev only)
```

### 10.3 Log API Endpoints

```
GET /api/v1/audit/{document_id}              → full audit trail
GET /api/v1/audit/{document_id}/timeline     → visual timeline
GET /api/v1/audit/{document_id}/decisions    → AI decisions with explanations
GET /api/v1/workflows/{workflow_id}/logs     → agent execution logs
GET /api/v1/analytics/performance            → aggregate performance metrics
GET /api/v1/analytics/costs                  → LLM token costs by agent/period
```

---

## SECTION 11 — Explainability Architecture

### 11.1 Core Principle

Every AI decision, validation, and routing choice must produce an `Explanation` object. No agent returns only `PASS`, `FAIL`, or a bare enum value.

### 11.2 ValidationResult Schema

```
ValidationResult:
  rule_name: str               # "gst_format_check"
  rule_version: str            # "1.2"
  status: PASS / FAIL / WARNING / SKIPPED

  # Why it passed or failed
  reason: str                  # "GSTIN checksum digit does not match"
  recommendation: str          # "Request corrected invoice from vendor"

  # Evidence
  evidence: dict               # { "extracted_gstin": "27AABCU...", "expected_format": "..." }
  compared_values: dict        # { "field_a": x, "field_b": y, "variance": z }

  confidence: float
```

### 11.3 ExplainableDecision Schema

```
ExplainableDecision:
  decision: str                # "NEEDS_APPROVAL"
  primary_reason: str          # "Invoice amount exceeds auto-approve threshold"

  contributing_factors: List[Factor]
    └── Factor: factor_name, weight, value, direction

  rules_triggered: List[str]
  rules_evaluated / rules_passed: int

  confidence_breakdown: dict   # per-stage scores
  overall_confidence: float

  alternative_decisions: List[AlternativeDecision]
    └── decision, reason, would_apply_if
```

### 11.4 Explainability API

```
GET /api/v1/documents/{document_id}/explanation      → full AI decision explanation
GET /api/v1/documents/{document_id}/validation       → all validation results with reasons
GET /api/v1/documents/{document_id}/matching         → PO/GRN match details with evidence
GET /api/v1/documents/{document_id}/confidence       → confidence breakdown by stage
GET /api/v1/exceptions/{exception_id}/explanation    → why this exception was raised
GET /api/v1/approvals/{approval_id}/recommendation   → AI recommendation for approver
```

---

## SECTION 12 — Exception Architecture

### 12.1 ExceptionRecord Schema

```
ExceptionRecord:
  exception_id: UUID
  workflow_id / document_id / raised_by_agent / raised_at

  # Classification
  exception_type: str          # "DUPLICATE_INVOICE" / "PO_MISMATCH" / ...
  exception_category: VALIDATION / MATCHING / COMPLIANCE / SYSTEM / MANUAL
  severity: CRITICAL / HIGH / MEDIUM / LOW

  # Why it was raised
  reason: str
  evidence: dict
  compared_fields: dict
  confidence: float

  # Resolution Guidance
  suggested_resolution: str
  resolution_options: List[str]
  retry_action: str
  resume_action: str

  # Routing
  responsible_team: AP_TEAM / FINANCE / PROCUREMENT / COMPLIANCE / WAREHOUSE
  assigned_to: str
  escalation_path: List[str]

  # SLA
  sla_hours / sla_deadline / sla_breached / priority_score

  # Status
  status: OPEN / IN_PROGRESS / RESOLVED / ESCALATED / CLOSED
  resolution_comment / resolved_by / resolved_at

  history: List[ExceptionHistoryEntry]
    └── timestamp, actor, action, comment
```

### 12.2 Exception Type Registry

```
DUPLICATE_INVOICE:
  severity: HIGH | responsible_team: AP_TEAM | sla_hours: 4

PO_MISMATCH:
  severity: HIGH | responsible_team: PROCUREMENT | sla_hours: 8

GSTIN_INVALID:
  severity: CRITICAL | responsible_team: COMPLIANCE | sla_hours: 2

OCR_LOW_QUALITY:
  severity: MEDIUM | responsible_team: AP_TEAM | sla_hours: 4

VENDOR_NOT_FOUND:
  severity: MEDIUM | responsible_team: AP_TEAM | sla_hours: 8
```

### 12.3 Exception API

```
GET    /api/v1/exceptions                          → list exceptions
GET    /api/v1/exceptions/{exception_id}           → full exception record
GET    /api/v1/exceptions/{exception_id}/history   → resolution history
POST   /api/v1/exceptions/{exception_id}/resolve   → resolve and resume pipeline
POST   /api/v1/exceptions/{exception_id}/escalate  → escalate to next level
GET    /api/v1/exceptions/my-queue                 → assigned to current user
GET    /api/v1/exceptions/team/{team}              → team queue
GET    /api/v1/analytics/exceptions/sla            → SLA breach analytics
```

---

## SECTION 13 — Approval Architecture

### 13.1 Approval Engine Design

The approval engine is fully driven by `approval_matrix.yaml`. No code changes are required to modify approval rules.

```
ApprovalEngine:
  ├── reads approval_matrix.yaml (or DB override)
  ├── matches: amount_range + business_profile + department
  ├── determines: number of levels + approvers at each level
  ├── supports: sequential + parallel levels
  └── writes: ApprovalRecord for every action
```

### 13.2 Approval Flow Patterns

```
Pattern A: Single Level
  Invoice → Approver L1 → [APPROVED / REJECTED] → Resume

Pattern B: Sequential Multi-Level
  Invoice → L1 → APPROVED → L2 → APPROVED → L3 → Resume

Pattern C: Parallel Multi-Level (future)
  Invoice → L1 ─┐
            L2 ─┼─→ ALL APPROVED → Resume
            L3 ─┘

Pattern D: Amount-Based (from YAML — no code changes)
  < 10K     → AP Executive
  10K–100K  → AP Manager + Finance Controller
  100K+     → Finance Director + CFO
```

### 13.3 Approval Record Schema

```
ApprovalRecord:
  approval_id, document_id, workflow_id
  level, approver_id, approver_role, approver_email
  status: PENDING / APPROVED / REJECTED / DELEGATED / EXPIRED
  request_sent_at / decision_at / comments
  delegate_to, sla_hours, sla_deadline
  ai_recommendation: str  ← AI-generated recommendation for approver
```

### 13.4 Approval API

```
GET    /api/v1/approvals                          → list approvals
GET    /api/v1/approvals/{approval_id}            → detail with AI recommendation
POST   /api/v1/approvals/{approval_id}/approve    → approve with optional comment
POST   /api/v1/approvals/{approval_id}/reject     → reject with mandatory reason
POST   /api/v1/approvals/{approval_id}/delegate   → delegate to another user
GET    /api/v1/approvals/my-queue                 → pending for current user
GET    /api/v1/approvals/{approval_id}/history    → full approval history
```

---

## SECTION 14 — Future-Ready Architecture

### 14.1 Extension Table

| Future Capability | What Changes | What Does NOT Change |
|---|---|---|
| Azure Document Intelligence OCR | Add `AzureDIProvider` in `tools/ocr/` | No agent, no graph |
| SAP ERP Integration | Add `SAPProvider` in `tools/erp/` | No agent, no graph |
| Oracle ERP Integration | Add `OracleProvider` in `tools/erp/` | No agent, no graph |
| Email Invoice Ingestion | Add `EmailIngestAgent` + trigger endpoint | No existing agent |
| Teams/WhatsApp notifications | Add channel in `notifications/` | No agent, no tool contract |
| New LLM (Gemini, Llama) | Add provider in `services/llm_service.py` | No agent, no tool |
| New Business Profile | Add profile in `business_rules.yaml` | No code |
| New Validation Rule | Add rule in `business_rules.yaml` | No code |
| New Country | Add entry in `country_config.yaml` | No code |
| Multi-tenancy | Add `tenant_id` context + tenant config | No business logic |
| Agent Marketplace | Register new agents in `graph_registry.py` | No existing agent |
| Multiple LLMs per agent | Update `provider_config.yaml` | No agent code |
| New Approval Level | Update `approval_matrix.yaml` | No code |

### 14.2 Multi-Tenancy Design

```
Every table has a tenant_id column.
Every API request carries X-Tenant-ID header.
FastAPI middleware injects tenant_id into request context.
Every repository query filters by tenant_id.
Every config load is tenant-scoped with global fallback.
Every prompt load is tenant-scoped with global fallback.
```

### 14.3 Agent Marketplace

```
GraphRegistry:
  invoice_processing:
    nodes:
      - upload_agent            ← from platform
      - classification_agent    ← from platform
      - extraction_agent        ← from platform / customer override
      - custom_agent_X          ← customer-specific (registered here)
```

New agents: create class → register in `graph_registry.py` → add to graph. No other file changes.

---

## AZURE DEPLOYMENT ARCHITECTURE

### Azure Services Map

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           AZURE RESOURCE GROUP                                  │
│                                                                                 │
│  ┌─────────────────────┐    ┌──────────────────────┐                           │
│  │  Azure Static Web   │    │  Azure App Service   │                           │
│  │  Apps (Next.js)     │    │  (FastAPI — Python)  │                           │
│  │  + Azure CDN        │    │  Plan: P1v3+         │                           │
│  └─────────────────────┘    └──────────┬───────────┘                           │
│                                        │                                       │
│  ┌─────────────────────┐  ┌────────────▼──────────┐  ┌───────────────────────┐│
│  │  Azure Database for │  │  Azure Cache for Redis│  │  Azure Service Bus    ││
│  │  PostgreSQL         │  │  (Celery broker +     │  │  (durable async       ││
│  │  Flexible Server    │  │   result backend +    │  │   document processing)││
│  │  (primary DB +      │  │   config cache)       │  └───────────────────────┘│
│  │   LangGraph state)  │  └───────────────────────┘                           │
│  └─────────────────────┘                                                       │
│  ┌─────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐│
│  │  Azure Blob         │  │  Azure Container Apps │  │  Azure Key Vault      ││
│  │  Storage            │  │  (Celery workers)     │  │  (all secrets via     ││
│  │  (documents +       │  │  Min 1 / Max 5        │  │   Managed Identity)   ││
│  │   exports)          │  │  auto-scale           │  └───────────────────────┘│
│  └─────────────────────┘  └───────────────────────┘                           │
│  ┌─────────────────────┐    ┌────────────────────────┐                        │
│  │  Azure Monitor +    │    │  Azure Application     │                        │
│  │  Log Analytics      │    │  Insights (APM)        │                        │
│  └─────────────────────┘    └────────────────────────┘                        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Azure Service Roles

| Service | Replaces (Docker) | Purpose |
|---|---|---|
| Azure App Service | FastAPI container | Hosts FastAPI — auto-scales, zero-downtime deploy |
| Azure Static Web Apps | Nginx + React build | Hosts Next.js — global CDN, free SSL |
| Azure Container Apps | Celery worker containers | Hosts Celery workers — scales to 0, scales out on load |
| Azure Cache for Redis | Redis container | Celery broker + result backend + config cache |
| Azure Database for PostgreSQL Flexible Server | PostgreSQL container | Primary database — managed backups, HA |
| Azure Blob Storage | `backend/uploads/` folder | Document storage — redundant, CDN-ready, infinite scale |
| Azure Service Bus | (new) | Durable async queuing — guaranteed delivery |
| Azure Key Vault | `.env` file | All secrets — no secrets in code or config |
| Azure Application Insights | None | APM, distributed tracing, performance monitoring |
| Azure Log Analytics | None | Centralised log aggregation |

### Deployment Pipeline

```
push to main branch
        │
        ▼
┌─────────────────────────────────────────────────────┐
│                CI/CD PIPELINE                       │
│                                                     │
│  1. Run tests (pytest)                              │
│  2. Build Backend                                   │
│     └── az webapp deploy → App Service             │
│  3. Run Alembic migrations                          │
│     └── az webapp ssh → alembic upgrade head       │
│  4. Build Frontend                                  │
│     └── az staticwebapp deploy                     │
│  5. Build Celery Workers                            │
│     └── az containerapp update --image             │
└─────────────────────────────────────────────────────┘
```

### Infrastructure as Code (Bicep)

All Azure resources defined in `azure/bicep/main.bicep`. New customer environment:

```
az deployment group create \
  --resource-group rg-ap-platform-prod \
  --template-file azure/bicep/main.bicep \
  --parameters tenantName=acme environment=prod
```

One command creates the complete isolated stack — database, storage, Redis, App Service.

### Zero-Downtime Deployment

```
Azure App Service Deployment Slots:
  production slot  → live traffic
  staging slot     → new version deployed and smoke-tested
  swap             → instant traffic swap, no downtime
  rollback         → swap back if issue detected within minutes
```

---

## COMPLETE API ROUTE REFERENCE

All routes prefixed `/api/v1/`. All path parameters are UUIDs (clickable in Swagger UI at `/api/docs`).

```
# DOCUMENTS
GET    /api/v1/documents                               → list documents
POST   /api/v1/documents/upload                        → upload new document
GET    /api/v1/documents/{document_id}                 → document detail
GET    /api/v1/documents/{document_id}/status          → processing status
GET    /api/v1/documents/{document_id}/extraction      → extracted fields
GET    /api/v1/documents/{document_id}/validation      → validation results
GET    /api/v1/documents/{document_id}/matching        → PO/GRN match results
GET    /api/v1/documents/{document_id}/confidence      → confidence breakdown
GET    /api/v1/documents/{document_id}/explanation     → AI decision explanation
GET    /api/v1/documents/{document_id}/timeline        → processing timeline

# WORKFLOWS
GET    /api/v1/workflows/{workflow_id}                 → workflow state
GET    /api/v1/workflows/{workflow_id}/logs            → execution logs
GET    /api/v1/workflows/{workflow_id}/pending-action  → await human input
POST   /api/v1/workflows/{workflow_id}/resume          → resume after human action
POST   /api/v1/workflows/{workflow_id}/retry           → retry failed step

# EXCEPTIONS
GET    /api/v1/exceptions                              → list exceptions
GET    /api/v1/exceptions/{exception_id}               → exception detail
GET    /api/v1/exceptions/{exception_id}/history       → resolution history
POST   /api/v1/exceptions/{exception_id}/resolve       → resolve and resume
POST   /api/v1/exceptions/{exception_id}/escalate      → escalate
GET    /api/v1/exceptions/my-queue                     → my assigned exceptions
GET    /api/v1/exceptions/team/{team_name}             → team queue

# APPROVALS
GET    /api/v1/approvals                               → list approvals
GET    /api/v1/approvals/{approval_id}                 → detail + AI recommendation
POST   /api/v1/approvals/{approval_id}/approve         → approve
POST   /api/v1/approvals/{approval_id}/reject          → reject
POST   /api/v1/approvals/{approval_id}/delegate        → delegate
GET    /api/v1/approvals/my-queue                      → pending for me

# MASTER DATA
GET    /api/v1/vendors                                 → vendor list
GET    /api/v1/vendors/{vendor_id}                     → vendor detail
GET    /api/v1/po                                      → PO list
GET    /api/v1/po/{po_id}                              → PO detail
GET    /api/v1/grn                                     → GRN list
GET    /api/v1/grn/{grn_id}                            → GRN detail

# AUDIT & EXPLAINABILITY
GET    /api/v1/audit/{document_id}                     → audit trail
GET    /api/v1/audit/{document_id}/timeline            → timeline view
GET    /api/v1/audit/{document_id}/decisions           → AI decisions log

# ANALYTICS
GET    /api/v1/analytics/dashboard                     → dashboard metrics
GET    /api/v1/analytics/performance                   → processing performance
GET    /api/v1/analytics/exceptions/sla                → SLA analytics
GET    /api/v1/analytics/costs                         → LLM cost analytics

# CONFIGURATION (admin only)
GET    /api/v1/config                                  → all config
GET    /api/v1/config/{section}                        → config section
PUT    /api/v1/config/{key}                            → update config
GET    /api/v1/config/prompts                          → all prompts
GET    /api/v1/config/prompts/{agent}                  → agent prompt
POST   /api/v1/config/prompts/{agent}/activate/{v}     → activate version
POST   /api/v1/config/prompts/{agent}/rollback         → rollback prompt
GET    /api/v1/config/approval-matrix                  → approval matrix
GET    /api/v1/config/business-rules                   → business rules

# NOTIFICATIONS
GET    /api/v1/notifications                           → notification list
GET    /api/v1/notifications/{notification_id}         → notification detail

# HEALTH
GET    /api/v1/health                                  → platform health
GET    /api/v1/health/deep                             → all dependency checks
```

---

## SECURITY ARCHITECTURE

### Authentication & Authorization

```
Request: Browser → Next.js → FastAPI JWT middleware
  extract: user_id, tenant_id, roles
  inject: RequestContext (every repository and tool reads this)
```

**JWT Payload:** `{ sub, tenant_id, roles, exp }`

### RBAC Matrix

| Role | Documents | Exceptions | Approvals | Config | Analytics | Audit |
|---|---|---|---|---|---|---|
| AP_EXECUTIVE | Read/Upload | Read/Resolve (own team) | — | — | Read | Read |
| AP_MANAGER | Read/Upload | Read/Resolve/Escalate | Approve L1 | — | Read | Read |
| FINANCE_CONTROLLER | Read | Read/Resolve | Approve L2 | — | Full | Read |
| FINANCE_DIRECTOR | Read | Read | Approve L3 | — | Full | Read |
| CFO | Read | Read | Approve L4 | — | Full | Read |
| COMPLIANCE | Read | Read/Resolve compliance | — | — | Full | Full |
| ADMIN | Full | Full | Full | Full | Full | Full |

### Security Controls

```
All endpoints: HTTPS only · JWT Bearer required · Rate limiting 100 req/min
Upload endpoint: Virus scan first · File type allowlist · SHA-256 integrity
Secrets: Azure Key Vault · Managed Identity · No secrets in code
```

---

## DATABASE SCHEMA OVERVIEW

### Core Table Groups

```
DOCUMENTS & WORKFLOW
  documents, workflows, workflow_states (LangGraph checkpoints),
  agent_execution_logs

EXTRACTED DATA
  invoice_extractions, line_items, validation_results

MASTER DATA
  vendors, purchase_orders, grn_records, employees

EXCEPTIONS & APPROVALS
  exceptions, exception_history, approvals, approval_matrix

CONFIGURATION
  config_entries, prompt_versions, business_rules

AUDIT
  audit_logs (immutable, append-only, no UPDATE/DELETE permissions)
  notifications_log

USERS
  users, user_roles, user_delegates
```

### Key Design Decisions

| Decision | Reason |
|---|---|
| `tenant_id` on every table | Multi-tenancy without schema separation |
| `audit_logs` append-only | Immutability enforced at DB level |
| `workflow_states` for LangGraph | Native PostgreSQL checkpointer — enables interrupt/resume |
| `config_entries` overrides YAML | Live config changes without restart |
| `prompt_versions` in DB | Prompt activation/rollback via API without deployment |

---

## TESTING STRATEGY

### Test Pyramid

```
E2E (5%)           ← Full pipeline: upload → payment
Integration (25%)  ← Agent + real DB + real tools
Unit (70%)         ← One test per tool method, no DB, no LLM
```

### Tool Testability Guarantee

Because all tools are stateless and dependency-injected:
- No LangGraph required to test a tool
- No agent required to test a tool
- No HTTP required to test a tool
- Inject mock LLM client / mock repository → pure input/output assertion

---

## MIGRATION PLAN

### Phase 1: Structural Reorganisation (1–2 weeks)
Move business logic from agents into tools. Agents call same functions, just relocated. Zero behaviour change.

### Phase 2: LangGraph Wrapping (1–2 weeks)
Wrap existing Celery tasks inside LangGraph nodes. Adds: checkpoint storage, interrupt/resume, conditional routing.

### Phase 3: Config & Prompt Externalisation (1 week)
Extract all hardcoded thresholds into YAML. Extract prompts into versioned YAML files. Code reads via `ConfigurationTool` and `PromptTool`.

### Phase 4: Azure Deployment (1 week)
Remove Docker Compose. Deploy to Azure App Service, Static Web Apps, Container Apps. Migrate storage → Blob, secrets → Key Vault.

### Phase 5: Platform Hardening (ongoing)
Per-tenant configuration, prompt versioning UI, explainability API endpoints, structured agent execution logging.

Each phase is independently deployable and testable. The pipeline is never broken during transition.

---

## ARCHITECTURE DECISION RECORD (ADR) SUMMARY

| Decision | Choice | Rationale |
|---|---|---|
| Orchestration | LangGraph | Native interrupt/resume, state checkpointing, conditional routing |
| State Management | Single WorkflowState | Single source of truth prevents inconsistency between agents |
| Business Logic Location | Tools only | Agents with logic cannot be independently tested or replaced |
| Config Format | YAML + Pydantic | YAML readable by non-engineers; Pydantic enforces type safety |
| ERP Abstraction | Provider interface | Swapping ERP requires zero changes to agents or tools |
| Prompt Versioning | YAML files + DB version table | Rollback in seconds without code deployment |
| Async Processing | Celery + Azure Service Bus | Decouples API response time; durable delivery |
| Storage | Azure Blob | Eliminates local disk dependency; enables horizontal scaling |
| Deployment | Azure App Service + Container Apps | Fully managed; auto-scaling; no container orchestration |
| Secrets | Azure Key Vault + Managed Identity | No secrets in code; zero credential rotation risk |
