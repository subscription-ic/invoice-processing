import React, { useCallback, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Box, Typography, Chip, CircularProgress, Divider, LinearProgress,
  Table, TableBody, TableCell, TableHead, TableRow, Paper, Button,
  IconButton, Tooltip, Badge, Avatar, Menu, MenuItem, TextField,
  InputAdornment, Select, FormControl, InputLabel, Alert, Snackbar,
  Dialog, DialogTitle, DialogContent, DialogActions, Skeleton,
} from '@mui/material'
// Import each icon from its own module path to avoid the broken barrel index
import CloudUpload     from '@mui/icons-material/CloudUpload'
import Search          from '@mui/icons-material/Search'
import Refresh         from '@mui/icons-material/Refresh'
import Close           from '@mui/icons-material/Close'
import CheckCircle     from '@mui/icons-material/CheckCircle'
import Warning         from '@mui/icons-material/Warning'
import ErrorIcon       from '@mui/icons-material/Error'
import HourglassEmpty  from '@mui/icons-material/HourglassEmpty'
import Notifications   from '@mui/icons-material/Notifications'
import Logout          from '@mui/icons-material/Logout'
import Receipt         from '@mui/icons-material/Receipt'
import ContentCopy     from '@mui/icons-material/ContentCopy'
import PriceChange     from '@mui/icons-material/PriceChange'
import FindInPage      from '@mui/icons-material/FindInPage'
import RuleFolder      from '@mui/icons-material/RuleFolder'
import ExpandMore      from '@mui/icons-material/ExpandMore'
import ExpandLess      from '@mui/icons-material/ExpandLess'
import TrendingUp      from '@mui/icons-material/TrendingUp'
import TrendingDown    from '@mui/icons-material/TrendingDown'
import FlatIcon        from '@mui/icons-material/Remove'
import Business        from '@mui/icons-material/Business'
import { dashboardApi, documentsApi, exceptionsApi } from '../api/client'
import { useAuthStore, useUIStore } from '../store'
import type { Document, Exception, ValidationResult, MatchingResult, DashboardStats } from '../types'

// ─── Colour tokens ───────────────────────────────────────────────────────────
const C = {
  navy:     '#0A1628',
  navyMid:  '#0F2040',
  navyCard: '#162035',
  blue:     '#3B7EF4',
  blueHov:  '#2C6DE0',
  green:    '#10B981',
  amber:    '#F59E0B',
  red:      '#EF4444',
  purple:   '#8B5CF6',
  text:     '#F1F5F9',
  textDim:  '#94A3B8',
  border:   'rgba(255,255,255,0.07)',
  surface:  '#F8FAFC',
  card:     '#FFFFFF',
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
const fmt = (n?: number, currency = 'INR') =>
  n == null ? '—' : new Intl.NumberFormat('en-IN', { style: 'currency', currency, maximumFractionDigits: 0 }).format(n)

const fmtDate = (s?: string) =>
  s ? new Date(s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'

const age = (s: string) => {
  const d = (Date.now() - new Date(s).getTime()) / 1000
  if (d < 60) return `${Math.floor(d)}s ago`
  if (d < 3600) return `${Math.floor(d / 60)}m ago`
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`
  return `${Math.floor(d / 86400)}d ago`
}

// ─── Status badge ─────────────────────────────────────────────────────────────
const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  PENDING:               { label: 'Pending',         color: C.textDim, bg: 'rgba(148,163,184,0.15)' },
  PROCESSING:            { label: 'Processing',      color: C.blue,    bg: 'rgba(59,126,244,0.12)'  },
  EXTRACTING:            { label: 'Extracting',      color: C.blue,    bg: 'rgba(59,126,244,0.12)'  },
  VALIDATING:            { label: 'Validating',      color: C.blue,    bg: 'rgba(59,126,244,0.12)'  },
  MATCHING:              { label: 'Matching',        color: C.blue,    bg: 'rgba(59,126,244,0.12)'  },
  PROFILED:              { label: 'Profiled',        color: C.blue,    bg: 'rgba(59,126,244,0.12)'  },
  PENDING_APPROVAL:      { label: 'Pending Approval',color: C.amber,   bg: 'rgba(245,158,11,0.12)'  },
  AWAITING_APPROVAL:     { label: 'Awaiting Approval',color:C.amber,   bg: 'rgba(245,158,11,0.12)'  },
  HUMAN_REVIEW_REQUIRED: { label: 'Human Review',   color: C.amber,   bg: 'rgba(245,158,11,0.12)'  },
  EXCEPTION:             { label: 'Exception',      color: C.red,     bg: 'rgba(239,68,68,0.12)'   },
  FAILED:                { label: 'Failed',          color: C.red,     bg: 'rgba(239,68,68,0.12)'   },
  REJECTED:              { label: 'Rejected',        color: C.red,     bg: 'rgba(239,68,68,0.12)'   },
  APPROVED:              { label: 'Approved',        color: C.green,   bg: 'rgba(16,185,129,0.12)'  },
  COMPLETED:             { label: 'Completed',       color: C.green,   bg: 'rgba(16,185,129,0.12)'  },
  POSTED:                { label: 'Posted',          color: C.green,   bg: 'rgba(16,185,129,0.12)'  },
  PAYMENT_SCHEDULED:     { label: 'Payment Scheduled',color:C.green,  bg: 'rgba(16,185,129,0.12)'  },
  UNDER_REVIEW:          { label: 'Under Review',   color: C.purple,  bg: 'rgba(139,92,246,0.12)'  },
  EXCEPTION_RESOLVED:    { label: 'Resolved',       color: C.green,   bg: 'rgba(16,185,129,0.12)'  },
}

function StatusBadge({ status }: { status: string }) {
  const m = STATUS_META[status] ?? { label: status, color: C.textDim, bg: 'rgba(148,163,184,0.15)' }
  return (
    <Box sx={{
      display: 'inline-flex', alignItems: 'center', gap: 0.5,
      px: 1.2, py: 0.3, borderRadius: '6px',
      bgcolor: m.bg, color: m.color,
      fontSize: 11, fontWeight: 700, letterSpacing: 0.3,
      whiteSpace: 'nowrap',
    }}>
      {m.label}
    </Box>
  )
}

// ─── Severity badge ───────────────────────────────────────────────────────────
const SEV_META: Record<string, { color: string; bg: string }> = {
  CRITICAL: { color: '#FF2D55', bg: 'rgba(255,45,85,0.12)'    },
  HIGH:     { color: C.red,    bg: 'rgba(239,68,68,0.12)'    },
  MEDIUM:   { color: C.amber,  bg: 'rgba(245,158,11,0.12)'   },
  LOW:      { color: C.green,  bg: 'rgba(16,185,129,0.12)'   },
}
function SeverityBadge({ sev }: { sev: string }) {
  const m = SEV_META[sev] ?? { color: C.textDim, bg: 'rgba(148,163,184,0.15)' }
  return (
    <Box sx={{
      display: 'inline-flex', px: 1, py: 0.25, borderRadius: '5px',
      bgcolor: m.bg, color: m.color, fontSize: 10, fontWeight: 800, letterSpacing: 0.5,
    }}>
      {sev}
    </Box>
  )
}

// ─── KPI card ─────────────────────────────────────────────────────────────────
function KpiCard({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color: string }) {
  return (
    <Box sx={{
      flex: '1 1 160px', minWidth: 140,
      bgcolor: C.navyCard, border: `1px solid ${C.border}`,
      borderRadius: '12px', px: 2.5, py: 2,
      borderLeft: `3px solid ${color}`,
    }}>
      <Typography sx={{ fontSize: 11, color: C.textDim, fontWeight: 600, letterSpacing: 0.8, textTransform: 'uppercase', mb: 0.5 }}>
        {label}
      </Typography>
      <Typography sx={{ fontSize: 26, fontWeight: 800, color: C.text, lineHeight: 1.1 }}>
        {value}
      </Typography>
      {sub && <Typography sx={{ fontSize: 11, color: C.textDim, mt: 0.5 }}>{sub}</Typography>}
    </Box>
  )
}

// ─── Upload zone ──────────────────────────────────────────────────────────────
function UploadZone({ onUploaded }: { onUploaded: (doc: { document_id: string }) => void }) {
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState<string | null>(null)
  const ref = useRef<HTMLInputElement>(null)

  const doUpload = useCallback(async (file: File) => {
    if (!file) return
    setUploading(true)
    setProgress(`Uploading ${file.name}…`)
    try {
      const form = new FormData()
      form.append('file', file)
      const { data } = await documentsApi.upload(file)
      setProgress(`Processing started — ${data.document_id}`)
      onUploaded(data)
      setTimeout(() => { setProgress(null); setUploading(false) }, 2500)
    } catch {
      setProgress('Upload failed — check file type/size')
      setTimeout(() => { setProgress(null); setUploading(false) }, 3000)
    }
  }, [onUploaded])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) doUpload(file)
  }, [doUpload])

  return (
    <Box
      onClick={() => !uploading && ref.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      sx={{
        border: `2px dashed ${dragging ? C.blue : 'rgba(59,126,244,0.3)'}`,
        borderRadius: '12px',
        bgcolor: dragging ? 'rgba(59,126,244,0.06)' : 'rgba(59,126,244,0.02)',
        p: 3, textAlign: 'center', cursor: uploading ? 'default' : 'pointer',
        transition: 'all 0.2s',
        '&:hover': { borderColor: C.blue, bgcolor: 'rgba(59,126,244,0.05)' },
      }}
    >
      <input ref={ref} type="file" hidden accept=".pdf,.jpg,.jpeg,.png,.tiff,.docx"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) doUpload(f); e.target.value = '' }} />
      {uploading ? (
        <>
          <CircularProgress size={28} sx={{ color: C.blue, mb: 1 }} />
          <Typography sx={{ fontSize: 13, color: C.blue, fontWeight: 600 }}>{progress}</Typography>
        </>
      ) : (
        <>
          <CloudUpload sx={{ fontSize: 32, color: C.blue, opacity: 0.7, mb: 0.5 }} />
          <Typography sx={{ fontSize: 13, fontWeight: 700, color: C.text }}>Drop invoice here</Typography>
          <Typography sx={{ fontSize: 11, color: C.textDim, mt: 0.3 }}>PDF · JPG · PNG · TIFF · DOCX · max 50 MB</Typography>
        </>
      )}
    </Box>
  )
}

// ─── Pipeline progress bar ────────────────────────────────────────────────────
const STAGES = ['INTAKE','CLASSIFICATION','OCR','EXTRACTION','VALIDATION','PROFILING','MATCHING','EXCEPTION','APPROVAL','ERP_POSTING','PAYMENT','COMPLETED']

function PipelineBar({ progress, currentStage, error }: { progress: number; currentStage: string; error?: string }) {
  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
        <Typography sx={{ fontSize: 11, color: C.textDim }}>{currentStage.replace(/_/g, ' ')}</Typography>
        <Typography sx={{ fontSize: 11, color: error ? C.red : C.blue, fontWeight: 700 }}>{error ? 'ERROR' : `${progress}%`}</Typography>
      </Box>
      <LinearProgress
        variant="determinate" value={error ? 100 : progress}
        sx={{
          height: 5, borderRadius: 3,
          bgcolor: 'rgba(255,255,255,0.08)',
          '& .MuiLinearProgress-bar': { bgcolor: error ? C.red : progress === 100 ? C.green : C.blue, borderRadius: 3 },
        }}
      />
    </Box>
  )
}

// ─── Exception AI summary ─────────────────────────────────────────────────────
function ExceptionDetail({
  exc, doc, matching, validation,
}: {
  exc: Exception
  doc?: Document
  matching?: MatchingResult
  validation?: ValidationResult[]
}) {
  const [resolving, setResolving] = useState(false)
  const [notes, setNotes] = useState('')
  const [showResolve, setShowResolve] = useState(false)
  const qc = useQueryClient()

  const resolveMut = useMutation({
    mutationFn: () => exceptionsApi.resolve(exc.id, { resolution_notes: notes, status: 'RESOLVED' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['exceptions'] })
      qc.invalidateQueries({ queryKey: ['documents'] })
      setShowResolve(false)
    },
  })

  const code = exc.exception_code ?? exc.exception_type ?? ''
  const isDuplicate = code.includes('DUPLICATE')
  const isPriceMismatch = code.includes('PRICE') || code.includes('MISMATCH') || code.includes('MATCHING')
  const isPONotFound = code.includes('PO_NOT_FOUND') || code.includes('NO_PO')
  const isValidation = code.includes('VALIDATION') || code.includes('GSTIN') || code.includes('TAX')
  const isVendor = code.includes('VENDOR')

  // failed rules
  const failedRules = (validation ?? []).filter(v => v.status === 'FAIL' || v.status === 'WARNING')
  const passedRules = (validation ?? []).filter(v => v.status === 'PASS')

  // variance report from matching
  const vr = matching?.variance_report as Record<string, unknown> | undefined
  const lineMatches = matching?.line_matches ?? []

  const slaBreached = exc.sla_deadline && new Date(exc.sla_deadline) < new Date()

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, mb: 2 }}>
        <Box sx={{
          width: 40, height: 40, borderRadius: '10px', flexShrink: 0,
          bgcolor: SEV_META[exc.severity]?.bg ?? 'rgba(239,68,68,0.12)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <Warning sx={{ color: SEV_META[exc.severity]?.color ?? C.red, fontSize: 22 }} />
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 0.5 }}>
            <SeverityBadge sev={exc.severity} />
            <StatusBadge status={exc.status} />
            {slaBreached && (
              <Box sx={{ px: 1, py: 0.2, borderRadius: '5px', bgcolor: 'rgba(255,45,85,0.12)', color: '#FF2D55', fontSize: 10, fontWeight: 800 }}>
                SLA BREACHED
              </Box>
            )}
          </Box>
          <Typography sx={{ fontSize: 14, fontWeight: 700, color: '#0F172A', lineHeight: 1.3 }}>
            {exc.title}
          </Typography>
          <Typography sx={{ fontSize: 11, color: '#64748B', mt: 0.3 }}>
            Queue: <strong>{exc.queue}</strong> · Raised by {exc.agent_raised_by?.replace(/_/g,' ') ?? 'System'} · {age(exc.created_at)}
          </Typography>
        </Box>
      </Box>

      {/* AI Description */}
      {exc.description && (
        <Box sx={{ bgcolor: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: '10px', p: 2, mb: 2 }}>
          <Typography sx={{ fontSize: 11, color: '#64748B', fontWeight: 700, letterSpacing: 0.6, mb: 0.5 }}>
            AI ANALYSIS
          </Typography>
          <Typography sx={{ fontSize: 13, color: '#1E293B', lineHeight: 1.6 }}>
            {exc.description}
          </Typography>
        </Box>
      )}

      {/* ── DUPLICATE INVOICE ── */}
      {isDuplicate && doc && (
        <Box sx={{ mb: 2 }}>
          <SectionLabel icon={<ContentCopy sx={{ fontSize: 13 }} />} label="DUPLICATE DETECTION" />
          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1.5, mt: 1 }}>
            <CompareCard title="THIS INVOICE" highlight color={C.red}>
              <CompareRow label="Document" value={doc.document_id} />
              <CompareRow label="Invoice #" value={doc.invoice_number} />
              <CompareRow label="Vendor" value={doc.vendor_name} />
              <CompareRow label="Amount" value={fmt(doc.total_amount)} />
              <CompareRow label="Date" value={fmtDate(doc.invoice_date)} />
            </CompareCard>
            <CompareCard title="ORIGINAL (MATCH)" color={C.green}>
              {/* The matching agent stores duplicate info in description / metadata */}
              <Typography sx={{ fontSize: 12, color: '#64748B', mt: 1, fontStyle: 'italic' }}>
                Matched record identified by AI. Refer to exception description for original document reference.
              </Typography>
            </CompareCard>
          </Box>
          <InfoRow label="Matched Fields" value="Invoice Number · Vendor · Amount · Date" />
        </Box>
      )}

      {/* ── PRICE / MATCHING MISMATCH ── */}
      {isPriceMismatch && lineMatches.length > 0 && (
        <Box sx={{ mb: 2 }}>
          <SectionLabel icon={<PriceChange sx={{ fontSize: 13 }} />} label="PRICE COMPARISON" />
          <Box sx={{ overflowX: 'auto', mt: 1 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: '#F1F5F9' }}>
                  {['Line', 'PO Qty', 'Inv Qty', 'PO Price', 'Inv Price', 'Variance', 'Status'].map(h => (
                    <th key={h} style={{ padding: '6px 10px', textAlign: 'left', color: '#64748B', fontWeight: 700, fontSize: 10, letterSpacing: 0.5 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {lineMatches.map((lm, i) => {
                  const poPrice  = (lm.po as {qty:number;price:number} | null)?.price ?? 0
                  const invPrice = (lm.invoice as {qty:number;price:number})?.price ?? 0
                  const poQty    = (lm.po as {qty:number;price:number} | null)?.qty ?? 0
                  const invQty   = (lm.invoice as {qty:number;price:number})?.qty ?? 0
                  const varAmt   = invPrice - poPrice
                  const varPct   = poPrice ? ((varAmt / poPrice) * 100) : 0
                  const mismatch = !lm.price_ok
                  return (
                    <tr key={i} style={{ borderBottom: '1px solid #F1F5F9', background: mismatch ? 'rgba(239,68,68,0.04)' : 'white' }}>
                      <td style={{ padding: '7px 10px', fontWeight: 600 }}>#{lm.line_number}</td>
                      <td style={{ padding: '7px 10px' }}>{poQty}</td>
                      <td style={{ padding: '7px 10px', color: lm.qty_ok ? '#1E293B' : C.red, fontWeight: lm.qty_ok ? 400 : 700 }}>{invQty}</td>
                      <td style={{ padding: '7px 10px' }}>{fmt(poPrice)}</td>
                      <td style={{ padding: '7px 10px', color: mismatch ? C.red : '#1E293B', fontWeight: mismatch ? 700 : 400 }}>{fmt(invPrice)}</td>
                      <td style={{ padding: '7px 10px' }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                          {varAmt > 0 ? <TrendingUp sx={{ fontSize: 13, color: C.red }} /> : varAmt < 0 ? <TrendingDown sx={{ fontSize: 13, color: C.green }} /> : <FlatIcon sx={{ fontSize: 13, color: C.textDim }} />}
                          <span style={{ color: mismatch ? C.red : '#64748B', fontWeight: mismatch ? 700 : 400 }}>
                            {varAmt >= 0 ? '+' : ''}{fmt(varAmt)} ({varPct >= 0 ? '+' : ''}{varPct.toFixed(1)}%)
                          </span>
                        </Box>
                      </td>
                      <td style={{ padding: '7px 10px' }}>
                        <Box sx={{
                          display: 'inline-flex', px: 0.8, py: 0.2, borderRadius: '4px', fontSize: 10, fontWeight: 800,
                          color: lm.price_ok ? C.green : C.red,
                          bgcolor: lm.price_ok ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
                        }}>
                          {lm.status}
                        </Box>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </Box>

          {vr && (
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1, mt: 1.5 }}>
              <StatMini label="Invoice Total" value={fmt(vr.invoice_total as number)} />
              <StatMini label="PO Total"      value={fmt(vr.po_total as number)} />
              <StatMini
                label="Variance"
                value={`${fmt(vr.total_variance as number)} (${(vr.total_variance_pct as number ?? 0).toFixed(1)}%)`}
                alert={Math.abs(vr.total_variance_pct as number ?? 0) > 2}
              />
            </Box>
          )}
        </Box>
      )}

      {/* ── PO NOT FOUND ── */}
      {isPONotFound && (
        <Box sx={{ mb: 2 }}>
          <SectionLabel icon={<FindInPage sx={{ fontSize: 13 }} />} label="PURCHASE ORDER LOOKUP" />
          <Box sx={{ bgcolor: 'rgba(239,68,68,0.05)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: '10px', p: 2, mt: 1 }}>
            <Typography sx={{ fontSize: 12, color: '#1E293B', lineHeight: 1.6 }}>
              No matching Purchase Order was found for this invoice.
            </Typography>
            <Box sx={{ mt: 1.5, display: 'flex', gap: 2, flexWrap: 'wrap' }}>
              <InfoRow label="Vendor on Invoice" value={doc?.vendor_name ?? '—'} />
              <InfoRow label="PO Ref on Invoice" value={doc?.po_number ?? 'Not mentioned'} />
            </Box>
          </Box>
        </Box>
      )}

      {/* ── VENDOR ISSUE ── */}
      {isVendor && (
        <Box sx={{ mb: 2 }}>
          <SectionLabel icon={<Business sx={{ fontSize: 13 }} />} label="VENDOR VERIFICATION" />
          <Box sx={{ bgcolor: 'rgba(245,158,11,0.05)', border: '1px solid rgba(245,158,11,0.2)', borderRadius: '10px', p: 2, mt: 1 }}>
            <InfoRow label="Vendor Name" value={doc?.vendor_name ?? '—'} />
            <InfoRow label="GSTIN on Invoice" value={(doc?.extracted_data as Record<string, unknown>)?.vendor_gstin as string ?? '—'} />
          </Box>
        </Box>
      )}

      {/* ── FAILED VALIDATION RULES ── */}
      {failedRules.length > 0 && (
        <Box sx={{ mb: 2 }}>
          <SectionLabel icon={<RuleFolder sx={{ fontSize: 13 }} />} label={`FAILED RULES (${failedRules.length})`} />
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mt: 1 }}>
            {failedRules.map((r) => (
              <Box key={r.id} sx={{
                bgcolor: r.status === 'FAIL' ? 'rgba(239,68,68,0.04)' : 'rgba(245,158,11,0.04)',
                border: `1px solid ${r.status === 'FAIL' ? 'rgba(239,68,68,0.2)' : 'rgba(245,158,11,0.2)'}`,
                borderRadius: '9px', p: 1.5,
              }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Box sx={{
                    fontSize: 9, fontWeight: 800, px: 0.8, py: 0.15, borderRadius: '4px',
                    color: r.status === 'FAIL' ? C.red : C.amber,
                    bgcolor: r.status === 'FAIL' ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.12)',
                  }}>{r.status}</Box>
                  <Typography sx={{ fontSize: 12, fontWeight: 700, color: '#0F172A' }}>
                    {r.rule_name ?? r.rule_code}
                  </Typography>
                </Box>
                {r.reason && <Typography sx={{ fontSize: 12, color: '#475569', lineHeight: 1.5 }}>{r.reason}</Typography>}
                {(r.expected_value || r.actual_value) && (
                  <Box sx={{ display: 'flex', gap: 2, mt: 0.8, flexWrap: 'wrap' }}>
                    {r.expected_value && <InfoRow label="Expected" value={r.expected_value} />}
                    {r.actual_value  && <InfoRow label="Actual"   value={r.actual_value} alert />}
                  </Box>
                )}
              </Box>
            ))}
          </Box>
        </Box>
      )}

      {/* ── PASSED RULES (collapsed) ── */}
      {passedRules.length > 0 && (
        <PassedRules rules={passedRules} />
      )}

      {/* ── RESOLVE ── */}
      {exc.status !== 'RESOLVED' && exc.status !== 'CLOSED' && (
        <Box sx={{ mt: 2, pt: 2, borderTop: '1px solid #F1F5F9' }}>
          <Button
            variant="contained"
            size="small"
            onClick={() => setShowResolve(true)}
            sx={{ bgcolor: C.green, '&:hover': { bgcolor: '#0DA271' }, textTransform: 'none', fontWeight: 700 }}
          >
            Mark as Resolved
          </Button>
        </Box>
      )}

      {/* Resolve dialog */}
      <Dialog open={showResolve} onClose={() => setShowResolve(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 700, fontSize: 16 }}>Resolve Exception</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth multiline rows={3}
            label="Resolution Notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowResolve(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => resolveMut.mutate()}
            disabled={resolveMut.isPending || !notes.trim()}
            sx={{ bgcolor: C.green, '&:hover': { bgcolor: '#0DA271' } }}
          >
            {resolveMut.isPending ? 'Saving…' : 'Confirm Resolve'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

// ─── Small helpers for ExceptionDetail ───────────────────────────────────────
function SectionLabel({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.8 }}>
      <Box sx={{ color: '#64748B' }}>{icon}</Box>
      <Typography sx={{ fontSize: 10, fontWeight: 800, color: '#64748B', letterSpacing: 0.8 }}>{label}</Typography>
    </Box>
  )
}

function InfoRow({ label, value, alert: isAlert }: { label: string; value?: string; alert?: boolean }) {
  return (
    <Box>
      <Typography sx={{ fontSize: 10, color: '#94A3B8', fontWeight: 600 }}>{label}</Typography>
      <Typography sx={{ fontSize: 12, fontWeight: 700, color: isAlert ? C.red : '#1E293B' }}>{value ?? '—'}</Typography>
    </Box>
  )
}

function StatMini({ label, value, alert }: { label: string; value: string; alert?: boolean }) {
  return (
    <Box sx={{ bgcolor: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: '8px', p: 1.5 }}>
      <Typography sx={{ fontSize: 10, color: '#64748B', fontWeight: 600 }}>{label}</Typography>
      <Typography sx={{ fontSize: 13, fontWeight: 700, color: alert ? C.red : '#0F172A', mt: 0.3 }}>{value}</Typography>
    </Box>
  )
}

function CompareCard({ title, children, highlight, color }: { title: string; children: React.ReactNode; highlight?: boolean; color: string }) {
  return (
    <Box sx={{
      border: `1.5px solid ${highlight ? color : '#E2E8F0'}`,
      borderRadius: '10px', p: 1.5,
      bgcolor: highlight ? `${color}08` : 'white',
    }}>
      <Typography sx={{ fontSize: 9, fontWeight: 800, color, letterSpacing: 0.8, mb: 1 }}>{title}</Typography>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.8 }}>
        {children}
      </Box>
    </Box>
  )
}

function CompareRow({ label, value }: { label: string; value?: string }) {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1 }}>
      <Typography sx={{ fontSize: 11, color: '#94A3B8' }}>{label}</Typography>
      <Typography sx={{ fontSize: 11, fontWeight: 600, color: '#1E293B', textAlign: 'right' }}>{value ?? '—'}</Typography>
    </Box>
  )
}

function PassedRules({ rules }: { rules: ValidationResult[] }) {
  const [open, setOpen] = useState(false)
  return (
    <Box sx={{ mb: 1.5 }}>
      <Box
        onClick={() => setOpen(o => !o)}
        sx={{ display: 'flex', alignItems: 'center', gap: 0.8, cursor: 'pointer', mb: open ? 1 : 0 }}
      >
        <CheckCircle sx={{ fontSize: 13, color: C.green }} />
        <Typography sx={{ fontSize: 10, fontWeight: 700, color: '#64748B', letterSpacing: 0.6 }}>
          {rules.length} RULES PASSED
        </Typography>
        {open ? <ExpandLess sx={{ fontSize: 14, color: '#94A3B8' }} /> : <ExpandMore sx={{ fontSize: 14, color: '#94A3B8' }} />}
      </Box>
      {open && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          {rules.map(r => (
            <Box key={r.id} sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, py: 0.8, bgcolor: 'rgba(16,185,129,0.04)', borderRadius: '7px' }}>
              <CheckCircle sx={{ fontSize: 12, color: C.green }} />
              <Typography sx={{ fontSize: 12, color: '#475569' }}>{r.rule_name ?? r.rule_code}</Typography>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  )
}

// ─── Document detail panel ────────────────────────────────────────────────────
function DocPanel({ docId, onClose }: { docId: string; onClose: () => void }) {
  const [tab, setTab] = useState<'overview' | 'exception' | 'matching' | 'validation'>('overview')

  const { data: doc, isLoading: loadDoc } = useQuery({
    queryKey: ['doc', docId],
    queryFn: async () => { const { data } = await documentsApi.get(docId); return data as Document },
  })
  const { data: workflow, isLoading: loadWf } = useQuery({
    queryKey: ['workflow', docId],
    queryFn: async () => { const { data } = await documentsApi.getWorkflow(docId); return data },
  })
  const { data: exceptions } = useQuery({
    queryKey: ['doc-exceptions', docId],
    queryFn: async () => { const { data } = await exceptionsApi.list({ document_id: docId }); return data as Exception[] },
    enabled: !!doc,
  })
  const { data: matching } = useQuery({
    queryKey: ['matching', docId],
    queryFn: async () => { const { data } = await documentsApi.getMatching(docId); return data as MatchingResult },
    enabled: !!doc,
  })
  const { data: validation } = useQuery({
    queryKey: ['validation', docId],
    queryFn: async () => { const { data } = await documentsApi.getValidation(docId); return data as ValidationResult[] },
    enabled: !!doc,
  })

  const hasException = (doc?.status === 'EXCEPTION' || doc?.status === 'HUMAN_REVIEW_REQUIRED') && (exceptions?.length ?? 0) > 0
  const activeExc = exceptions?.[0]

  // Auto-switch to exception tab
  React.useEffect(() => {
    if (hasException) setTab('exception')
  }, [hasException])

  const TABS = [
    { key: 'overview',   label: 'Overview' },
    { key: 'exception',  label: 'Exception', show: hasException },
    { key: 'matching',   label: 'Matching',  show: !!matching   },
    { key: 'validation', label: 'Validation' },
  ].filter(t => t.show !== false)

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: 'white' }}>
      {/* Panel header */}
      <Box sx={{ px: 2.5, pt: 2.5, pb: 0, borderBottom: '1px solid #F1F5F9' }}>
        <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', mb: 1.5 }}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            {loadDoc ? <Skeleton width={180} height={20} /> : (
              <>
                <Typography sx={{ fontSize: 13, fontWeight: 800, color: '#0F172A', mb: 0.3, fontFamily: 'monospace' }}>
                  {doc?.document_id}
                </Typography>
                <Typography sx={{ fontSize: 12, color: '#64748B' }} noWrap>
                  {doc?.original_filename}
                </Typography>
              </>
            )}
          </Box>
          <IconButton size="small" onClick={onClose} sx={{ ml: 1 }}>
            <Close sx={{ fontSize: 18 }} />
          </IconButton>
        </Box>

        {/* Status + amount row */}
        {doc && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1.5 }}>
            <StatusBadge status={doc.status} />
            {doc.total_amount != null && (
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: '#0F172A' }}>{fmt(doc.total_amount)}</Typography>
            )}
            {doc.vendor_name && (
              <Typography sx={{ fontSize: 12, color: '#64748B' }}>· {doc.vendor_name}</Typography>
            )}
          </Box>
        )}

        {/* Pipeline bar */}
        {workflow && (
          <Box sx={{ mb: 1.5 }}>
            <PipelineBar
              progress={workflow.progress_percent ?? 0}
              currentStage={workflow.current_stage ?? ''}
              error={workflow.error_message}
            />
          </Box>
        )}

        {/* Tabs */}
        <Box sx={{ display: 'flex', gap: 0, mt: 0.5 }}>
          {TABS.map(t => (
            <Box
              key={t.key}
              onClick={() => setTab(t.key as typeof tab)}
              sx={{
                px: 2, py: 1, fontSize: 12, fontWeight: 600, cursor: 'pointer',
                color: tab === t.key ? C.blue : '#64748B',
                borderBottom: tab === t.key ? `2px solid ${C.blue}` : '2px solid transparent',
                transition: 'all 0.15s',
                '&:hover': { color: C.blue },
              }}
            >
              {t.label}
              {t.key === 'exception' && (
                <Box component="span" sx={{ ml: 0.5, px: 0.6, py: 0.1, borderRadius: '4px', bgcolor: C.red, color: 'white', fontSize: 9, fontWeight: 800 }}>
                  {exceptions?.length}
                </Box>
              )}
            </Box>
          ))}
        </Box>
      </Box>

      {/* Panel body */}
      <Box sx={{ flex: 1, overflowY: 'auto', p: 2.5 }}>
        {loadDoc || loadWf ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            {[1,2,3,4].map(i => <Skeleton key={i} height={40} sx={{ borderRadius: 1 }} />)}
          </Box>
        ) : (
          <>
            {tab === 'overview' && doc && (
              <OverviewTab doc={doc} workflow={workflow} />
            )}
            {tab === 'exception' && activeExc && doc && (
              <ExceptionDetail
                exc={activeExc}
                doc={doc}
                matching={matching}
                validation={validation}
              />
            )}
            {tab === 'matching' && matching && (
              <MatchingTab matching={matching} />
            )}
            {tab === 'validation' && (
              <ValidationTab rules={validation ?? []} />
            )}
          </>
        )}
      </Box>
    </Box>
  )
}

// ─── Overview tab ─────────────────────────────────────────────────────────────
function OverviewTab({ doc, workflow }: { doc: Document; workflow?: { stage_history: {stage:string;status:string;completed_at?:string}[] } }) {
  const fields = [
    { label: 'Invoice Number',  value: doc.invoice_number  },
    { label: 'Invoice Date',    value: fmtDate(doc.invoice_date) },
    { label: 'Vendor',          value: doc.vendor_name     },
    { label: 'PO Number',       value: doc.po_number ?? '—' },
    { label: 'GRN Number',      value: doc.grn_number ?? '—' },
    { label: 'Invoice Amount',  value: fmt(doc.invoice_amount) },
    { label: 'Tax Amount',      value: fmt(doc.tax_amount)  },
    { label: 'Total Amount',    value: fmt(doc.total_amount), bold: true },
    { label: 'Business Profile',value: doc.business_profile?.replace(/_/g,' ') },
    { label: 'AI Confidence',   value: doc.ai_profile_confidence != null ? `${(doc.ai_profile_confidence * 100).toFixed(0)}%` : '—' },
    { label: 'Document Type',   value: doc.doc_type  },
    { label: 'OCR Confidence',  value: doc.ocr_confidence != null ? `${(doc.ocr_confidence * 100).toFixed(0)}%` : '—' },
    { label: 'Source',          value: doc.ingestion_source },
    { label: 'Uploaded',        value: fmtDate(doc.created_at) },
  ]

  return (
    <Box>
      {doc.ai_profile_reasoning && (
        <Box sx={{ bgcolor: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: '10px', p: 2, mb: 2.5 }}>
          <Typography sx={{ fontSize: 10, fontWeight: 800, color: '#64748B', letterSpacing: 0.6, mb: 0.5 }}>AI REASONING</Typography>
          <Typography sx={{ fontSize: 12, color: '#1E293B', lineHeight: 1.6 }}>{doc.ai_profile_reasoning}</Typography>
        </Box>
      )}
      <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
        {fields.map(f => (
          <Box key={f.label} sx={{ py: 1.2, px: 0.5, borderBottom: '1px solid #F8FAFC' }}>
            <Typography sx={{ fontSize: 10, color: '#94A3B8', fontWeight: 600, mb: 0.2 }}>{f.label}</Typography>
            <Typography sx={{ fontSize: 12, fontWeight: f.bold ? 700 : 500, color: '#1E293B' }}>{f.value ?? '—'}</Typography>
          </Box>
        ))}
      </Box>
      {doc.line_items && doc.line_items.length > 0 && (
        <Box sx={{ mt: 2 }}>
          <Typography sx={{ fontSize: 10, fontWeight: 800, color: '#64748B', letterSpacing: 0.6, mb: 1 }}>LINE ITEMS</Typography>
          <Box sx={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: '#F8FAFC' }}>
                  {['#', 'Description', 'Qty', 'Unit Price', 'Total'].map(h => (
                    <th key={h} style={{ padding: '6px 8px', textAlign: 'left', color: '#64748B', fontWeight: 700, fontSize: 10 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {doc.line_items.map(li => (
                  <tr key={li.id} style={{ borderBottom: '1px solid #F8FAFC' }}>
                    <td style={{ padding: '6px 8px', color: '#94A3B8' }}>{li.line_number}</td>
                    <td style={{ padding: '6px 8px' }}>{li.description ?? '—'}</td>
                    <td style={{ padding: '6px 8px' }}>{li.quantity ?? '—'}</td>
                    <td style={{ padding: '6px 8px' }}>{fmt(li.unit_price)}</td>
                    <td style={{ padding: '6px 8px', fontWeight: 600 }}>{fmt(li.total_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Box>
        </Box>
      )}
    </Box>
  )
}

// ─── Matching tab ─────────────────────────────────────────────────────────────
function MatchingTab({ matching }: { matching: MatchingResult }) {
  const vr = matching.variance_report as Record<string, unknown> | undefined
  const score = Math.round((matching.overall_match_score ?? 0) * 100)
  const checks = [
    { label: 'Vendor Match',   ok: matching.vendor_match   },
    { label: 'Price Match',    ok: matching.price_match    },
    { label: 'Quantity Match', ok: matching.quantity_match },
    { label: 'Tax Match',      ok: matching.tax_match      },
    { label: 'Total Match',    ok: matching.total_match    },
  ]
  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
        <Box sx={{ position: 'relative', display: 'inline-flex' }}>
          <CircularProgress
            variant="determinate" value={score}
            size={72} thickness={5}
            sx={{ color: score >= 90 ? C.green : score >= 70 ? C.amber : C.red }}
          />
          <Box sx={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Typography sx={{ fontSize: 16, fontWeight: 800, color: '#0F172A' }}>{score}%</Typography>
          </Box>
        </Box>
        <Box>
          <Typography sx={{ fontSize: 14, fontWeight: 700, color: '#0F172A' }}>Match Score</Typography>
          <StatusBadge status={matching.match_status} />
          {matching.tolerance_applied && (
            <Typography sx={{ fontSize: 11, color: C.amber, mt: 0.5 }}>Tolerance applied</Typography>
          )}
        </Box>
      </Box>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.8, mb: 2 }}>
        {checks.map(c => (
          <Box key={c.label} sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', px: 1.5, py: 1, borderRadius: '8px', bgcolor: '#F8FAFC' }}>
            <Typography sx={{ fontSize: 12, color: '#475569' }}>{c.label}</Typography>
            {c.ok == null ? <Box sx={{ fontSize: 10, color: '#94A3B8' }}>N/A</Box> : c.ok
              ? <CheckCircle sx={{ fontSize: 16, color: C.green }} />
              : <ErrorIcon sx={{ fontSize: 16, color: C.red }} />
            }
          </Box>
        ))}
      </Box>
      {vr && (
        <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 1 }}>
          <StatMini label="Invoice Total" value={fmt(vr.invoice_total as number)} />
          <StatMini label="PO Total"      value={fmt(vr.po_total as number)} />
          <StatMini label="Variance"      value={fmt(vr.total_variance as number)} alert={Math.abs(vr.total_variance_pct as number ?? 0) > 2} />
          <StatMini label="Variance %"    value={`${(vr.total_variance_pct as number ?? 0).toFixed(2)}%`} alert={Math.abs(vr.total_variance_pct as number ?? 0) > 2} />
        </Box>
      )}
      {matching.matching_notes && (
        <Box sx={{ mt: 2, p: 1.5, bgcolor: '#F8FAFC', borderRadius: '8px', border: '1px solid #E2E8F0' }}>
          <Typography sx={{ fontSize: 12, color: '#475569', lineHeight: 1.6 }}>{matching.matching_notes}</Typography>
        </Box>
      )}
    </Box>
  )
}

// ─── Validation tab ───────────────────────────────────────────────────────────
function ValidationTab({ rules }: { rules: ValidationResult[] }) {
  if (rules.length === 0) return <Typography sx={{ fontSize: 13, color: '#94A3B8', textAlign: 'center', py: 4 }}>No validation results yet.</Typography>
  const counts = { PASS: 0, FAIL: 0, WARNING: 0, SKIPPED: 0 }
  rules.forEach(r => { counts[r.status] = (counts[r.status] ?? 0) + 1 })
  return (
    <Box>
      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
        {Object.entries(counts).filter(([, v]) => v > 0).map(([k, v]) => (
          <Box key={k} sx={{
            px: 1.2, py: 0.4, borderRadius: '6px', fontSize: 11, fontWeight: 700,
            color: k === 'PASS' ? C.green : k === 'FAIL' ? C.red : k === 'WARNING' ? C.amber : '#94A3B8',
            bgcolor: k === 'PASS' ? 'rgba(16,185,129,0.1)' : k === 'FAIL' ? 'rgba(239,68,68,0.1)' : k === 'WARNING' ? 'rgba(245,158,11,0.1)' : 'rgba(148,163,184,0.1)',
          }}>{v} {k}</Box>
        ))}
      </Box>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.8 }}>
        {rules.map(r => (
          <Box key={r.id} sx={{
            display: 'flex', alignItems: 'flex-start', gap: 1.5, p: 1.5, borderRadius: '9px',
            bgcolor: r.status === 'PASS' ? 'rgba(16,185,129,0.04)' : r.status === 'FAIL' ? 'rgba(239,68,68,0.04)' : r.status === 'WARNING' ? 'rgba(245,158,11,0.04)' : '#F8FAFC',
            border: `1px solid ${r.status === 'PASS' ? 'rgba(16,185,129,0.15)' : r.status === 'FAIL' ? 'rgba(239,68,68,0.15)' : r.status === 'WARNING' ? 'rgba(245,158,11,0.15)' : '#E2E8F0'}`,
          }}>
            <Box sx={{ mt: 0.2, flexShrink: 0 }}>
              {r.status === 'PASS'    ? <CheckCircle sx={{ fontSize: 15, color: C.green }} /> :
               r.status === 'FAIL'    ? <ErrorIcon   sx={{ fontSize: 15, color: C.red   }} /> :
               r.status === 'WARNING' ? <Warning     sx={{ fontSize: 15, color: C.amber }} /> :
                                        <HourglassEmpty sx={{ fontSize: 15, color: '#94A3B8' }} />}
            </Box>
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography sx={{ fontSize: 12, fontWeight: 600, color: '#1E293B' }}>{r.rule_name ?? r.rule_code}</Typography>
              {r.reason && <Typography sx={{ fontSize: 11, color: '#64748B', mt: 0.3 }}>{r.reason}</Typography>}
              {(r.expected_value || r.actual_value) && (
                <Box sx={{ display: 'flex', gap: 2, mt: 0.5, flexWrap: 'wrap' }}>
                  {r.expected_value && <Box><Typography sx={{ fontSize: 9, color: '#94A3B8', fontWeight: 700 }}>EXPECTED</Typography><Typography sx={{ fontSize: 11 }}>{r.expected_value}</Typography></Box>}
                  {r.actual_value   && <Box><Typography sx={{ fontSize: 9, color: '#94A3B8', fontWeight: 700 }}>ACTUAL</Typography><Typography sx={{ fontSize: 11, color: r.status === 'FAIL' ? C.red : '#1E293B', fontWeight: 700 }}>{r.actual_value}</Typography></Box>}
                </Box>
              )}
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function InvoiceHub({ embedded = false }: { embedded?: boolean }) {
  const { user, logout } = useAuthStore()
  const { notifications, setNotifications } = useUIStore()
  const qc = useQueryClient()
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [notifAnchor, setNotifAnchor] = useState<null | HTMLElement>(null)
  const [avatarAnchor, setAvatarAnchor] = useState<null | HTMLElement>(null)
  const [snack, setSnack] = useState<{ msg: string; color: string } | null>(null)
  const [page] = useState(1)

  const { data: stats } = useQuery<DashboardStats>({
    queryKey: ['stats'],
    queryFn: async () => { const { data } = await dashboardApi.stats(); return data },
    refetchInterval: 30_000,
  })

  useQuery({
    queryKey: ['notifications'],
    queryFn: async () => {
      const { data } = await dashboardApi.notifications()
      const list = Array.isArray(data) ? data : []
      setNotifications(list)
      return list
    },
    refetchInterval: 30_000,
  })

  const { data: docs, isLoading: loadDocs, refetch } = useQuery({
    queryKey: ['documents', statusFilter, page],
    queryFn: async () => {
      const params: Record<string, unknown> = { page, page_size: 50 }
      if (statusFilter) params.status = statusFilter
      const { data } = await documentsApi.list(params)
      return (Array.isArray(data) ? data : data?.items ?? []) as Document[]
    },
    refetchInterval: 15_000,
  })

  const filtered = (docs ?? []).filter(d => {
    if (!search) return true
    const s = search.toLowerCase()
    return (
      d.document_id?.toLowerCase().includes(s) ||
      d.original_filename?.toLowerCase().includes(s) ||
      d.vendor_name?.toLowerCase().includes(s) ||
      d.invoice_number?.toLowerCase().includes(s)
    )
  })

  const unread = notifications.filter(n => !n.is_read).length

  const handleUploaded = (doc: { document_id: string }) => {
    setSnack({ msg: `Processing started for ${doc.document_id}`, color: C.green })
    setTimeout(() => { qc.invalidateQueries({ queryKey: ['documents'] }); qc.invalidateQueries({ queryKey: ['stats'] }) }, 2000)
  }

  const processInFlight = (docs ?? []).filter(d => ['PROCESSING','EXTRACTING','VALIDATING','MATCHING'].includes(d.status)).length
  const exceptionCount  = stats?.open_exceptions ?? 0
  const approvalCount   = stats?.pending_approvals ?? 0

  return (
    <Box sx={{
      display: 'flex', flexDirection: 'column',
      height: embedded ? 'calc(100vh - 64px)' : '100vh',
      bgcolor: C.navy, overflow: 'hidden',
    }}>

      {/* ── TOP BAR — only shown when NOT embedded inside Layout ──────────── */}
      {!embedded && (
        <>
          <Box sx={{
            height: 56, flexShrink: 0,
            display: 'flex', alignItems: 'center', px: 3, gap: 2,
            bgcolor: C.navyMid, borderBottom: `1px solid ${C.border}`,
          }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
              <Box sx={{ width: 30, height: 30, borderRadius: '8px', bgcolor: C.blue, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Receipt sx={{ fontSize: 17, color: 'white' }} />
              </Box>
              <Box>
                <Typography sx={{ fontSize: 14, fontWeight: 800, color: C.text, lineHeight: 1 }}>AP Invoice Hub</Typography>
                <Typography sx={{ fontSize: 10, color: C.textDim, lineHeight: 1 }}>Accounts Payable Automation</Typography>
              </Box>
            </Box>
            <Box sx={{ flex: 1 }} />
            {processInFlight > 0 && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, px: 1.5, py: 0.5, borderRadius: '8px', bgcolor: 'rgba(59,126,244,0.12)', border: '1px solid rgba(59,126,244,0.25)' }}>
                <CircularProgress size={10} sx={{ color: C.blue }} />
                <Typography sx={{ fontSize: 11, color: C.blue, fontWeight: 700 }}>{processInFlight} processing</Typography>
              </Box>
            )}
            {exceptionCount > 0 && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.8, px: 1.5, py: 0.5, borderRadius: '8px', bgcolor: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.25)' }}>
                <Warning sx={{ fontSize: 13, color: C.red }} />
                <Typography sx={{ fontSize: 11, color: C.red, fontWeight: 700 }}>{exceptionCount} exceptions</Typography>
              </Box>
            )}
            <IconButton size="small" onClick={(e) => setNotifAnchor(e.currentTarget)} sx={{ color: C.textDim }}>
              <Badge badgeContent={unread} color="error" sx={{ '& .MuiBadge-badge': { fontSize: 9, minWidth: 15, height: 15 } }}>
                <Notifications sx={{ fontSize: 19 }} />
              </Badge>
            </IconButton>
            <Box onClick={(e) => setAvatarAnchor(e.currentTarget)}
              sx={{ display: 'flex', alignItems: 'center', gap: 1, cursor: 'pointer', px: 1.5, py: 0.5, borderRadius: '8px', '&:hover': { bgcolor: 'rgba(255,255,255,0.05)' } }}>
              <Avatar sx={{ width: 26, height: 26, fontSize: 11, bgcolor: C.blue, fontWeight: 800 }}>
                {user?.name?.[0]?.toUpperCase()}
              </Avatar>
              <Box>
                <Typography sx={{ fontSize: 12, fontWeight: 700, color: C.text, lineHeight: 1 }}>{user?.name}</Typography>
                <Typography sx={{ fontSize: 10, color: C.textDim, lineHeight: 1 }}>{user?.role}</Typography>
              </Box>
            </Box>
          </Box>

          <Menu anchorEl={notifAnchor} open={Boolean(notifAnchor)} onClose={() => setNotifAnchor(null)}
            PaperProps={{ sx: { width: 340, maxHeight: 380, borderRadius: '12px', mt: 1 } }}>
            <Box sx={{ px: 2, py: 1.5, borderBottom: '1px solid #F1F5F9' }}>
              <Typography sx={{ fontWeight: 700, fontSize: 13 }}>Notifications</Typography>
            </Box>
            {notifications.slice(0, 8).map(n => (
              <MenuItem key={n.id} onClick={() => setNotifAnchor(null)}
                sx={{ bgcolor: n.is_read ? 'transparent' : 'rgba(59,126,244,0.04)', py: 1.5, px: 2, whiteSpace: 'normal' }}>
                <Box>
                  <Typography sx={{ fontSize: 12, fontWeight: 600 }}>{n.title}</Typography>
                  {n.body && <Typography sx={{ fontSize: 11, color: '#64748B', mt: 0.2 }}>{n.body}</Typography>}
                </Box>
              </MenuItem>
            ))}
            {notifications.length === 0 && (
              <Box sx={{ p: 3, textAlign: 'center' }}><Typography sx={{ fontSize: 13, color: '#94A3B8' }}>No notifications</Typography></Box>
            )}
          </Menu>

          <Menu anchorEl={avatarAnchor} open={Boolean(avatarAnchor)} onClose={() => setAvatarAnchor(null)}
            PaperProps={{ sx: { minWidth: 180, borderRadius: '10px', mt: 1 } }}>
            <Box sx={{ px: 2, py: 1.5 }}>
              <Typography sx={{ fontSize: 13, fontWeight: 700 }}>{user?.name}</Typography>
              <Typography sx={{ fontSize: 11, color: '#64748B' }}>{user?.email}</Typography>
            </Box>
            <Divider />
            <MenuItem onClick={() => { logout(); setAvatarAnchor(null) }} sx={{ fontSize: 13, gap: 1, py: 1.2 }}>
              <Logout sx={{ fontSize: 16 }} /> Sign out
            </MenuItem>
          </Menu>
        </>
      )}

      {/* ── BODY ────────────────────────────────────────────────────────────── */}
      <Box sx={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* LEFT COLUMN */}
        <Box sx={{
          width: selectedDocId ? 520 : '100%',
          maxWidth: selectedDocId ? 520 : '100%',
          flexShrink: 0,
          display: 'flex', flexDirection: 'column',
          transition: 'all 0.25s ease',
          overflow: 'hidden',
        }}>

          {/* KPI strip */}
          <Box sx={{ px: 2.5, pt: 2, pb: 1.5, display: 'flex', gap: 1.5, flexWrap: 'wrap' }}>
            <KpiCard label="Total Invoices"   value={stats?.total_documents ?? '—'} sub={`${stats?.documents_today ?? 0} today`} color={C.blue} />
            <KpiCard label="Processing"        value={processInFlight}                sub="in pipeline"                           color={C.purple} />
            <KpiCard label="Open Exceptions"   value={exceptionCount}                 sub="need attention"                        color={C.red} />
            <KpiCard label="Pending Approvals" value={approvalCount}                  sub="awaiting action"                       color={C.amber} />
            {stats?.matching_rate != null && (
              <KpiCard label="Match Rate" value={`${Number(stats.matching_rate).toFixed(1)}%`} sub="auto-matched" color={C.green} />
            )}
          </Box>

          {/* Upload + filter row */}
          <Box sx={{ px: 2.5, pb: 1.5, display: 'flex', gap: 1.5, alignItems: 'stretch' }}>
            <Box sx={{ flex: '0 0 280px' }}>
              <UploadZone onUploaded={handleUploaded} />
            </Box>
            <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <TextField
                size="small" fullWidth placeholder="Search by ID, vendor, filename…"
                value={search} onChange={e => setSearch(e.target.value)}
                InputProps={{
                  startAdornment: <InputAdornment position="start"><Search sx={{ fontSize: 17, color: '#94A3B8' }} /></InputAdornment>,
                  sx: { bgcolor: C.navyCard, color: C.text, borderRadius: '9px',
                    '& input': { color: C.text, fontSize: 13 },
                    '& fieldset': { borderColor: C.border },
                    '&:hover fieldset': { borderColor: 'rgba(255,255,255,0.2)' },
                  },
                }}
              />
              <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                <FormControl size="small" sx={{ minWidth: 160 }}>
                  <Select
                    value={statusFilter}
                    onChange={e => setStatusFilter(e.target.value)}
                    displayEmpty
                    sx={{ bgcolor: C.navyCard, color: C.text, borderRadius: '9px', fontSize: 12,
                      '& fieldset': { borderColor: C.border },
                      '& .MuiSvgIcon-root': { color: C.textDim },
                    }}
                  >
                    <MenuItem value="">All Statuses</MenuItem>
                    {['PROCESSING','EXCEPTION','HUMAN_REVIEW_REQUIRED','PENDING_APPROVAL','APPROVED','COMPLETED','FAILED','REJECTED'].map(s => (
                      <MenuItem key={s} value={s} sx={{ fontSize: 12 }}>{STATUS_META[s]?.label ?? s}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Tooltip title="Refresh">
                  <IconButton size="small" onClick={() => refetch()} sx={{ color: C.textDim }}>
                    <Refresh sx={{ fontSize: 17 }} />
                  </IconButton>
                </Tooltip>
                <Typography sx={{ fontSize: 11, color: C.textDim, ml: 'auto' }}>
                  {filtered.length} invoices
                </Typography>
              </Box>
            </Box>
          </Box>

          {/* Document table */}
          <Box sx={{ flex: 1, overflowY: 'auto', px: 2.5, pb: 2 }}>
            <Box sx={{
              bgcolor: C.navyCard, border: `1px solid ${C.border}`,
              borderRadius: '12px', overflow: 'hidden',
            }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: 'rgba(255,255,255,0.03)' }}>
                    {(selectedDocId
                      ? ['Document', 'Status', 'Amount']
                      : ['Document', 'Vendor', 'Invoice #', 'Amount', 'Status', 'Updated']
                    ).map(h => (
                      <th key={h} style={{ padding: '10px 14px', textAlign: 'left', color: C.textDim, fontWeight: 700, fontSize: 10, letterSpacing: 0.6, borderBottom: `1px solid ${C.border}`, whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {loadDocs ? (
                    Array.from({ length: 6 }).map((_, i) => (
                      <tr key={i}>
                        <td colSpan={6} style={{ padding: '12px 14px' }}>
                          <Box sx={{ height: 18, bgcolor: 'rgba(255,255,255,0.05)', borderRadius: 1, width: `${60 + i * 6}%` }} />
                        </td>
                      </tr>
                    ))
                  ) : filtered.length === 0 ? (
                    <tr>
                      <td colSpan={6} style={{ padding: '40px 14px', textAlign: 'center', color: C.textDim, fontSize: 13 }}>
                        No invoices found
                      </td>
                    </tr>
                  ) : filtered.map(d => {
                    const isSelected = d.id === selectedDocId
                    const hasExc = d.status === 'EXCEPTION' || d.status === 'HUMAN_REVIEW_REQUIRED'
                    return (
                      <tr
                        key={d.id}
                        onClick={() => setSelectedDocId(isSelected ? null : d.id)}
                        style={{
                          cursor: 'pointer',
                          background: isSelected ? 'rgba(59,126,244,0.1)' : hasExc ? 'rgba(239,68,68,0.04)' : 'transparent',
                          borderBottom: `1px solid ${C.border}`,
                          transition: 'background 0.12s',
                        }}
                        onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.03)' }}
                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = isSelected ? 'rgba(59,126,244,0.1)' : hasExc ? 'rgba(239,68,68,0.04)' : 'transparent' }}
                      >
                        <td style={{ padding: '11px 14px' }}>
                          <Typography sx={{ fontSize: 12, fontWeight: 700, color: C.text, fontFamily: 'monospace' }}>{d.document_id}</Typography>
                          <Typography sx={{ fontSize: 10, color: C.textDim }} noWrap>{d.original_filename}</Typography>
                        </td>
                        {!selectedDocId && (
                          <>
                            <td style={{ padding: '11px 14px' }}>
                              <Typography sx={{ fontSize: 12, color: C.text }} noWrap>{d.vendor_name ?? '—'}</Typography>
                            </td>
                            <td style={{ padding: '11px 14px' }}>
                              <Typography sx={{ fontSize: 12, color: C.textDim, fontFamily: 'monospace' }}>{d.invoice_number ?? '—'}</Typography>
                            </td>
                          </>
                        )}
                        <td style={{ padding: '11px 14px', whiteSpace: 'nowrap' }}>
                          <Typography sx={{ fontSize: 12, fontWeight: 600, color: C.text }}>{fmt(d.total_amount)}</Typography>
                        </td>
                        <td style={{ padding: '11px 14px' }}>
                          <StatusBadge status={d.status} />
                        </td>
                        {!selectedDocId && (
                          <td style={{ padding: '11px 14px' }}>
                            <Typography sx={{ fontSize: 11, color: C.textDim }}>{age(d.updated_at ?? d.created_at)}</Typography>
                          </td>
                        )}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </Box>
          </Box>
        </Box>

        {/* ── DETAIL PANEL ──────────────────────────────────────────────────── */}
        {selectedDocId && (
          <Box sx={{
            flex: 1, minWidth: 0, borderLeft: `1px solid ${C.border}`,
            bgcolor: 'white', overflow: 'hidden', display: 'flex', flexDirection: 'column',
          }}>
            <DocPanel docId={selectedDocId} onClose={() => setSelectedDocId(null)} />
          </Box>
        )}
      </Box>

      {/* Snackbar */}
      <Snackbar
        open={!!snack} autoHideDuration={4000} onClose={() => setSnack(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert severity="success" onClose={() => setSnack(null)} sx={{ fontSize: 13 }}>
          {snack?.msg}
        </Alert>
      </Snackbar>
    </Box>
  )
}
