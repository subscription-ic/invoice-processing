# AP Automation & P2P Platform — Script

> An AI-powered Accounts Payable platform that ingests any financial document, understands it,
> validates it against the ERP, matches it to purchase orders, routes approvals, and posts to the
> ledger — with a complete, explainable audit trail at every step.

---

## 1. The one-line pitch

"We drop in an invoice — handwritten, scanned, or digital — and the system reads it, figures out
what kind of spend it is, checks it against our purchase orders and vendor master, runs the right
validations, routes it for approval, and posts it to the books. No manual data entry, and every
decision is recorded and explainable."

---

## 2. What problem it solves

- Manual AP is slow, error-prone, and hard to audit.
- Invoices come in every format (PDF, scan, photo, handwritten).
- Different spend types (raw material, capex, opex, lease, reimbursement) need different checks.
- Fraud/duplicate/over-billing risk without 3-way matching.

Our platform automates all of it and keeps a full audit trail for compliance.

---

## 3. High-level architecture (draw this)

```
                ┌──────────────┐     upload      ┌─────────────────────────┐
   User /       │   React UI   │ ──────────────► │   FastAPI (REST API)    │
   Browser      │ (Operations  │ ◄────────────── │   - auth, documents,    │
                │   Center)    │   live status   │     vendors, approvals  │
                └──────────────┘                 └───────────┬─────────────┘
                                                             │ dispatch task
                                                             ▼
                                          ┌───────────────────────────────┐
                                          │  Redis  (message broker)       │
                                          └───────────────┬───────────────┘
                                                          │ pulls task
                                                          ▼
                                          ┌───────────────────────────────┐
                                          │  Celery Worker (the brain)     │
                                          │  runs 12 AI agents in sequence │
                                          │  ── GPT-4o for AI steps        │
                                          └───────────────┬───────────────┘
                                                          │ read/write
                                                          ▼
                                          ┌───────────────────────────────┐
                                          │  PostgreSQL (single database)  │
                                          │  = system of record + Mock ERP │
                                          └───────────────────────────────┘
```

- **Frontend (React)** — what humans use: upload, dashboards, approvals, exceptions, admin.
- **API (FastAPI)** — the contract between UI and backend; handles auth and CRUD.
- **Redis** — a queue. Upload returns instantly; heavy processing happens in the background.
- **Celery Worker** — runs the 12-agent pipeline; calls GPT-4o for the AI steps.
- **PostgreSQL** — one database that is BOTH our records AND the "Mock ERP" (the stand-in for SAP/Oracle until we connect the real one).

---

## 4. How the ERP fits in (and how we'll swap in the real one)

Today the "ERP" is the set of master-data tables in PostgreSQL (vendors, purchase_orders, grns,
contracts, etc.). All validation and matching read from these tables — exactly as they would read
from SAP/Oracle.

We built a **pluggable ERP provider interface** (`app/services/erp/`):
- `MockERPProvider` — current; posts journal entries into the `erp_postings` table.
- `SAPProvider`, `OracleProvider` — stubs ready to implement.

**To go live with a real ERP, we only swap the provider — no pipeline changes.** Same for storage
(local disk today → Azure Blob later) and ingestion (portal upload today → email/Teams/ERP-pull later).
This is why the system is "integration-ready."

---

## 5. Agent-to-agent communication (the core innovation)

The pipeline is **12 independent agents**. They communicate by passing a single **workflow state**
object from one to the next — like an assembly line where each station adds to the same job ticket.

```
 UPLOAD
   │  state = { document_id, file_path, ... }
   ▼
 1. INTAKE ─────────► validates file, stores it, creates the document record
   │  state += { doc_type pending }
   ▼
 2. CLASSIFICATION ─► DIGITAL / SCANNED / HANDWRITTEN  (decides if OCR is needed)
   │  state += { doc_type, ocr_text? }
   ▼
 3. OCR ────────────► Tesseract (scanned) or GPT-4o Vision (handwritten); confidence score
   │  state += { ocr_text, ocr_confidence }
   ▼
 4. EXTRACTION ─────► GPT-4o pulls vendor, invoice#, amounts, line items, GST/PAN, PO/GRN refs
   │  state += { extracted_data }
   ▼
 5. UNIVERSAL VALIDATION ─► GST/PAN/duplicate/arithmetic/dates/bank (runs on EVERY doc)
   │  state += { validation results }
   ▼
 6. BUSINESS PROFILE ─► AI + rules decide: PO/Non-PO × Raw-material/Capex/Opex, or Lease/Reimbursement/Petty-cash
   │  state += { business_profile }
   ▼
 7. PROFILE VALIDATION ─► runs the rules specific to that profile (from the DB)
   │
   ├──(needs PO)──► 8. MATCHING ─► 3-way: PO ↔ GRN ↔ Invoice (qty, price, tax)
   │
   ▼
 9. EXCEPTION (only if something fails) ─► routes to a queue with an SLA
   ▼
 10. APPROVAL ─► DB-driven approval matrix by amount; multi-level, sequential
   ▼
 11. ERP POSTING ─► builds double-entry journal, posts to Mock ERP
   ▼
 12. PAYMENT ─► due date from terms, TDS, net payable → COMPLETED
```

Key points to stress:
- **Each agent has one job** (separation of concerns) — easy to test, replace, or upgrade.
- **Every agent writes an audit log** — who/what/when/why for every decision.
- **Every agent updates progress %** — the UI shows the live pipeline.
- **Hybrid AI + Rules** — AI predicts; rules validate/override. Nothing is a black box.

---

## 6. The database — one PostgreSQL database, ~30 tables

Grouped by purpose. (Show the key columns; full schema in `backend/app/models/models.py`.)

### A. ERP master data (the "Mock ERP" — source of truth for validation & matching)
| Table | Key columns | Why it exists |
|-------|-------------|---------------|
| `vendors` | vendor_code, name, **gstin, pan**, bank_*, payment_terms, **is_approved, po_required**, tds_* | Who we pay; drives vendor/GST/PAN validation |
| `vendor_contacts` | vendor_id, name, email, phone | Billing contacts |
| `purchase_orders` | **po_number**, vendor_id, status, total_amount, **invoiced_amount**, po_date | What was ordered (matching basis) |
| `po_line_items` | po_id, item_code, description, hsn_sac_code, quantity, **received_quantity, invoiced_quantity**, unit_price, uom, tax rates | Line-level PO detail + draw-down tracking |
| `grns` | grn_number, po_id, vendor_id, received_date, status | Goods Receipt Note — what was physically received |
| `grn_line_items` | grn_id, po_line_id, received_quantity, accepted_quantity | Line-level receipt |
| `contracts` / `lease_contracts` | contract_number, vendor_id, value/monthly_rent, dates, gst/tds | Service contracts / property leases |
| `assets` | asset_code, serial_number, category, purchase_value, depreciation | Fixed-asset register (CAPEX) |
| `employees` | employee_code, email, **monthly_reimbursement_limit, petty_cash_limit** | Reimbursement / petty-cash limits |
| `budgets` | cost_center_id, gl_code_id, total/committed/spent/available | Budget checks for non-PO spend |
| `cost_centers`, `gl_codes` | code, name, category | Accounting dimensions |

### B. Document processing
| Table | Key columns | Why |
|-------|-------------|-----|
| `documents` | **document_id**, original_filename, **status, doc_type, business_profile**, ai_profile_confidence, vendor_id, po_id, grn_id, invoice_number, invoice_date, total_amount, **extracted_data (JSON)**, ocr_text, ocr_confidence, original_path | The invoice + everything derived from it |
| `document_line_items` | document_id, description, quantity, unit_price, tax amounts, total | Extracted invoice lines |
| `workflow_states` | document_id, **current_stage, progress_percent, stage_history (JSON)**, error_message | Live pipeline status (drives the Processing tab) |

### C. Validation / matching / exceptions / approvals
| Table | Key columns | Why |
|-------|-------------|-----|
| `validation_profiles` | business_profile, name | One rule set per spend type |
| `validation_rules` | profile_id, rule_code, rule_type, severity, parameters (JSON) | The DB-driven rules (add without code) |
| `validation_results` | document_id, rule_code, **status (PASS/FAIL/WARNING)**, expected, actual, reason | Per-document outcomes |
| `matching_results` | document_id, po_id, grn_id, **match_status, overall_match_score**, variance_report (JSON), line_matches (JSON) | 3-way match result |
| `exceptions` | document_id, exception_type, **queue, severity, sla_deadline, status**, assigned_to, resolution_notes | Failures routed to teams |
| `approval_rules` | name, amount_min/max, **approval_matrix (JSON)** | The approval tiers |
| `approvals` | document_id, approval_level, approver_id, **status, action, comments, deadline** | Per-level approval steps |

### D. Output / audit
| Table | Key columns | Why |
|-------|-------------|-----|
| `erp_postings` | document_id, **journal_entries (JSON)**, erp_reference, posting_status, erp_system | The ledger posting (the "ERP" output) |
| `payment_schedules` | document_id, vendor_id, net_payable, tds_deduction, **due_date, status** | When/how much we pay |
| `audit_logs` | document_id, action, **agent, stage, before_state, after_state (JSON)**, timestamp | Immutable trail of every decision |
| `notifications` | user_id, type, title, body, is_read | User alerts |
| `users`, `configurations` | — | Auth + tunable settings (tolerances, SLAs) |

---

## 7. Where the mock/seed data lives — and why

- **Seed scripts** live in `seed/`.
  - `seed/data/*.json` — vendors, purchase_orders, grns as editable JSON fixtures.
  - `seed/load.py` — a generic loader that reads the JSON and inserts into PostgreSQL, resolving
    relationships by natural keys (vendor_code → vendor, po_number → PO).
  - `seed/seed_governance.py` — approver users + approval rules.
  - `seed/fix_login.py` — admin login.
- **Why JSON + loader (not hardcoded Python):** business users can edit master data without touching
  code; the same fixtures serve seeding, demos, and tests; adding a vendor/PO is a one-line JSON edit.
- **Where the data physically sits:** in the **PostgreSQL `ap_platform` database** (the tables above).
  The JSON files are just the *input*; the live data is in Postgres.


---

## 8. Where invoices are stored (raw, OCR, extracted, completed)

**Files on disk** under `backend/uploads/`:
```
backend/uploads/raw/{document_id}.pdf        ← the ORIGINAL uploaded invoice (immutable)
backend/uploads/ocr/{document_id}.txt        ← the OCR / source text
backend/uploads/extracted/{document_id}.json ← the extracted structured fields
backend/uploads/processed/                    ← preprocessed images (deskew/denoise)
```
**Structured data in PostgreSQL:**
- The `documents` row holds status, type, profile, amounts, and the full `extracted_data` JSON.
- Line items in `document_line_items`.
- A **completed** invoice is the same `documents` row with `status = 'COMPLETED'` — nothing moves;
  its journal posting is in `erp_postings`, its payment in `payment_schedules`.
- The original file is always retrievable via the "View Original Invoice" button (served from `raw/`).

**Talking point:** "We keep the original document forever (immutable evidence), the machine-readable
text, and the structured data — so we can always show exactly what we received and what we derived."

---

## 9. The frontend — every page, what each field means

The app is the **AP Operations Center** (left sidebar navigation). Auto-login opens it; the Admin
page is gated by admin/admin.

### Dashboard (`/`)
KPIs across the top, charts below:
- **Total Documents / Documents Today** — volume processed.
- **Pending Approvals** — invoices waiting on a human.
- **Open Exceptions** — invoices needing intervention.
- **Matching Rate %** — share of PO invoices that 3-way matched.
- **Total Invoice Value / Avg Processing Time** — financial + efficiency KPIs.
- **Processing Trend** (area chart) — last 7 days volume.
- **Documents by Status / Business Profile** (pie/bar) — mix of spend types.
- **Top Vendors by Amount** — spend concentration.
- **Exceptions by Queue** — where the bottlenecks are.

### Upload (`/upload`)
- **Drag-drop zone** — accepts PDF/JPG/PNG/TIFF/DOCX, up to 50MB.
- **Upload Queue** — each file shows name, size, and a live status: PROCESSING (spinner) → COMPLETED.
- **"View Live Progress"** — jumps to that document's pipeline view.
- Info panel explains the AI auto-processing (no manual type selection needed).

### Documents (`/documents`)
A data grid of all invoices with columns:
- **Document ID, File Name, Status** (color chip), **Business Profile** (PO/Non-PO type),
  **Vendor, Invoice #, Amount, AI Confidence, Invoice Date, Uploaded**.
- Filters by status & profile; auto-refreshes every 5s.
- **Actions:** View (opens detail), **Delete** (removes DB + file).

### Document Detail (`/documents/:id`) — the heart of the system
A header (Document ID, status chip, profile chip, **View Original Invoice** button) + a progress bar,
then tabs:
- **Overview** — summary banner (Doc Type, **PO/Non-PO**, Business Profile, OCR Confidence, Status),
  Document Information, Invoice Details (invoice #, date, vendor, GSTIN, PO#, GRN#, amounts), and the
  **AI Profile Decision** (what the AI concluded and *why*).
- **Extracted Data** — the full raw JSON of every field the AI pulled.
- **Validation** — every rule with **Result** (PASS/FAIL/WARNING), Expected, Actual, Reason, Agent.
- **3-Way Matching** — grouped table: **PURCHASE ORDER | GOODS RECEIPT | INVOICE** per line item,
  with Qty ✓ / Price ✓ / Status; plus PO balance draw-down for blanket POs. (Non-PO docs show a clear
  "Not Applicable" explanation.)
- **OCR / Source Text** — OCR method, confidence %, char count, and the raw extracted text (for audit).
- **Processing Pipeline** — live step-by-step (each agent, status, timestamps).
- **Audit Trail** — every action with agent, stage, and state changes.

### Approval Center (`/approvals`)
- **My Approvals** (assigned to me) and **All Approvals** tabs.
- Columns: Document, Level, Approver, Status, Deadline, Comments.
- **Approve / Reject** (with comments) and **Delegate**. Approving the last level triggers ERP posting.

### Exception Center (`/exceptions`)
- Grid of exceptions: Code, Title, Severity, Queue, Status, SLA Deadline (red if breached), Escalations.
- Filters by queue/status. Actions: **View document, ▶ Start (In Progress), ✓ Resolve** (with notes).

### Audit Trail (`/audit`)
- Search by document; immutable, exportable log of every agent decision and human action.

### Admin / ERP (`/admin`) — gated by admin/admin
- Tabs: **Vendors, Purchase Orders, Employees, Contracts, Lease Contracts, Assets, ERP Postings,
  Payment Schedules**.
- **Add Vendor / Add Purchase Order** forms write directly to the Mock ERP tables.
- **ERP Postings** tab shows completed journal entries (the ledger output); **Payment Schedules**
  shows due dates and net payable.

---

## 10. Live demo flow (5 minutes)

1. **Show the Mock ERP** — Admin → Vendors & Purchase Orders (e.g. PO `IO-56969-2-0-000037`).
2. **Upload** a real vendor invoice that references that PO.
3. **Watch the pipeline** — Document Detail → Processing Pipeline tab: INTAKE → CLASSIFICATION →
   EXTRACTION → VALIDATION → BUSINESS PROFILE → PROFILE VALIDATION → MATCHING → APPROVAL → ERP → PAYMENT.
4. **Show 3-Way Matching** — the PO↔GRN↔Invoice grouped table, all lines matched.
5. **Approve** it in the Approval Center → it posts to ERP and schedules payment.
6. **Show the Audit Trail** — every decision recorded.
7. **Upload a non-PO invoice** — show it correctly classified NON-PO and validated against vendor
   master/budget instead of matching.
8. **Upload a duplicate** — show it blocked with a duplicate-invoice exception.

---

## 11. Why this is enterprise-grade (closing)

- **Explainable AI** — every classification/validation shows its reasoning; nothing is a black box.
- **Hybrid AI + Rules** — AI for understanding, deterministic rules for control.
- **Full auditability** — immutable trail of every decision for compliance.
- **Integration-ready** — pluggable ERP/storage/ingestion; swap Mock ERP for SAP/Oracle with no
  pipeline changes.
- **Configurable** — validation rules, approval tiers, SLAs all DB-driven (no code deploys to change policy).
- **Risk controls** — 3-way matching, duplicate detection, over-billing guards, budget checks,
  multi-level approvals.