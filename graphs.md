# Enterprise AI Agent Platform — LangGraph Graph Specifications

> **Document Purpose**: Complete specification of all 6 LangGraph graphs orchestrating the AP Automation Platform.
> Each graph is a state machine that owns a segment of the invoice lifecycle.
> Graphs communicate via WorkflowState. No graph calls another graph directly — inter-graph
> communication is managed by the LangGraph checkpointer and FastAPI resume endpoints.
>
> **Source of truth**: `ARCHITECTURE.md` (Section 3 — Graph Designs), `agents.md` (agent specs)

---

## Table of Contents

1. [Graph Architecture Overview](#1-graph-architecture-overview)
2. [Graph 1 — InvoiceProcessingGraph](#2-graph-1--invoiceprocessinggraph)
3. [Graph 2 — ExceptionGraph](#3-graph-2--exceptiongraph)
4. [Graph 3 — HumanReviewGraph](#4-graph-3--humanreviewgraph)
5. [Graph 4 — ApprovalGraph](#5-graph-4--approvalgraph)
6. [Graph 5 — RetryGraph](#6-graph-5--retrygraph)
7. [Graph 6 — NotificationGraph](#7-graph-6--notificationgraph)
8. [Human-in-the-Loop Strategy](#8-human-in-the-loop-strategy)
9. [Graph Responsibilities Table](#9-graph-responsibilities-table)
10. [Design Rules](#10-design-rules)

---

## 1. Graph Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LANGGRAPH PLATFORM TOPOLOGY                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   InvoiceProcessingGraph                             │   │
│  │  upload → classify → ocr → extract → validate → profile →           │   │
│  │  profile_validate → match_po → match_grn → match_3way →             │   │
│  │  confidence → [ROUTE] → erp_post → payment → END                    │   │
│  └────────────┬──────────────────┬──────────────┬───────────────────── ┘   │
│               │ exception route  │ review route  │ approval route           │
│               ▼                  ▼               ▼                          │
│  ┌────────────────────┐  ┌───────────────┐  ┌────────────────────┐        │
│  │  ExceptionGraph    │  │HumanReviewGraph│  │  ApprovalGraph     │        │
│  │  exception →       │  │ human_review → │  │  approve →         │        │
│  │  assign → notify   │  │ [interrupt] →  │  │  [interrupt] →     │        │
│  │  → [wait resolve]  │  │ resume → route │  │  resume → route    │        │
│  └────────────────────┘  └───────────────┘  └────────────────────┘        │
│                                                                              │
│  ┌────────────────────┐  ┌─────────────────────────────────────────┐       │
│  │    RetryGraph      │  │          NotificationGraph               │       │
│  │  retry → [backoff] │  │  notify → render → dispatch → record    │       │
│  │  → re-enqueue      │  │                                          │       │
│  └────────────────────┘  └─────────────────────────────────────────┘       │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  PostgreSQL Checkpointer (LangGraph StateStore)                       │  │
│  │  • Persists WorkflowState at every interrupt point                   │  │
│  │  • Enables workflow resume across process restarts                   │  │
│  │  • Thread-safe per document_id                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Shared Conventions Across All Graphs

| Convention | Value |
|---|---|
| State class | `WorkflowState` (single Pydantic model, all graphs) |
| Checkpointer | `PostgresSaver` (LangGraph built-in, Azure PostgreSQL Flexible Server) |
| Interrupt mechanism | `langgraph.checkpoint.interrupt()` |
| Resume endpoint | `POST /api/v1/workflows/{document_id}/resume` |
| Review endpoint | `GET /api/v1/workflows/{document_id}/review` |
| Thread ID | `document_id` (unique per invoice) |
| Config key | `configurable["thread_id"]` = `document_id` |
| Error state | `workflow.status = ERROR` with `workflow.error_code` populated |
| Audit on every node | Every node calls AuditTool before returning |

---

## 2. Graph 1 — InvoiceProcessingGraph

### Purpose
The primary orchestration graph that drives an invoice from initial upload through OCR, extraction, validation, matching, and posting to payment scheduling. It is the spine of the platform — every other graph branches off it via conditional routing.

### Start Node
`upload`

### End Node
`payment` (on happy path) | `END` node after error terminal conditions

### Nodes

| Node ID | Agent | Description |
|---|---|---|
| `upload` | UploadAgent | Accept, validate, and store the incoming document |
| `classify` | ClassificationAgent | Determine document class and OCR strategy |
| `ocr` | OCRAgent | Convert images to text (skipped for DIGITAL) |
| `extract` | ExtractionAgent | LLM-based structured data extraction |
| `validate` | ValidationAgent | Universal validation (GST, PAN, arithmetic, duplicates) |
| `profile` | BusinessProfileAgent | Assign one of 9 business profiles |
| `profile_validate` | ProfileValidationAgent | Profile-specific rule validation |
| `match_po` | POMatchingAgent | Match invoice against purchase order |
| `match_grn` | GRNMatchingAgent | Match invoice against goods receipt |
| `match_3way` | ThreeWayMatchingAgent | Combine PO+GRN into three-way verdict |
| `confidence` | ConfidenceAgent | Aggregate all signals into overall score |
| `erp_post` | ERPPostingAgent | Post journal entry to ERP |
| `payment` | PaymentAgent | Schedule payment with TDS calculation |
| `route_post_confidence` | Router (no agent) | Conditional edge: route based on confidence outcome |
| `route_post_match` | Router (no agent) | Conditional edge: route based on match disposition |

### Conditional Edges

#### Edge: `upload` → next
```
upload result
├── virus_scan = QUARANTINED  → END (reject; emit VIRUS_DETECTED)
├── validation_failed         → END (reject; emit UPLOAD_REJECTED)
└── success                   → classify
```

#### Edge: `classify` → next
```
classify result
├── document_class = UNKNOWN  → human_review (HumanReviewGraph)
├── document_class = DIGITAL  → extract       (bypass OCR)
└── document_class = SCANNED
    or HANDWRITTEN            → ocr
```

#### Edge: `ocr` → next
```
ocr result
├── avg_confidence < min_threshold  → human_review
├── empty_output                    → human_review
└── success                         → extract
```

#### Edge: `extract` → next
```
extract result
├── all mandatory fields missing    → human_review
├── token_budget_exceeded           → exception (ExceptionGraph)
└── success                         → validate
```

#### Edge: `validate` → next
```
validate result
├── duplicate_detected (CONFIRMED)  → END (reject duplicate)
├── hard_failures present           → exception (ExceptionGraph)
├── soft_failures only              → human_review
└── is_valid = True                 → profile
```

#### Edge: `profile` → next
```
profile result
├── profile_confidence < threshold  → human_review
└── profile assigned                → profile_validate
```

#### Edge: `profile_validate` → next
```
profile_validate result
├── hard_rule_violation             → exception (ExceptionGraph)
└── is_valid = True                 → match_po (if PO-type profile)
                                    → match_grn (if NON-PO but GRN required)
                                    → match_3way (if contract-based profile)
                                    → confidence (if PETTY_CASH / EMPLOYEE_REIMBURSEMENT)
```

#### Edge: `match_po` → next
```
match_po result
├── po_status = NOT_FOUND           → exception (queue: PROCUREMENT)
├── po_status = PARTIAL             → match_grn (continue with warning)
└── po_status = MATCHED             → match_grn
```

#### Edge: `match_grn` → next
```
match_grn result
├── grn_status = NOT_FOUND          → exception (queue: WAREHOUSE)
├── grn_status = PARTIAL            → match_3way (continue with variance)
└── grn_status = MATCHED            → match_3way
```

#### Edge: `match_3way` (route_post_match) → next
```
match_3way result
├── disposition = FAILED_MATCH      → exception (ExceptionGraph)
├── disposition = PARTIAL_MATCH     → confidence (flag for human review)
└── disposition = FULL_MATCH        → confidence
```

#### Edge: `confidence` (route_post_confidence) → next
```
confidence result
├── confidence_band = CRITICAL      → human_review
├── confidence_band = LOW           → human_review
├── requires_human_review = True    → human_review (HumanReviewGraph)
├── auto_approve_eligible = True    → erp_post (bypass ApprovalGraph)
└── approval_required = True        → approve (ApprovalGraph)
```

#### Edge: `erp_post` → next
```
erp_post result
├── posting_status = FAILED         → exception (ExceptionGraph)
├── budget_exceeded                 → exception (queue: FINANCE)
└── posting_status = POSTED         → payment
```

#### Edge: `payment` → next
```
payment result
├── payment_failed                  → exception (ExceptionGraph)
└── payment_scheduled               → END (notify via NotificationGraph)
```

### Interrupt Points

| Interrupt ID | Trigger Condition | Resume Endpoint |
|---|---|---|
| `REVIEW_CLASSIFICATION_UNKNOWN` | `classification.document_class = UNKNOWN` | `POST /workflows/{id}/resume` |
| `REVIEW_OCR_LOW_CONFIDENCE` | `ocr.avg_confidence < threshold` | `POST /workflows/{id}/resume` |
| `REVIEW_EXTRACTION_LOW_CONFIDENCE` | Mandatory field confidence below threshold | `POST /workflows/{id}/resume` |
| `REVIEW_SOFT_VALIDATION_FAILURE` | Non-blocking validation warnings only | `POST /workflows/{id}/resume` |
| `REVIEW_PROFILE_LOW_CONFIDENCE` | Profile confidence below threshold | `POST /workflows/{id}/resume` |
| `REVIEW_PARTIAL_MATCH` | Three-way match is PARTIAL | `POST /workflows/{id}/resume` |
| `REVIEW_CONFIDENCE_LOW` | Overall confidence band is LOW or CRITICAL | `POST /workflows/{id}/resume` |

### Resume Logic

When a reviewer POSTs to `/api/v1/workflows/{document_id}/resume`:
1. FastAPI validates reviewer has `INVOICE_REVIEW` permission
2. The request body contains `ReviewDecision` with: `decision`, `corrections`, `resume_node`, `comments`
3. FastAPI calls `graph.invoke(command=Command(resume=decision), config={"configurable": {"thread_id": document_id}})`
4. LangGraph restores state from PostgreSQL checkpointer
5. Corrections in `ReviewDecision.corrections` are merged into WorkflowState
6. Graph resumes from the node specified in `resume_node`
7. AuditTool records the resumption with reviewer identity

### Failure Paths

| Failure | Path |
|---|---|
| Any agent raises AgentException | Caught by graph error handler → `exception` node |
| Retry agent reports RETRY_EXHAUSTED | → `exception` node with severity CRITICAL |
| Approval rejected | → `END` with status REJECTED; notify submitter |
| ERP posting permanently failed | → `exception` node; payment put on HOLD |

### Retry Behaviour
- Each agent declares its own retry policy (see `agents.md`)
- InvoiceProcessingGraph does not implement graph-level retries
- On agent retry exhaustion, the graph routes to ExceptionGraph

### State Updates (summary of fields written per node)

| Node | WorkflowState sections written |
|---|---|
| `upload` | `document.*`, `workflow.status=UPLOADED` |
| `classify` | `classification.*`, `workflow.status=CLASSIFIED` |
| `ocr` | `ocr.*`, `workflow.status=OCR_COMPLETE` |
| `extract` | `invoice.*`, `extraction.*`, `workflow.status=EXTRACTED` |
| `validate` | `validation.*`, `workflow.status=VALIDATED or VALIDATION_FAILED` |
| `profile` | `profile.*`, `workflow.status=PROFILED` |
| `profile_validate` | `profile_validation.*`, `workflow.status=PROFILE_VALIDATED` |
| `match_po` | `matching.po_*`, `workflow.status=PO_MATCHED` |
| `match_grn` | `matching.grn_*`, `workflow.status=GRN_MATCHED` |
| `match_3way` | `matching.three_way_*`, `matching.match_disposition` |
| `confidence` | `confidence.*`, `routing.*`, `workflow.status=CONFIDENCE_SCORED` |
| `erp_post` | `erp.*`, `workflow.status=ERP_POSTED` |
| `payment` | `payment.*`, `workflow.status=PAYMENT_SCHEDULED` |

### ASCII Flow Diagram

```
                              ┌─────────┐
                              │  START  │
                              └────┬────┘
                                   │
                              ┌────▼────┐
                              │ upload  │
                              └────┬────┘
                     ┌─────────────┼──────────────┐
                     │             │              │
                  VIRUS         INVALID        SUCCESS
                     │             │              │
                    END           END       ┌─────▼──────┐
                                            │  classify  │
                                            └─────┬──────┘
                              ┌──────────────┬────┴──────────────┐
                              │              │                    │
                           UNKNOWN        DIGITAL           SCANNED/HW
                              │              │                    │
                              ▼              │              ┌─────▼──────┐
                        [human_review]       │              │    ocr     │
                              │              │              └─────┬──────┘
                              └──────────────┤       LOW_CONF/EMPTY│
                                             │              ┌─────▼──────┐
                                             │              │[human_rev] │
                                             │              └─────┬──────┘
                                             │                    │
                                        ┌────▼────────────────────▼───┐
                                        │          extract             │
                                        └─────────────┬───────────────┘
                                        ┌─────────────┼──────────────┐
                                     MISSING       TOKEN_OVER      SUCCESS
                                        │             │               │
                                   [human_rev]   [exception]   ┌─────▼──────┐
                                                               │  validate  │
                                                               └─────┬──────┘
                              ┌──────────────┬────────────┬──────────┤
                           DUPLICATE     HARD_FAIL    SOFT_FAIL    VALID
                              │             │             │           │
                             END      [exception]  [human_rev]  ┌────▼────┐
                                                                │ profile │
                                                                └────┬────┘
                                                          LOW_CONF   │  OK
                                                               │     │
                                                         [human_rev] │
                                                                ┌────▼──────────┐
                                                                │profile_validate│
                                                                └────┬──────────┘
                                                        HARD_FAIL    │     OK
                                                             │        │
                                                       [exception]  ┌─▼───────┐
                                                                    │ match_po│ ◄── (PO profiles)
                                                                    └────┬────┘
                                                             NOT_FOUND   │  MATCHED/PARTIAL
                                                                  │      │
                                                            [exception]  │
                                                                    ┌────▼─────┐
                                                                    │match_grn │ ◄── (GRN profiles)
                                                                    └────┬─────┘
                                                             NOT_FOUND   │  MATCHED/PARTIAL
                                                                  │      │
                                                            [exception]  │
                                                                    ┌────▼──────┐
                                                                    │match_3way │
                                                                    └────┬──────┘
                                                              FAILED     │  PARTIAL/FULL
                                                                  │      │
                                                            [exception]  │
                                                                    ┌────▼──────┐
                                                                    │confidence │
                                                                    └────┬──────┘
                                ┌───────────────────────┬──────────────┬──┘
                             CRITICAL/LOW           AUTO_APPROVE   APPROVAL_REQ
                                │                       │               │
                           [human_rev]             ┌────▼────┐   [ApprovalGraph]
                                │                  │erp_post │         │
                                └──────────────────►         ◄─────────┘
                                                   └────┬────┘
                                                FAILED   │  POSTED
                                                   │     │
                                             [exception] │
                                                    ┌────▼────┐
                                                    │ payment │
                                                    └────┬────┘
                                                FAILED   │  SCHEDULED
                                                   │     │
                                             [exception] ▼
                                                        END
```

---

## 3. Graph 2 — ExceptionGraph

### Purpose
Classify, assign, track, and manage resolution of all exceptions raised during invoice processing. An exception is any condition that prevents straight-through processing and requires human intervention or system escalation.

### Start Node
`exception_classify`

### End Node
`exception_resolved` (when exception is resolved) | `exception_escalated` (SLA breach)

### Nodes

| Node ID | Agent | Description |
|---|---|---|
| `exception_classify` | ExceptionAgent | Classify exception type and severity |
| `exception_assign` | ExceptionAgent | Assign to correct queue and user |
| `exception_notify` | NotificationAgent | Notify responsible team |
| `exception_wait` | Router (interrupt) | Checkpoint; wait for human resolution input |
| `exception_evaluate` | ExceptionAgent | Evaluate resolution attempt |
| `exception_retry` | RetryAgent | Trigger retry if resolution is auto-fix |
| `exception_resolved` | AuditAgent | Record resolution; resume main graph |
| `exception_escalate` | ExceptionAgent | Escalate on SLA breach |

### Conditional Edges

#### Edge: `exception_classify` → next
```
severity
├── CRITICAL    → exception_assign (bypass standard routing; alert admin immediately)
└── HIGH/MED/LOW → exception_assign
```

#### Edge: `exception_assign` → next
```
always → exception_notify
```

#### Edge: `exception_notify` → next
```
always → exception_wait  (interrupt: wait for human to resolve)
```

#### Edge: `exception_wait` (resume) → next
```
resolution_input
├── resolution_type = AUTO_FIX     → exception_retry
├── resolution_type = MANUAL_FIX   → exception_evaluate
├── resolution_type = OVERRIDE     → exception_resolved
└── resolution_type = REJECT       → exception_resolved (with REJECTED outcome)
```

#### Edge: `exception_evaluate` → next
```
evaluation result
├── resolution_valid   → exception_resolved
└── resolution_invalid → exception_assign (re-assign for another attempt)
```

#### Edge: `exception_retry` → next
```
retry result
├── retry_succeeded    → exception_resolved
└── retry_failed       → exception_assign (escalate or re-assign)
```

#### Edge: `exception_escalate` → next
```
always → exception_notify (notify escalation target)
         → exception_wait (wait again with escalation deadline)
```

### Interrupt Points

| Interrupt ID | Trigger | Resume Endpoint |
|---|---|---|
| `EXCEPTION_AWAITING_RESOLUTION` | After assignment and notification | `POST /workflows/{id}/exceptions/{exc_id}/resolve` |
| `EXCEPTION_ESCALATION_PENDING` | After SLA breach escalation | `POST /workflows/{id}/exceptions/{exc_id}/resolve` |

### Resume Logic
1. Resolver POSTs to `/api/v1/workflows/{document_id}/exceptions/{exception_id}/resolve`
2. Request body: `ExceptionResolution` with `resolution_type`, `resolution_notes`, `corrected_fields`
3. FastAPI validates resolver has permission for the assigned queue
4. LangGraph resumes ExceptionGraph from `exception_wait` node
5. `resolution_type = OVERRIDE` skips re-processing; `AUTO_FIX` triggers RetryGraph

### Failure Paths

| Failure | Path |
|---|---|
| SLA deadline reached without resolution | → `exception_escalate` node |
| Escalation also unresolved | → Emit CRITICAL alert; escalate to platform admin |
| Exception resolution invalid | → Re-assign to same or different queue |

### Retry Behaviour
- ExceptionGraph does not retry itself
- It delegates retries to RetryGraph via the `exception_retry` node

### State Updates

| Node | WorkflowState sections written |
|---|---|
| `exception_classify` | `exception.exception_type`, `exception.severity` |
| `exception_assign` | `exception.assigned_queue`, `exception.assigned_to`, `exception.sla_deadline` |
| `exception_notify` | `notifications.sent` |
| `exception_evaluate` | `exception.resolution_status` |
| `exception_resolved` | `exception.resolution_status=RESOLVED`, `workflow.status=EXCEPTION_RESOLVED` |
| `exception_escalate` | `exception.escalation_level++`, `exception.escalated_to` |

### ASCII Flow Diagram

```
                        ┌────────────┐
                        │   START    │
                        └─────┬──────┘
                               │
                    ┌──────────▼──────────┐
                    │ exception_classify  │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  exception_assign   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  exception_notify   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   exception_wait    │ ◄─────────── SLA timer
                    │  [INTERRUPT POINT]  │                 │
                    └──────────┬──────────┘          SLA_BREACH
                               │                           │
            ┌──────────────────┼────────────────┐    ┌────▼───────────────┐
         AUTO_FIX         MANUAL_FIX         OVERRIDE  │ exception_escalate│
            │                  │                │    └────────────────────┘
            │                  │                │
    ┌───────▼──────┐  ┌────────▼──────┐   ┌────▼────────────┐
    │exception_retry│  │exception_eval │   │exception_resolved│
    └───────┬───────┘  └────────┬──────┘   └─────────────────┘
    SUCCEED  │ FAIL    VALID │  INVALID
        │    │           │       │
        │    └──►assign  │  assign◄┘
        │            ▲   │
        └────────────┘   │
                         ▼
              ┌──────────────────────┐
              │  exception_resolved  │
              └──────────────────────┘
```

---

## 4. Graph 3 — HumanReviewGraph

### Purpose
Pause the invoice processing workflow at a deterministic checkpoint, present flagged issues and full invoice context to a qualified reviewer, collect the reviewer's decision and corrections, and resume the appropriate stage of InvoiceProcessingGraph.

### Start Node
`review_prepare`

### End Node
`review_resume` (routes back into InvoiceProcessingGraph at the correct node)

### Nodes

| Node ID | Agent | Description |
|---|---|---|
| `review_prepare` | HumanReviewAgent | Prepare review context; identify flagged issues |
| `review_assign` | HumanReviewAgent | Assign review task to qualified reviewer |
| `review_notify` | NotificationAgent | Send review request to reviewer |
| `review_wait` | Router (interrupt) | LangGraph interrupt; state checkpointed to PostgreSQL |
| `review_validate` | HumanReviewAgent | Validate reviewer's input completeness |
| `review_apply` | HumanReviewAgent | Apply corrections to WorkflowState |
| `review_resume` | HumanReviewAgent | Determine resume node; hand back to InvoiceProcessingGraph |
| `review_escalate` | HumanReviewAgent | Escalate if SLA breached |

### Conditional Edges

#### Edge: `review_prepare` → next
```
always → review_assign
```

#### Edge: `review_assign` → next
```
always → review_notify
```

#### Edge: `review_notify` → next
```
always → review_wait  (LangGraph interrupt checkpoint)
```

#### Edge: `review_wait` (resume input) → next
```
reviewer_decision
├── decision = APPROVED              → review_apply (no corrections needed)
├── decision = CORRECTED             → review_apply (apply field corrections)
├── decision = REJECTED              → review_resume (resume with REJECTED status)
└── decision = ESCALATE              → review_escalate
```

#### Edge: `review_validate` → next
```
validation result
├── input_valid    → review_apply
└── input_invalid  → review_wait (re-prompt reviewer for correction)
```

#### Edge: `review_apply` → next
```
always → review_resume
```

#### Edge: `review_resume` → next
```
resume_node determination
├── corrections_include_extraction_fields → resume at `validate` (re-run validation)
├── corrections_include_match_fields      → resume at `match_po` (re-run matching)
├── corrections_include_profile_fields    → resume at `profile` (re-run profiling)
├── decision = APPROVED (no corrections) → resume at node after the interrupt trigger
└── decision = REJECTED                  → END (workflow terminated)
```

#### Edge: `review_escalate` → next
```
always → review_notify (notify escalation target)
         → review_wait  (wait again with shortened deadline)
```

### Interrupt Points

| Interrupt ID | Trigger | Resume Endpoint |
|---|---|---|
| `REVIEW_AWAITING_DECISION` | After reviewer is notified | `POST /api/v1/workflows/{id}/resume` |
| `REVIEW_ESCALATION_PENDING` | After escalation notification | `POST /api/v1/workflows/{id}/resume` |

### Resume Logic
1. Reviewer calls `GET /api/v1/workflows/{document_id}/review` to get review context
2. Context includes: flagged fields, confidence scores, validation errors, match variances, original invoice data
3. Reviewer submits `POST /api/v1/workflows/{document_id}/resume` with `ReviewDecision`:
   ```
   {
     "decision": "CORRECTED",
     "corrections": { "invoice.vendor_name": "Corrected Vendor Ltd" },
     "resume_node": "validate",
     "comments": "Vendor name was OCR error"
   }
   ```
4. FastAPI validates `INVOICE_REVIEW` permission on reviewer's identity
5. LangGraph restores WorkflowState from PostgreSQL checkpointer
6. `review_apply` merges corrections into WorkflowState
7. `review_resume` routes back to InvoiceProcessingGraph at `resume_node`

### Failure Paths

| Failure | Path |
|---|---|
| Review SLA breached | → `review_escalate` → senior reviewer |
| Reviewer submits invalid corrections | → Re-present review form |
| Checkpoint restoration fails | → Alert platform admin; document enters STUCK state |

### Retry Behaviour
- HumanReviewGraph does not retry automatically
- The reviewer may re-submit corrections if initial input is invalid

### State Updates

| Node | WorkflowState sections written |
|---|---|
| `review_prepare` | `human_review.flagged_fields`, `human_review.review_context` |
| `review_assign` | `human_review.reviewer_id`, `human_review.review_deadline` |
| `review_apply` | All corrected fields in their original sections; `human_review.corrections` |
| `review_resume` | `human_review.review_decision`, `human_review.reviewed_at`, `human_review.resume_node` |
| `review_escalate` | `human_review.escalated_to`, `human_review.escalation_deadline` |

### ASCII Flow Diagram

```
                     ┌───────────────┐
                     │     START     │
                     └───────┬───────┘
                              │
                  ┌───────────▼───────────┐
                  │    review_prepare     │
                  │  (build review pack)  │
                  └───────────┬───────────┘
                              │
                  ┌───────────▼───────────┐
                  │     review_assign     │
                  └───────────┬───────────┘
                              │
                  ┌───────────▼───────────┐
                  │     review_notify     │
                  └───────────┬───────────┘
                              │
                  ┌───────────▼───────────┐
                  │      review_wait      │ ◄── SLA timer
                  │   [INTERRUPT POINT]   │         │
                  └───────────┬───────────┘    SLA_BREACH
                              │                     │
          ┌───────────────────┼──────────┐   ┌──────▼──────────┐
       APPROVED           CORRECTED  REJECTED │review_escalate  │
          │                   │          │   └─────────────────┘
          │              ┌────▼─────┐    │
          │              │review_val│    │
          │              └────┬─────┘    │
          │           VALID   │ INVALID  │
          │              │    └──►wait   │
          │         ┌────▼──────────┐    │
          └────────►│ review_apply  │    │
                    └────┬──────────┘    │
                         │               │
                    ┌────▼──────────┐    │
                    │ review_resume │◄───┘
                    └────┬──────────┘
                         │
                         ▼
              Resume InvoiceProcessingGraph
              at determined resume_node
```

---

## 5. Graph 4 — ApprovalGraph

### Purpose
Implement the multi-level approval workflow for invoices that require explicit human authorisation before ERP posting. Approval levels, authorities, and SLAs are entirely configuration-driven — no code changes are required when the approval matrix changes.

### Start Node
`approval_prepare`

### End Node
`approval_complete` (APPROVED or REJECTED)

### Nodes

| Node ID | Agent | Description |
|---|---|---|
| `approval_prepare` | ApprovalAgent | Load approval matrix; create approval record |
| `approval_request` | ApprovalAgent | Create approval task for current level |
| `approval_notify` | NotificationAgent | Notify approver with invoice details |
| `approval_wait` | Router (interrupt) | LangGraph interrupt; wait for approver decision |
| `approval_record` | ApprovalAgent | Record approver decision |
| `approval_check_levels` | ApprovalAgent | Determine if more levels required |
| `approval_complete` | ApprovalAgent | Finalise approval decision; resume main graph |
| `approval_escalate` | ApprovalAgent | Escalate if SLA breached |
| `approval_reject_path` | ApprovalAgent | Handle rejection — notify submitter, close workflow |

### Conditional Edges

#### Edge: `approval_prepare` → next
```
always → approval_request (level 1)
```

#### Edge: `approval_request` → next
```
always → approval_notify
```

#### Edge: `approval_notify` → next
```
always → approval_wait  (LangGraph interrupt)
```

#### Edge: `approval_wait` (resume input) → next
```
approver_decision
├── decision = APPROVED   → approval_record
├── decision = REJECTED   → approval_reject_path
├── decision = DELEGATE   → approval_request (re-assign to delegate)
└── (timeout)             → approval_escalate
```

#### Edge: `approval_record` → next
```
always → approval_check_levels
```

#### Edge: `approval_check_levels` → next
```
levels check
├── more_levels_required = True  → approval_request (next level)
└── all_levels_approved = True   → approval_complete
```

#### Edge: `approval_complete` → next
```
always → [resume InvoiceProcessingGraph at `erp_post`]
```

#### Edge: `approval_reject_path` → next
```
always → approval_complete (with REJECTED status)
         → [InvoiceProcessingGraph END with REJECTED]
```

#### Edge: `approval_escalate` → next
```
always → approval_notify (notify escalation target = manager of original approver)
         → approval_wait  (wait with shortened SLA deadline)
```

### Interrupt Points

| Interrupt ID | Approver Context | Resume Endpoint |
|---|---|---|
| `APPROVAL_L1_PENDING` | Level 1 approver notified | `POST /api/v1/workflows/{id}/approve` |
| `APPROVAL_L2_PENDING` | Level 2 approver notified | `POST /api/v1/workflows/{id}/approve` |
| `APPROVAL_LN_PENDING` | Level N approver notified | `POST /api/v1/workflows/{id}/approve` |
| `APPROVAL_ESCALATION_PENDING` | Escalated approver notified | `POST /api/v1/workflows/{id}/approve` |

### Resume Logic
1. Approver calls `GET /api/v1/workflows/{document_id}/approval` to get approval pack
2. Pack includes: invoice summary, match results, confidence score, GL account proposal, risk flags
3. Approver submits `POST /api/v1/workflows/{document_id}/approve`:
   ```
   {
     "decision": "APPROVED",
     "comments": "Reviewed and approved per procurement policy",
     "approver_id": "user_123"
   }
   ```
4. FastAPI verifies approver has authority for the invoice amount and profile
5. ApprovalGraph resumes from `approval_wait`
6. `approval_record` commits decision to `approval_decisions` table
7. `approval_check_levels` determines if more levels are needed

### Failure Paths

| Failure | Path |
|---|---|
| Approval SLA breached | → `approval_escalate` |
| Approver not found or inactive | → Escalate to AP_TEAM immediately |
| Rejection at any level | → Terminate workflow with REJECTED status |

### Retry Behaviour
- ApprovalGraph does not retry — human decisions are not retried
- SLA breach triggers escalation, not retry

### State Updates

| Node | WorkflowState sections written |
|---|---|
| `approval_prepare` | `approval.approval_id`, `approval.approval_levels` |
| `approval_request` | `approval.current_level` |
| `approval_record` | `approval.decisions` (append) |
| `approval_complete` | `approval.final_decision`, `approval.approved_at` |
| `approval_reject_path` | `approval.final_decision=REJECTED`, `approval.rejection_reason` |
| `approval_escalate` | `approval.escalation_level`, `approval.escalated_to` |

### ASCII Flow Diagram

```
                      ┌──────────────┐
                      │    START     │
                      └──────┬───────┘
                              │
               ┌──────────────▼──────────────┐
               │       approval_prepare      │
               │  (load matrix, create record)│
               └──────────────┬──────────────┘
                               │
               ┌───────────────▼─────────────┐
         ┌────►│      approval_request       │
         │     │  (assign to level N approver)│
         │     └───────────────┬─────────────┘
         │                     │
         │     ┌───────────────▼─────────────┐
         │     │      approval_notify        │
         │     └───────────────┬─────────────┘
         │                     │
         │     ┌───────────────▼─────────────┐
         │     │       approval_wait         │ ◄── SLA timer
         │     │     [INTERRUPT POINT]       │          │
         │     └───────────────┬─────────────┘     SLA_BREACH
         │                     │                        │
         │    ┌────────┬────────┼────────┐        ┌─────▼───────────┐
         │ DELEGATE APPROVED REJECTED (TO)         │approval_escalate│
         │    │        │        │                 └─────────────────┘
         │    │   ┌────▼────┐   │
         │    │   │ record  │   │
         │    │   └────┬────┘   │
         │    │        │        │
         │    │  ┌─────▼──────┐ │
         │    │  │check_levels│ │
         │    │  └─────┬──────┘ │
         │    │   MORE  │  ALL   │
         │    └─────────┘  ▼    │
         │           ┌──────────┐│
         └───────────┤ complete ││
                     └────┬─────┘│
                          │      │ REJECTED
                          ▼      ▼
                    Resume at   reject_path
                    erp_post     │
                              END (REJECTED)
```

---

## 6. Graph 5 — RetryGraph

### Purpose
Manage the complete retry lifecycle for any failed operation in the platform. Implements configurable backoff strategies, enforces maximum retry limits per operation type, and escalates to ExceptionGraph when the retry budget is exhausted.

### Start Node
`retry_assess`

### End Node
`retry_success` (operation succeeded) | `retry_escalate` (max retries exhausted)

### Nodes

| Node ID | Agent | Description |
|---|---|---|
| `retry_assess` | RetryAgent | Assess failure; determine if retryable |
| `retry_schedule` | RetryAgent | Compute next retry time using backoff strategy |
| `retry_wait` | Router | Wait for backoff duration (async sleep via queue) |
| `retry_execute` | RetryAgent | Re-enqueue failed operation for execution |
| `retry_check` | RetryAgent | Check if operation succeeded after re-execution |
| `retry_success` | RetryAgent | Record success; resume original graph |
| `retry_escalate` | RetryAgent | Max retries exhausted; route to ExceptionGraph |

### Conditional Edges

#### Edge: `retry_assess` → next
```
failure assessment
├── error_type is non-retryable  → retry_escalate (immediately)
├── retry_count >= max_retries   → retry_escalate
└── error_type is retryable      → retry_schedule
```

#### Edge: `retry_schedule` → next
```
always → retry_wait
```

#### Edge: `retry_wait` → next
```
always → retry_execute  (after backoff delay expires)
```

#### Edge: `retry_execute` → next
```
always → retry_check
```

#### Edge: `retry_check` → next
```
execution result
├── succeeded          → retry_success
├── failed (retryable) → retry_assess (increment count; re-assess)
└── failed (non-ret)   → retry_escalate
```

### Backoff Strategies

| Strategy | Formula | Config Key |
|---|---|---|
| Exponential | `base_delay * 2^attempt` | `retry.backoff_strategy = EXPONENTIAL` |
| Exponential + Jitter | `base_delay * 2^attempt * random(0.5, 1.5)` | `retry.backoff_strategy = EXPONENTIAL_JITTER` |
| Linear | `base_delay * attempt` | `retry.backoff_strategy = LINEAR` |
| Fixed | `base_delay` (constant) | `retry.backoff_strategy = FIXED` |

### Interrupt Points
RetryGraph has no human interrupt points — it is fully automated.

### Failure Paths

| Failure | Path |
|---|---|
| Max retries exhausted | → `retry_escalate` → ExceptionGraph |
| Non-retryable error | → `retry_escalate` immediately |

### State Updates

| Node | WorkflowState sections written |
|---|---|
| `retry_assess` | `retry.attempt_number`, `workflow.failed_agent` |
| `retry_schedule` | `retry.next_retry_at`, `retry.backoff_seconds` |
| `retry_success` | `retry.escalated=False`, `workflow.status` restored |
| `retry_escalate` | `retry.escalated=True`, `workflow.status=RETRY_EXHAUSTED` |

### ASCII Flow Diagram

```
                    ┌──────────────┐
                    │    START     │
                    └──────┬───────┘
                            │
               ┌────────────▼────────────┐
               │      retry_assess       │
               └────────────┬────────────┘
                             │
              NON-RETRYABLE  │  MAX_EXCEEDED  │  RETRYABLE
                    │        │       │         │
                    │        ▼       │         │
              ┌─────▼──────────────┐ │  ┌──────▼──────────┐
              │   retry_escalate   │◄┘  │  retry_schedule  │
              └────────────────────┘    └──────┬──────────┘
                                                │
                                         ┌──────▼──────────┐
                                         │   retry_wait     │
                                         │ (backoff delay)  │
                                         └──────┬──────────┘
                                                │
                                         ┌──────▼──────────┐
                                         │  retry_execute   │
                                         └──────┬──────────┘
                                                │
                                         ┌──────▼──────────┐
                                         │   retry_check    │
                                         └──────┬──────────┘
                                    ┌───────────┼───────────┐
                                 SUCCESS    RETRYABLE   NON-RET
                                    │        FAIL          │
                            ┌───────▼───┐      │     ┌─────▼──────┐
                            │retry_succ │   assess◄──│retry_escalate│
                            └───────────┘  (loop)   └────────────┘
```

---

## 7. Graph 6 — NotificationGraph

### Purpose
Decouple notification dispatch from business logic by providing a dedicated asynchronous graph that handles template rendering, channel selection, delivery, and retry for all platform notifications.

### Start Node
`notify_prepare`

### End Node
`notify_complete`

### Nodes

| Node ID | Agent | Description |
|---|---|---|
| `notify_prepare` | NotificationAgent | Determine recipients and select template |
| `notify_render` | NotificationAgent | Render template with event data; mask PII |
| `notify_channel_select` | NotificationAgent | Select delivery channels per recipient preferences |
| `notify_dispatch` | NotificationAgent | Send via each configured channel |
| `notify_verify` | NotificationAgent | Verify delivery status (where channel supports it) |
| `notify_retry` | RetryAgent | Retry failed channel dispatches |
| `notify_fallback` | NotificationAgent | Switch to fallback channel on primary failure |
| `notify_complete` | AuditAgent | Record delivery outcomes |

### Conditional Edges

#### Edge: `notify_prepare` → next
```
recipients found
├── no recipients determinable  → notify_complete (no-op, log warning)
└── recipients found            → notify_render
```

#### Edge: `notify_render` → next
```
render result
├── template_not_found  → notify_complete (log error, non-blocking)
└── rendered_ok         → notify_channel_select
```

#### Edge: `notify_channel_select` → next
```
always → notify_dispatch
```

#### Edge: `notify_dispatch` → next
```
dispatch result
├── all_succeeded          → notify_verify
├── some_failed            → notify_retry (for failed channels)
└── all_failed             → notify_fallback
```

#### Edge: `notify_retry` → next
```
retry result
├── succeeded   → notify_verify
└── exhausted   → notify_fallback
```

#### Edge: `notify_fallback` → next
```
fallback result
├── fallback_succeeded  → notify_verify
└── fallback_failed     → notify_complete (log NOTIFICATION_ALL_CHANNELS_FAILED)
```

#### Edge: `notify_verify` → next
```
always → notify_complete
```

### Interrupt Points
NotificationGraph has no human interrupt points — it is fully automated.

### Failure Paths
Notification failures are non-blocking. The graph always reaches `notify_complete` regardless of delivery success. Failures are logged and metered but do not halt business processing.

### State Updates

| Node | WorkflowState sections written |
|---|---|
| `notify_prepare` | `notifications.recipients`, `notifications.template_id` |
| `notify_dispatch` | `notifications.sent` (append per channel) |
| `notify_complete` | `notifications.last_sent_at`, `notifications.failed` |

### ASCII Flow Diagram

```
                  ┌──────────────┐
                  │    START     │
                  └──────┬───────┘
                          │
           ┌──────────────▼──────────────┐
           │        notify_prepare       │
           └──────────────┬──────────────┘
              NO RECIP     │  RECIPIENTS
                  │        │
                  ▼        │
             complete      │
                    ┌──────▼──────────────┐
                    │    notify_render     │
                    └──────┬──────────────┘
             NO TEMPLATE   │  RENDERED
                  │        │
                  ▼        │
             complete      │
                    ┌──────▼──────────────┐
                    │ notify_channel_sel  │
                    └──────┬──────────────┘
                            │
                    ┌───────▼─────────────┐
                    │   notify_dispatch    │
                    └───────┬─────────────┘
              ┌─────────────┼──────────────┐
           ALL_OK       SOME_FAIL       ALL_FAIL
              │             │               │
              │      ┌──────▼──────┐  ┌────▼──────────┐
              │      │notify_retry │  │notify_fallback │
              │      └──────┬──────┘  └────┬──────────┘
              │    OK  │ EXHAUSTED         │
              │      │  │            OK  FAIL
              │      │  └──────────►fallback
              └──────┘         │        │
                           ┌───▼────────▼──┐
                           │ notify_verify  │
                           └───────┬────────┘
                                   │
                           ┌───────▼────────┐
                           │ notify_complete │
                           └────────────────┘
```

---

## 8. Human-in-the-Loop Strategy

### Design Principles

1. **Interrupt, don't block** — When a human decision is needed, the workflow is checkpointed and released. Processing threads are freed. The workflow resumes only when the human provides input.
2. **All interrupts are durable** — LangGraph writes state to PostgreSQL before the interrupt. If the server restarts, the workflow resumes from exactly the interrupt point.
3. **Reviewers act on complete context** — The review endpoint (`GET /review`) provides all relevant state: flagged fields, confidence scores, validation errors, match variances, original document image URL.
4. **Corrections are applied before re-processing** — HumanReviewAgent merges reviewer corrections into WorkflowState and routes back to the appropriate upstream node (not always to the beginning).
5. **Minimal re-processing on correction** — If the reviewer only corrects a vendor name, the workflow resumes at `validate`, not at `upload`. The `resume_node` is chosen based on which section of WorkflowState was corrected.
6. **Audit trail is unbroken** — Every interrupt, wait, correction, and resume is recorded as an audit event with the reviewer's identity.

### Interrupt Architecture

```
  Agent detects interrupt condition
           │
           ▼
  graph.interrupt(reason=InterruptReason, review_context=context)
           │
           ▼
  LangGraph PostgresSaver checkpoints WorkflowState
           │
           ▼
  FastAPI GET /api/v1/workflows/{id}/review → returns review pack to reviewer
           │
           ▼  (human reviews; time passes)
           │
  Reviewer POSTs to /api/v1/workflows/{id}/resume with ReviewDecision
           │
           ▼
  FastAPI: validate reviewer permission → call graph.invoke(Command(resume=...))
           │
           ▼
  LangGraph restores state from PostgresSaver
           │
           ▼
  review_apply merges corrections into WorkflowState
           │
           ▼
  graph resumes at review_resume_node
```

### Review Pack Content (GET /review response)

```json
{
  "document_id": "uuid",
  "workflow_status": "UNDER_REVIEW",
  "interrupt_reason": "REVIEW_OCR_LOW_CONFIDENCE",
  "flagged_issues": [
    { "field": "invoice.vendor_name", "issue": "OCR confidence 0.45", "current_value": "Acm3 Corp" }
  ],
  "invoice": { "...all extracted fields..." },
  "confidence": { "overall_score": 0.52, "contributing_factors": [...] },
  "matching": { "po_match_score": 0.89, "grn_match_score": 0.91 },
  "document_image_url": "/api/v1/documents/{id}/image",
  "review_deadline": "2026-06-10T10:00:00Z"
}
```

### SLA Configuration

| Review Type | Default SLA | Escalation Target |
|---|---|---|
| Extraction confidence review | 24 hours | Senior AP Clerk |
| Validation failure review | 24 hours | AP Manager |
| Matching partial review | 48 hours | Finance Manager |
| Exception resolution | 48 hours | Department Head |
| Approval L1 | 24 hours | L1 Approver's Manager |
| Approval L2+ | 48 hours | CFO or Delegate |

All SLAs are configurable per tenant in `approval_config.yaml` and `review_config.yaml`.

### Permissions Matrix

| Action | Required Permission |
|---|---|
| View review pack | `INVOICE_VIEW` |
| Submit review decision | `INVOICE_REVIEW` |
| Submit approval decision | `INVOICE_APPROVE_LN` (level-specific) |
| Resolve exception | `EXCEPTION_RESOLVE_{QUEUE}` |
| Override rejection | `INVOICE_OVERRIDE` (senior only) |
| View audit trail | `AUDIT_VIEW` |

---

## 9. Graph Responsibilities Table

| Responsibility | InvoiceProc | Exception | HumanReview | Approval | Retry | Notification |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Straight-through invoice processing | ✓ | | | | | |
| OCR and data extraction | ✓ | | | | | |
| Validation and matching | ✓ | | | | | |
| ERP posting and payment | ✓ | | | | | |
| Exception classification | | ✓ | | | | |
| Exception queue assignment | | ✓ | | | | |
| Exception SLA management | | ✓ | | | | |
| Human review interrupts | | | ✓ | | | |
| Reviewer context preparation | | | ✓ | | | |
| Correction application | | | ✓ | | | |
| Multi-level approval workflow | | | | ✓ | | |
| Approval authority enforcement | | | | ✓ | | |
| Approval SLA and escalation | | | | ✓ | | |
| Automated operation retry | | | | | ✓ | |
| Backoff strategy management | | | | | ✓ | |
| Retry escalation | | | | | ✓ | |
| Notification dispatch (all events) | | | | | | ✓ |
| Channel selection and fallback | | | | | | ✓ |
| Notification delivery tracking | | | | | | ✓ |
| State persistence (all graphs) | PostgreSQL Checkpointer (shared) | | | | | |
| Audit trail (all graphs) | AuditTool called by every agent node | | | | | |

---

## 10. Design Rules

The following rules govern the design and implementation of all LangGraph graphs in this platform. These rules must be respected when adding new graphs, new nodes, or modifying existing graphs.

### DR-01 — Agents Are Nodes; Tools Are Logic
Every graph node must correspond to exactly one agent. No business logic is implemented inside graph node functions. All computation is delegated to tools via the agent.

### DR-02 — WorkflowState Is the Only Communication Channel
Graphs do not call each other directly. All inter-graph communication happens through WorkflowState fields and the PostgreSQL checkpointer. A graph can only observe state written by a prior graph; it cannot call a prior graph's methods.

### DR-03 — Conditional Edges Are Configuration-Driven
Routing decisions in conditional edges must read from WorkflowState fields, not evaluate raw data. The routing function is a pure mapping: `WorkflowState → next_node_name`. Thresholds are loaded from `ConfigurationTool`, not hardcoded in edge functions.

### DR-04 — Every Interrupt Is Durable
Before any `interrupt()` call, the current WorkflowState must be fully written to the PostgreSQL checkpointer. If the checkpointer write fails, the interrupt must not proceed — the agent must retry the write.

### DR-05 — Resume Nodes Are Declared Explicitly
The `resume_node` field in every resume request must be one of a pre-declared set of valid resume points. FastAPI must validate `resume_node` against the allowed list before invoking `graph.invoke(Command(resume=...))`. Arbitrary code injection via `resume_node` must be rejected.

### DR-06 — Audit on Every Node Exit
Every graph node must emit at least one audit event via `AuditTool` before returning control to the graph. A node that exits without an audit event is a bug.

### DR-07 — Notifications Are Always Asynchronous
Notifications must always be dispatched via NotificationGraph (asynchronous), never inline within InvoiceProcessingGraph nodes. Inline notification calls would add latency to the critical path.

### DR-08 — Failure Nodes Must Not Swallow Exceptions
Graph error handlers must record the full error (agent, error_code, stack hash) in WorkflowState before routing to the exception node. Silent failure — catching an exception without updating WorkflowState — is prohibited.

### DR-09 — No Cross-Tenant State Access
The LangGraph `thread_id` must always equal `document_id`, and `document_id` must be scoped to a single `tenant_id`. No graph operation may read or write WorkflowState for a thread_id that belongs to a different tenant.

### DR-10 — Human Review Does Not Re-Run Prior Nodes
After a human review decision, the workflow resumes at the minimum necessary node — not at the beginning. `resume_node` selection logic must choose the earliest node that depends on the corrected fields, not an earlier node.

### DR-11 — Retry Graphs Are Separate from Business Graphs
RetryGraph is the sole owner of retry logic. Individual agents declare their retry policy in config but do not implement retry loops. If an agent's tool call fails and must be retried, the agent raises `RetryableAgentException`; the graph catches it and routes to RetryGraph.

### DR-12 — Approval Decisions Are Immutable
Once an approval decision is recorded by `approval_record`, it may not be modified. A second approver reconsidering must create a new approval record. The original record remains in the audit trail.

### DR-13 — Graphs Must Be Stateless Between Runs
No graph stores state in module-level variables, class attributes, or external caches (e.g., Redis) that would survive process restart. All state lives in the PostgreSQL checkpointer or in WorkflowState. This enables horizontal scaling and zero-downtime deployments.

### DR-14 — Configuration Changes Do Not Require Graph Redeployment
Approval matrices, tolerance thresholds, SLA deadlines, confidence thresholds, retry limits, and queue assignments are all read from `ConfigurationTool` at runtime. Changing these values requires a configuration update only — no graph code changes, no redeployment.

### DR-15 — Mock ERP Is Blocked in Production
The graph node `erp_post` must call `ConfigurationTool.get("erp.allow_mock_in_production")` and halt with a `CRITICAL` audit event if the value is `True` in a production environment (`environment.name = "production"`). This check must occur before any ERP tool is invoked.

---

*End of graphs.md — Enterprise AI Agent Platform*
