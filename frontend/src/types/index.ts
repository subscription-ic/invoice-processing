export interface User {
  id: string
  email: string
  name: string
  role: string
  department?: string
  employee_code?: string
  is_active: boolean
  created_at: string
}

export interface Vendor {
  id: string
  vendor_code: string
  name: string
  gstin?: string
  pan?: string
  city?: string
  state?: string
  payment_terms: string
  vendor_type: string
  is_approved: boolean
  is_msme: boolean
  tds_applicable: boolean
  tds_rate: number
  currency: string
  credit_limit: number
  created_at: string
  contacts?: VendorContact[]
}

export interface VendorContact {
  id: string
  name: string
  email?: string
  phone?: string
  designation?: string
  is_primary: boolean
  contact_type: string
}

export interface PurchaseOrder {
  id: string
  po_number: string
  vendor_id: string
  vendor_name?: string
  status: string
  total_amount: number
  invoiced_amount: number
  currency: string
  payment_terms: string
  po_date: string
  delivery_date?: string
  created_at: string
  line_items?: POLineItem[]
}

export interface POLineItem {
  id: string
  line_number: number
  item_code?: string
  description: string
  quantity: number
  received_quantity: number
  invoiced_quantity: number
  unit_price: number
  uom: string
  total_amount: number
  cgst_rate: number
  sgst_rate: number
  igst_rate: number
}

export interface GRN {
  id: string
  grn_number: string
  po_id: string
  po_number?: string
  vendor_id: string
  vendor_name?: string
  received_date: string
  status: string
  warehouse_location?: string
  created_at: string
  line_items?: GRNLineItem[]
}

export interface GRNLineItem {
  id: string
  po_line_id: string
  received_quantity: number
  accepted_quantity: number
  rejected_quantity: number
  rejection_reason?: string
  uom: string
}

export interface Document {
  id: string
  document_id: string
  original_filename: string
  file_extension: string
  file_size: number
  status: string
  doc_type?: string
  business_profile?: string
  ai_profile_confidence?: number
  ai_profile_reasoning?: string
  vendor_id?: string
  vendor_name?: string
  po_id?: string
  po_number?: string
  grn_id?: string
  grn_number?: string
  invoice_number?: string
  invoice_date?: string
  invoice_amount?: number
  tax_amount?: number
  total_amount?: number
  currency: string
  extracted_data?: Record<string, unknown>
  ocr_confidence?: number
  ocr_text?: string
  ingestion_source: string
  created_at: string
  updated_at?: string
  processing_started_at?: string
  processing_completed_at?: string
  line_items?: DocumentLineItem[]
}

export interface DocumentLineItem {
  id: string
  line_number: number
  description?: string
  quantity?: number
  unit_price?: number
  uom?: string
  cgst_rate: number
  sgst_rate: number
  igst_rate: number
  cgst_amount: number
  sgst_amount: number
  igst_amount: number
  total_amount?: number
  gl_code?: string
  cost_center?: string
}

export interface WorkflowState {
  id: string
  document_id: string
  current_stage: string
  current_agent?: string
  progress_percent: number
  error_message?: string
  stage_history: StageHistoryEntry[]
  retry_count: number
  started_at?: string
  completed_at?: string
  updated_at?: string
}

export interface StageHistoryEntry {
  stage: string
  agent: string
  started_at: string
  completed_at?: string
  status: string
  error?: string
  details?: Record<string, unknown>
}

export interface ValidationResult {
  id: string
  rule_code: string
  rule_name?: string
  status: 'PASS' | 'FAIL' | 'WARNING' | 'SKIPPED'
  expected_value?: string
  actual_value?: string
  reason?: string
  severity?: string
  agent?: string
  created_at: string
}

export interface MatchingResult {
  id: string
  match_status: string
  overall_match_score: number
  quantity_match?: boolean
  price_match?: boolean
  tax_match?: boolean
  total_match?: boolean
  vendor_match?: boolean
  variance_report?: Record<string, unknown>
  line_matches?: LineMatch[]
  tolerance_applied: boolean
  matching_notes?: string
}

export interface LineMatch {
  line_number: number
  status: string
  invoice: { qty: number; price: number }
  po: { qty: number; price: number } | null
  grn: { qty: number } | null
  qty_ok: boolean
  price_ok: boolean
}

export interface Exception {
  id: string
  document_id: string
  exception_code: string
  exception_type: string
  severity: string
  queue: string
  title: string
  description?: string
  agent_raised_by?: string
  assigned_to?: string
  assignee_name?: string
  status: string
  sla_hours: number
  sla_deadline?: string
  resolution_notes?: string
  resolved_at?: string
  escalation_count: number
  created_at: string
}

export interface Approval {
  id: string
  document_id: string
  approval_level: number
  approver_id: string
  approver_name?: string
  delegate_id?: string
  status: string
  action?: string
  comments?: string
  actioned_at?: string
  deadline?: string
  created_at: string
}

export interface AuditLog {
  id: string
  entity_type: string
  action: string
  agent?: string
  stage?: string
  before_state?: Record<string, unknown>
  after_state?: Record<string, unknown>
  metadata?: Record<string, unknown>
  timestamp: string
}

export interface DashboardStats {
  total_documents: number
  documents_today: number
  pending_approvals: number
  open_exceptions: number
  matching_rate: number
  avg_processing_time_minutes?: number
  total_invoice_amount: number
  documents_by_status: Record<string, number>
  documents_by_profile: Record<string, number>
  documents_by_source: Record<string, number>
  exception_by_queue: Record<string, number>
  top_vendors_by_amount: Array<{ vendor: string; amount: number }>
  processing_trend: Array<{ date: string; count: number }>
  approval_sla_stats: Record<string, unknown>
}

export interface Notification {
  id: string
  type: string
  title: string
  body?: string
  action_url?: string
  is_read: boolean
  created_at: string
}

export type DocumentStatus =
  | 'PENDING' | 'PROCESSING' | 'EXTRACTING' | 'VALIDATING'
  | 'MATCHING' | 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED'
  | 'POSTED' | 'HUMAN_REVIEW_REQUIRED' | 'EXCEPTION' | 'COMPLETED' | 'FAILED'

export type BusinessProfile =
  | 'PO_RAW_MATERIAL' | 'NON_PO_RAW_MATERIAL' | 'PO_CAPEX' | 'NON_PO_CAPEX'
  | 'PO_OPEX' | 'NON_PO_OPEX' | 'LEASE_RENT' | 'EMPLOYEE_REIMBURSEMENT' | 'PETTY_CASH'