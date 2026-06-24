import React, { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Box, Tabs, Tab, Typography, Card, CardContent, Grid, Chip, CircularProgress,
  Table, TableBody, TableCell, TableHead, TableRow, Alert, LinearProgress,
  List, ListItem, ListItemText, Stepper, Step, StepLabel, StepContent,
  Accordion, AccordionSummary, AccordionDetails, Button, Stack, Divider,
  Dialog, DialogTitle, DialogContent, IconButton,
} from '@mui/material'
import {
  ArrowBack, ExpandMore, CheckCircle, Cancel, Warning,
  TrendingUp, TrendingDown, TrendingFlat, AutoAwesome, Close, PauseCircle,
} from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'
import { documentsApi } from '../../api/client'
import type { Document, WorkflowState, ValidationResult, MatchingResult, AuditLog } from '../../types'
import { formatDate, formatDateTime } from '../../utils/format'

const STATUS_COLOR: Record<string, any> = {
  PASS: 'success', FAIL: 'error', WARNING: 'warning', SKIPPED: 'default',
}

const PIPELINE_STAGES = [
  { key: 'INTAKE',                      agentId: 'INTAKE_AGENT',                   label: 'Intake',      agent: 'Intake Agent',          hideWhen: null },
  { key: 'DOCUMENT_CLASSIFICATION',     agentId: 'CLASSIFICATION_AGENT',           label: 'Classify',    agent: 'Classification Agent',  hideWhen: null },
  { key: 'OCR',                         agentId: 'OCR_AGENT',                      label: 'OCR',         agent: 'OCR Agent',              hideWhen: 'NOT_SCANNED' },
  { key: 'HANDWRITING_AGENT',           agentId: 'HANDWRITING_AGENT',              label: 'Vision OCR',  agent: 'Handwriting Agent',     hideWhen: 'NOT_HANDWRITTEN' },
  { key: 'EXTRACTION',                  agentId: 'EXTRACTION_AGENT',               label: 'Extract',     agent: 'Extraction Agent',      hideWhen: null },
  { key: 'UNIVERSAL_VALIDATION',        agentId: 'UNIVERSAL_VALIDATION_AGENT',     label: 'Validate',    agent: 'Validation Agent',      hideWhen: null },
  { key: 'BUSINESS_PROFILE_PREDICTION', agentId: 'BUSINESS_PROFILE_AGENT',         label: 'Profile',     agent: 'Biz Profile Agent',     hideWhen: null },
  { key: 'PROFILE_VALIDATION',          agentId: 'PROFILE_VALIDATION_AGENT',       label: 'Prof. Valid', agent: 'Profile Validator',     hideWhen: null },
  { key: 'MATCHING',                    agentId: 'MATCHING_AGENT',                 label: 'Match',       agent: 'Matching Agent',        hideWhen: null },
  { key: 'EXCEPTION',                   agentId: 'EXCEPTION_AGENT',                label: 'Exception',   agent: 'Exception Agent',       hideWhen: 'NO_EXCEPTION' },
  { key: 'APPROVAL',                    agentId: 'APPROVAL_AGENT',                 label: 'Approval',    agent: 'Approval Agent',        hideWhen: null },
  { key: 'ERP_POSTING',                 agentId: 'ERP_POSTING_AGENT',              label: 'ERP Post',    agent: 'ERP Posting Agent',     hideWhen: null },
  { key: 'PAYMENT_SCHEDULING',          agentId: 'PAYMENT_AGENT',                  label: 'Payment',     agent: 'Payment Agent',         hideWhen: null },
]

function TabPanel({ children, value, index }: { children: React.ReactNode; value: number; index: number }) {
  return value === index ? <Box sx={{ pt: 2 }}>{children}</Box> : null
}

export default function DocumentDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [tab, setTab] = useState(0)
  const [aiDialogOpen, setAiDialogOpen] = useState(false)

  const { data: doc, isLoading } = useQuery<Document>({
    queryKey: ['document', id],
    queryFn: async () => { const { data } = await documentsApi.get(id!); return data },
    enabled: !!id,
    refetchInterval: (query) => {
      const s = (query.state.data as any)?.status
      return s && ['COMPLETED','POSTED','APPROVED','FAILED','REJECTED'].includes(s) ? false : 2000
    },
  })

  const { data: workflow } = useQuery<WorkflowState>({
    queryKey: ['workflow', id],
    queryFn: async () => { const { data } = await documentsApi.getWorkflow(id!); return data },
    enabled: !!id,
    refetchInterval: (query) => {
      const status = (query.state.data as any)?.current_stage
      const pct = (query.state.data as any)?.progress_percent ?? 0
      return pct >= 100 ? false : 2000
    },
  })

  const { data: validations = [] } = useQuery<ValidationResult[]>({
    queryKey: ['validations', id],
    queryFn: async () => { const { data } = await documentsApi.getValidation(id!); return data },
    enabled: !!id,
  })

  const { data: matching } = useQuery<MatchingResult>({
    queryKey: ['matching', id],
    queryFn: async () => { const { data } = await documentsApi.getMatching(id!); return data },
    enabled: !!id,
  })

  const { data: auditLogs = [] } = useQuery<AuditLog[]>({
    queryKey: ['audit', id],
    queryFn: async () => { const { data } = await documentsApi.getAuditTrail(id!); return data },
    enabled: !!id,
  })

  const { data: explanation } = useQuery<any>({
    queryKey: ['explanation', id],
    queryFn: async () => { const { data } = await documentsApi.getExplanation(id!); return data },
    enabled: !!id && aiDialogOpen,
  })

  if (isLoading) return (
    <Box>
      <Box sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 2 }}>
        <Box sx={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 0.5, color: 'text.secondary' }}
          onClick={() => navigate('/documents')}>
          <ArrowBack fontSize="small" /> Back
        </Box>
        <Typography variant="h6" fontWeight={700} color="text.secondary">Loading document…</Typography>
      </Box>
      <Card sx={{ mb: 2 }}>
        <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 2 }}>
          <CircularProgress size={24} />
          <Box>
            <Typography fontWeight={600}>Pipeline starting…</Typography>
            <Typography variant="caption" color="text.secondary">AI agents are processing your document. This page will update automatically.</Typography>
          </Box>
        </CardContent>
      </Card>
    </Box>
  )
  if (!doc) return <Alert severity="error">Document not found</Alert>

  const passCount = validations.filter((v) => v.status === 'PASS').length
  const failCount = validations.filter((v) => v.status === 'FAIL').length
  const warnCount = validations.filter((v) => v.status === 'WARNING').length

  return (
    <Box>
      <Box sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 2 }}>
        <Box
          sx={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 0.5, color: 'text.secondary' }}
          onClick={() => navigate('/documents')}
        >
          <ArrowBack fontSize="small" /> Back
        </Box>
        <Typography variant="h6" fontWeight={700}>{doc.document_id}</Typography>
        <Chip label={doc.status.replace(/_/g, ' ')} size="small" color={doc.status === 'COMPLETED' || doc.status === 'APPROVED' ? 'success' : doc.status === 'FAILED' ? 'error' : 'info'} />
        {doc.business_profile && <Chip label={doc.business_profile.replace(/_/g, ' ')} size="small" variant="outlined" color="primary" />}
        <Box sx={{ flexGrow: 1 }} />
        <Button
          variant="contained"
          size="small"
          startIcon={<AutoAwesome />}
          onClick={() => setAiDialogOpen(true)}
          sx={{ bgcolor: '#7b1fa2', '&:hover': { bgcolor: '#6a1b9a' } }}
        >
          AI Explanation
        </Button>
        <Button
          variant="outlined"
          size="small"
          onClick={() => window.open(`${import.meta.env.VITE_API_URL || ''}/api/v1/documents/${doc.id}/file`, '_blank')}
        >
          View Original Invoice
        </Button>
      </Box>

      {/* Processing Pipeline Strip */}
      {workflow && (
        <Card sx={{ mb: 2 }}>
          <CardContent sx={{ py: 1.5, px: 2, '&:last-child': { pb: 1.5 } }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5 }}>
              <Typography variant="caption" fontWeight={700} sx={{ textTransform: 'uppercase', letterSpacing: 0.8, color: 'text.secondary' }}>
                Processing Pipeline
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Typography variant="caption" fontWeight={700} color={workflow.progress_percent >= 100 ? 'success.main' : 'primary.main'}>
                  {workflow.progress_percent}%
                </Typography>
                {workflow.current_stage && (
                  <Chip
                    label={workflow.current_stage.replace(/_/g, ' ')}
                    size="small"
                    color={workflow.progress_percent >= 100 ? 'success' : 'info'}
                    sx={{ fontSize: 10, height: 20 }}
                  />
                )}
              </Box>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'flex-start', overflowX: 'auto', pb: 1 }}>
              {(() => {
                const pipelineDone = workflow.progress_percent >= 100 ||
                  ['COMPLETED', 'POSTED', 'APPROVED', 'FAILED', 'EXCEPTION', 'HUMAN_REVIEW_REQUIRED', 'REJECTED'].includes(doc.status)
                const history: any[] = workflow.stage_history || []
                const docStatus = doc.status
                const docType   = doc.doc_type || ''

                // Pre-compute status for every stage so we can filter before rendering
                const stagesWithStatus = PIPELINE_STAGES.map((stage) => {
                  // Two ways a stage appears in history:
                  // (a) h.stage === stage.key  → previous agent's handoff entry ("next stage is X")
                  // (b) h.agent === agentId && h.stage === agentId → this agent's own on-entry record
                  const ownIdx     = history.findIndex((h: any) => h.agent === stage.agentId && h.stage === stage.agentId)
                  const handoffIdx = history.findIndex((h: any) => h.stage === stage.key)
                  const histIdx    = ownIdx >= 0 ? ownIdx : handoffIdx
                  const histEntry  = histIdx >= 0 ? history[histIdx] : null
                  const timedEntry = ownIdx >= 0 ? history[ownIdx] : histEntry

                  let status: 'WAITING' | 'RUNNING' | 'COMPLETED' | 'ERROR' | 'STUCK' = 'WAITING'
                  if (histEntry) {
                    if (histEntry.status === 'ERROR') {
                      status = 'ERROR'
                    } else if (histEntry.status === 'COMPLETED' || histIdx < history.length - 1 || pipelineDone) {
                      status = 'COMPLETED'
                    } else {
                      status = 'RUNNING'
                    }
                  }

                  // Override to STUCK (orange) when doc is held at APPROVAL or EXCEPTION
                  if (status === 'RUNNING' || status === 'COMPLETED') {
                    if (stage.key === 'APPROVAL' && ['PENDING_APPROVAL', 'AWAITING_APPROVAL'].includes(docStatus)) {
                      status = 'STUCK'
                    }
                    if (stage.key === 'EXCEPTION' && ['EXCEPTION', 'HUMAN_REVIEW_REQUIRED'].includes(docStatus)) {
                      status = 'STUCK'
                    }
                  }

                  return { stage, histEntry, timedEntry, status }
                })

                // Filter out non-applicable WAITING stages
                const visibleStages = stagesWithStatus.filter(({ stage, status }) => {
                  if (status !== 'WAITING') return true   // always show reached stages
                  if (stage.hideWhen === 'NOT_SCANNED' && docType !== 'SCANNED') return false
                  if (stage.hideWhen === 'NOT_HANDWRITTEN' && docType !== 'HANDWRITTEN') return false
                  if (stage.hideWhen === 'NO_EXCEPTION' &&
                      !['EXCEPTION', 'HUMAN_REVIEW_REQUIRED'].includes(docStatus)) return false
                  return true
                })

                return visibleStages.map(({ stage, timedEntry, status }, visIdx) => {
                  const circleColor =
                    status === 'COMPLETED' ? '#4caf50' :
                    status === 'ERROR'     ? '#f44336' :
                    status === 'RUNNING'   ? '#1976d2' :
                    status === 'STUCK'     ? '#e65100' : '#bdbdbd'
                  const circleBg =
                    status === 'COMPLETED' ? '#e8f5e9' :
                    status === 'ERROR'     ? '#ffebee' :
                    status === 'RUNNING'   ? '#e3f2fd' :
                    status === 'STUCK'     ? '#fff3e0' : '#fafafa'
                  const labelColor =
                    status === 'WAITING'   ? '#bdbdbd' :
                    status === 'RUNNING'   ? 'primary.main' :
                    status === 'ERROR'     ? 'error.main' :
                    status === 'STUCK'     ? '#e65100' : 'text.primary'

                  return (
                    <React.Fragment key={stage.key}>
                      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 82, maxWidth: 82 }}>
                        <Box sx={{
                          width: 36, height: 36, borderRadius: '50%',
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          bgcolor: circleBg,
                          border: `2px solid ${circleColor}`,
                          boxShadow:
                            status === 'RUNNING' ? `0 0 0 4px rgba(25,118,210,0.14)` :
                            status === 'STUCK'   ? `0 0 0 4px rgba(230,81,0,0.18)` : 'none',
                          transition: 'all 0.3s',
                        }}>
                          {status === 'COMPLETED' && <CheckCircle    sx={{ fontSize: 18, color: '#4caf50' }} />}
                          {status === 'ERROR'     && <Cancel         sx={{ fontSize: 18, color: '#f44336' }} />}
                          {status === 'RUNNING'   && <CircularProgress size={16} color="primary" />}
                          {status === 'STUCK'     && <PauseCircle    sx={{ fontSize: 18, color: '#e65100' }} />}
                          {status === 'WAITING'   && <Typography variant="caption" sx={{ fontSize: 11, color: '#bdbdbd', fontWeight: 700 }}>{visIdx + 1}</Typography>}
                        </Box>
                        <Typography sx={{
                          fontSize: 10, fontWeight: status === 'RUNNING' || status === 'STUCK' ? 700 : 600, mt: 0.6,
                          color: labelColor, textAlign: 'center', lineHeight: 1.3, px: 0.5,
                        }}>
                          {stage.label}
                        </Typography>
                        <Typography sx={{
                          fontSize: 9, textAlign: 'center', lineHeight: 1.2, mt: 0.25, px: 0.5,
                          color: status === 'WAITING' ? '#d0d0d0' : '#9e9e9e', fontStyle: 'italic',
                        }}>
                          {stage.agent}
                        </Typography>
                        {timedEntry?.started_at && status !== 'WAITING' && (
                          <Typography sx={{ fontSize: 8, color: '#bdbdbd', textAlign: 'center', mt: 0.3 }}>
                            {new Date(timedEntry.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </Typography>
                        )}
                      </Box>
                      {visIdx < visibleStages.length - 1 && (
                        <Box sx={{
                          flexShrink: 0, width: 20, height: 2, mt: '17px',
                          bgcolor:
                            status === 'COMPLETED' ? '#4caf50' :
                            status === 'ERROR'     ? '#f44336' :
                            status === 'STUCK'     ? '#e65100' : '#e0e0e0',
                          transition: 'background-color 0.4s',
                        }} />
                      )}
                    </React.Fragment>
                  )
                })
              })()}
            </Box>
          </CardContent>
        </Card>
      )}

      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto" sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label="Overview" />
        <Tab label="Extracted Data" />
        <Tab label={`Validation (${passCount}P / ${failCount}F / ${warnCount}W)`} />
        <Tab label="2-Way Match" />
        <Tab label="3-Way Match" />
        <Tab label="OCR / Source Text" />
        <Tab label="Audit Trail" />
      </Tabs>

      {/* Overview */}
      <TabPanel value={tab} index={0}>
        <Grid container spacing={2}>
          {/* Classification summary banner */}
          <Grid item xs={12}>
            <Card>
              <CardContent sx={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
                <Box>
                  <Typography variant="caption" color="text.secondary">Document Type (OCR Classification)</Typography>
                  <Typography variant="h6" fontWeight={700}>{doc.doc_type || '—'}</Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">PO / Non-PO</Typography>
                  <Box sx={{ mt: 0.5 }}>
                    <Chip
                      label={doc.business_profile?.startsWith('PO_') ? 'PO' : (doc.business_profile ? 'NON-PO' : '—')}
                      color={doc.business_profile?.startsWith('PO_') ? 'primary' : 'default'}
                      size="small"
                    />
                  </Box>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Business Profile</Typography>
                  <Typography variant="h6" fontWeight={700}>{doc.business_profile?.replace(/_/g, ' ') || '—'}</Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">OCR Confidence</Typography>
                  <Typography variant="h6" fontWeight={700} color={
                    doc.ocr_confidence == null ? 'text.secondary' :
                    Number(doc.ocr_confidence) >= 0.85 ? 'success.main' :
                    Number(doc.ocr_confidence) >= 0.70 ? 'warning.main' : 'error.main'
                  }>
                    {doc.ocr_confidence != null ? `${(Number(doc.ocr_confidence) * 100).toFixed(0)}%` : 'N/A (digital)'}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="caption" color="text.secondary">Status</Typography>
                  <Box sx={{ mt: 0.5 }}>
                    <Chip label={doc.status.replace(/_/g, ' ')} size="small"
                      color={['COMPLETED','APPROVED','POSTED'].includes(doc.status) ? 'success' :
                             ['FAILED','EXCEPTION','REJECTED','HUMAN_REVIEW_REQUIRED'].includes(doc.status) ? 'error' : 'info'} />
                  </Box>
                </Box>
                {/* Language detection badge */}
                {(() => {
                  const meta = (doc.extracted_data as any)?._meta
                  if (!meta?.document_language || meta.document_language === 'Unknown') return null
                  const isEnglish = (meta.document_language_code || 'en') === 'en'
                  return (
                    <Box>
                      <Typography variant="caption" color="text.secondary">Document Language</Typography>
                      <Box sx={{ mt: 0.5, display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                        <Chip
                          label={meta.document_language}
                          size="small"
                          color={isEnglish ? 'default' : 'secondary'}
                          variant={isEnglish ? 'outlined' : 'filled'}
                        />
                        {meta.was_translated && (
                          <Chip label="Translated to English" size="small" color="info" variant="outlined" />
                        )}
                        {meta.is_indian_document === false && (
                          <Chip label="Non-Indian" size="small" variant="outlined" />
                        )}
                      </Box>
                    </Box>
                  )
                })()}
              </CardContent>
            </Card>
          </Grid>

          {/* Non-English translation notice */}
          {(() => {
            const meta = (doc.extracted_data as any)?._meta
            if (!meta?.was_translated) return null
            return (
              <Grid item xs={12}>
                <Alert severity="info" icon={false}>
                  <Typography variant="body2" fontWeight={700}>
                    Multilingual Invoice — Translated to English
                  </Typography>
                  <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                    This invoice was originally in <strong>{meta.document_language}</strong>.
                    All fields have been automatically extracted and translated to English by GPT-4o.
                    {meta.translation_notes ? ` Note: ${meta.translation_notes}` : ''}
                    Indian-specific validations (GSTIN/PAN/IFSC) are skipped for non-Indian documents.
                  </Typography>
                </Alert>
              </Grid>
            )
          })()}

          {/* Failure reason banner */}
          {workflow?.error_message && (
            <Grid item xs={12}>
              <Alert severity="error">
                <Typography variant="body2" fontWeight={700}>Processing stopped: {workflow.current_stage?.replace(/_/g,' ')}</Typography>
                <Typography variant="caption">{workflow.error_message}</Typography>
              </Alert>
            </Grid>
          )}

          <Grid item xs={12} md={6}>
            <Card>
              <CardContent>
                <Typography variant="subtitle2" fontWeight={700} gutterBottom>Document Information</Typography>
                {[
                  ['Document ID', doc.document_id],
                  ['File Name', doc.original_filename],
                  ['File Type', doc.doc_type || '—'],
                  ['File Size', `${(doc.file_size / 1024).toFixed(0)} KB`],
                  ['Source', doc.ingestion_source],
                  ['Uploaded', formatDateTime(doc.created_at)],
                ].map(([k, v]) => (
                  <Box key={k} sx={{ display: 'flex', py: 0.75, borderBottom: '1px solid #f0f0f0' }}>
                    <Typography variant="body2" color="text.secondary" sx={{ width: 140, flexShrink: 0 }}>{k}</Typography>
                    <Typography variant="body2" fontWeight={500}>{v}</Typography>
                  </Box>
                ))}
              </CardContent>
            </Card>
          </Grid>
          <Grid item xs={12} md={6}>
            <Card>
              <CardContent>
                <Typography variant="subtitle2" fontWeight={700} gutterBottom>Invoice Details</Typography>
                {(() => {
                  const ed: any = doc.extracted_data || {}
                  const refs = ed.references || {}
                  const ven = ed.vendor || {}
                  const vendorName = doc.vendor_name || ven.name || '—'
                  const poNum = doc.po_number || refs.po_number || '—'
                  const grnNum = doc.grn_number || refs.grn_number || '—'
                  const poStatus = doc.po_number ? '' : (refs.po_number ? ' (not in ERP master)' : '')
                  const venStatus = doc.vendor_name ? '' : (ven.name ? ' (not in vendor master)' : '')
                  return [
                  ['Invoice Number', doc.invoice_number || '—'],
                  ['Invoice Date', formatDate(doc.invoice_date)],
                  ['Vendor', vendorName + venStatus],
                  ['GSTIN', ven.gstin || '—'],
                  ['PO Number', poNum + poStatus],
                  ['GRN Number', grnNum],
                  ['Invoice Amount', doc.invoice_amount ? `₹${Number(doc.invoice_amount).toLocaleString('en-IN')}` : '—'],
                  ['Tax Amount', doc.tax_amount ? `₹${Number(doc.tax_amount).toLocaleString('en-IN')}` : '—'],
                  ['Total Amount', doc.total_amount ? `₹${Number(doc.total_amount).toLocaleString('en-IN')}` : '—'],
                ]})().map(([k, v]) => (
                  <Box key={k} sx={{ display: 'flex', py: 0.75, borderBottom: '1px solid #f0f0f0' }}>
                    <Typography variant="body2" color="text.secondary" sx={{ width: 140, flexShrink: 0 }}>{k}</Typography>
                    <Typography variant="body2" fontWeight={500}>{v}</Typography>
                  </Box>
                ))}
              </CardContent>
            </Card>
          </Grid>
          {doc.ai_profile_confidence && (
            <Grid item xs={12}>
              <Card sx={{ bgcolor: '#e8f4fd', border: '1px solid #90caf9' }}>
                <CardContent>
                  <Typography variant="subtitle2" fontWeight={700} color="primary" gutterBottom>
                    🤖 AI Profile Decision — {doc.business_profile?.replace(/_/g, ' ')} ({(Number(doc.ai_profile_confidence) * 100).toFixed(0)}% confidence)
                  </Typography>
                  <Typography variant="body2" color="text.secondary">{doc.ai_profile_reasoning}</Typography>
                </CardContent>
              </Card>
            </Grid>
          )}
        </Grid>
      </TabPanel>

      {/* Extracted Data */}
      <TabPanel value={tab} index={1}>
        <Card>
          <CardContent>
            <Typography variant="subtitle2" fontWeight={700} gutterBottom>Raw Extracted Fields</Typography>
            {doc.extracted_data ? (
              <Box component="pre" sx={{ fontSize: 12, overflow: 'auto', bgcolor: '#f5f5f5', p: 2, borderRadius: 2 }}>
                {JSON.stringify(doc.extracted_data, null, 2)}
              </Box>
            ) : (
              <Typography color="text.secondary">No extracted data available yet</Typography>
            )}
          </CardContent>
        </Card>
      </TabPanel>

      {/* Validation Results */}
      <TabPanel value={tab} index={2}>
        <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
          <Chip label={`${passCount} PASS`} color="success" icon={<CheckCircle />} />
          <Chip label={`${failCount} FAIL`} color="error" icon={<Cancel />} />
          <Chip label={`${warnCount} WARNING`} color="warning" icon={<Warning />} />
        </Box>
        <Table size="small" sx={{ tableLayout: 'fixed', width: '100%' }}>
          <TableHead>
            <TableRow>
              <TableCell>Rule</TableCell>
              <TableCell>Result</TableCell>
              <TableCell>Expected</TableCell>
              <TableCell>Actual</TableCell>
              <TableCell>Reason</TableCell>
              <TableCell>Agent</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {validations.map((v) => (
              <TableRow key={v.id} sx={{ bgcolor: v.status === 'FAIL' ? '#fff5f5' : v.status === 'WARNING' ? '#fffde7' : 'inherit', verticalAlign: 'top' }}>
                <TableCell sx={{ width: 160 }}><Typography variant="body2" fontWeight={600} sx={{ whiteSpace: 'normal', wordBreak: 'break-word' }}>{v.rule_name || v.rule_code}</Typography></TableCell>
                <TableCell sx={{ width: 90 }}><Chip label={v.status} size="small" color={STATUS_COLOR[v.status]} /></TableCell>
                <TableCell sx={{ width: 180 }}><Typography variant="caption" sx={{ whiteSpace: 'normal', wordBreak: 'break-all' }}>{v.expected_value || '—'}</Typography></TableCell>
                <TableCell sx={{ width: 150 }}><Typography variant="caption" sx={{ whiteSpace: 'normal', wordBreak: 'break-all' }}>{v.actual_value || '—'}</Typography></TableCell>
                <TableCell sx={{ minWidth: 200 }}><Typography variant="caption" sx={{ whiteSpace: 'normal', wordBreak: 'break-word' }}>{v.reason}</Typography></TableCell>
                <TableCell sx={{ width: 130 }}><Typography variant="caption" sx={{ whiteSpace: 'normal', wordBreak: 'break-word' }}>{v.agent}</Typography></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TabPanel>

      {/* 2-Way Match (Invoice vs PO only) */}
      <TabPanel value={tab} index={3}>
        {!matching || matching.match_status === 'NOT_APPLICABLE' ? (
          <Alert severity="info">
            <Typography variant="body2" fontWeight={700}>2-Way Matching Not Applicable</Typography>
            <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
              {doc.business_profile?.startsWith('PO_')
                ? `This is a PO-backed document but its PO (${doc.extracted_data?.references?.['po_number'] || 'referenced PO'}) was not found in the ERP. Upload an invoice with a PO number that exists in the system.`
                : `This is a NON-PO document (${doc.business_profile?.replace(/_/g, ' ')}). 2-way matching compares Invoice vs PO and requires a PO reference.`}
            </Typography>
          </Alert>
        ) : (
          <Grid container spacing={2}>
            <Grid item xs={12}>
              <Alert severity="info" icon={false}>
                <strong>2-Way Match</strong> compares the invoice directly against the Purchase Order — no GRN required.
                Use this view for service invoices or when goods receipt has not been recorded.
              </Alert>
            </Grid>

            {/* Score card */}
            <Grid item xs={12} md={4}>
              <Card>
                <CardContent sx={{ textAlign: 'center' }}>
                  <Typography variant="h3" fontWeight={700} color={matching.overall_match_score >= 0.8 ? 'success.main' : 'error.main'}>
                    {(matching.overall_match_score * 100).toFixed(0)}%
                  </Typography>
                  <Typography variant="subtitle2" color="text.secondary">2-Way Match Score</Typography>
                  <Chip
                    label={matching.match_status}
                    sx={{ mt: 1 }}
                    color={matching.match_status === 'MATCHED' ? 'success' : matching.match_status === 'TOLERANCE_MATCH' ? 'warning' : 'error'}
                  />
                </CardContent>
              </Card>
            </Grid>

            {/* Breakdown */}
            <Grid item xs={12} md={8}>
              <Card>
                <CardContent>
                  <Typography variant="subtitle2" fontWeight={700} gutterBottom>Invoice vs PO Checks</Typography>
                  {[
                    { label: 'Vendor Match', value: matching.vendor_match },
                    { label: 'Price Match', value: matching.price_match },
                    { label: 'Total Amount Match', value: matching.total_match },
                  ].map(({ label, value }) => (
                    <Box key={label} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.75, borderBottom: '1px solid #f0f0f0' }}>
                      <Typography variant="body2">{label}</Typography>
                      <Chip
                        label={value === null ? 'N/A' : value ? 'MATCH' : 'MISMATCH'}
                        size="small"
                        color={value === null ? 'default' : value ? 'success' : 'error'}
                      />
                    </Box>
                  ))}
                  {matching.variance_report && (
                    <Box sx={{ mt: 1.5, p: 1.5, bgcolor: '#f9f9f9', borderRadius: 1 }}>
                      <Typography variant="caption" fontWeight={700} display="block" gutterBottom>Amount Variance</Typography>
                      <Box sx={{ display: 'flex', gap: 4 }}>
                        <Box>
                          <Typography variant="caption" color="text.secondary">Invoice Total</Typography>
                          <Typography variant="body2" fontWeight={600}>₹{Number(matching.variance_report.invoice_total).toLocaleString('en-IN')}</Typography>
                        </Box>
                        <Box>
                          <Typography variant="caption" color="text.secondary">PO Total</Typography>
                          <Typography variant="body2" fontWeight={600}>₹{Number(matching.variance_report.po_total).toLocaleString('en-IN')}</Typography>
                        </Box>
                        <Box>
                          <Typography variant="caption" color="text.secondary">Variance</Typography>
                          <Typography variant="body2" fontWeight={600} color={matching.variance_report.total_variance === 0 ? 'success.main' : 'error.main'}>
                            ₹{Number(matching.variance_report.total_variance).toLocaleString('en-IN')}
                            {' '}({Number(matching.variance_report.total_variance_pct).toFixed(2)}%)
                          </Typography>
                        </Box>
                      </Box>
                    </Box>
                  )}
                  {matching.tolerance_applied && (
                    <Alert severity="info" sx={{ mt: 1 }} icon={<Warning />}>Tolerance rules applied</Alert>
                  )}
                </CardContent>
              </Card>
            </Grid>

            {/* Line-level Invoice vs PO (no GRN column) */}
            {matching.line_matches && matching.line_matches.length > 0 && (
              <Grid item xs={12}>
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" fontWeight={700} gutterBottom>Line-Level Invoice vs PO</Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                      Comparing what was ordered (PO) against what was billed (Invoice). No GRN column in 2-way.
                    </Typography>
                    <Box sx={{ overflowX: 'auto' }}>
                      <Table size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell rowSpan={2} sx={{ fontWeight: 700, verticalAlign: 'bottom' }}>Item</TableCell>
                            <TableCell colSpan={2} align="center" sx={{ bgcolor: '#e3f2fd', fontWeight: 700, borderLeft: '2px solid #fff' }}>PURCHASE ORDER</TableCell>
                            <TableCell colSpan={2} align="center" sx={{ bgcolor: '#fff3e0', fontWeight: 700, borderLeft: '2px solid #fff' }}>INVOICE</TableCell>
                            <TableCell colSpan={2} align="center" sx={{ bgcolor: '#f5f5f5', fontWeight: 700, borderLeft: '2px solid #fff' }}>RESULT</TableCell>
                          </TableRow>
                          <TableRow sx={{ '& th': { fontSize: 11, fontWeight: 600 } }}>
                            <TableCell align="right" sx={{ bgcolor: '#e3f2fd' }}>Qty</TableCell>
                            <TableCell align="right" sx={{ bgcolor: '#e3f2fd' }}>Unit Price</TableCell>
                            <TableCell align="right" sx={{ bgcolor: '#fff3e0' }}>Qty</TableCell>
                            <TableCell align="right" sx={{ bgcolor: '#fff3e0' }}>Unit Price</TableCell>
                            <TableCell align="center" sx={{ bgcolor: '#f5f5f5' }}>Price</TableCell>
                            <TableCell align="center" sx={{ bgcolor: '#f5f5f5' }}>Status</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {matching.line_matches.map((lm: any, i: number) => (
                            <TableRow key={i} sx={{ bgcolor: lm.status === 'MATCH' ? 'inherit' : '#fff5f5' }}>
                              <TableCell><Typography variant="caption" fontWeight={600}>{lm.item || `Line ${lm.line_number}`}</Typography></TableCell>
                              <TableCell align="right">{lm.po ? lm.po.qty : '—'}</TableCell>
                              <TableCell align="right">{lm.po ? `₹${lm.po.price}` : '—'}</TableCell>
                              <TableCell align="right">{lm.invoice ? lm.invoice.qty : '—'}</TableCell>
                              <TableCell align="right">{lm.invoice ? `₹${lm.invoice.price}` : '—'}</TableCell>
                              <TableCell align="center">
                                <Chip size="small" label={lm.price_ok ? '✓' : '✗'} color={lm.price_ok ? 'success' : 'error'} />
                              </TableCell>
                              <TableCell align="center">
                                <Chip size="small" label={lm.status}
                                  color={lm.status === 'MATCH' ? 'success' : lm.status === 'NO_PO_LINE' ? 'warning' : 'error'} />
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </Box>
                  </CardContent>
                </Card>
              </Grid>
            )}
          </Grid>
        )}
      </TabPanel>

      {/* 3-Way Match (Invoice vs PO vs GRN) */}
      <TabPanel value={tab} index={4}>
        {matching && matching.match_status === 'NOT_APPLICABLE' ? (
          <Alert severity="info">
            <Typography variant="body2" fontWeight={700}>3-Way Matching Not Applicable</Typography>
            <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
              {doc.business_profile?.startsWith('PO_')
                ? `This is a PO-backed document but its PO (${doc.extracted_data?.references?.['po_number'] || 'referenced PO'}) was not found in the ERP master data, so Invoice↔PO↔GRN matching could not run. ${matching.matching_notes || ''}`
                : `This is a NON-PO document (${doc.business_profile?.replace(/_/g, ' ')}), so 3-way PO/GRN matching does not apply. Such invoices are validated against vendor master, budget, and policy instead.`}
            </Typography>
          </Alert>
        ) : matching ? (
          <Grid container spacing={2}>
            <Grid item xs={12}>
              <Alert severity="info" icon={false}>
                <strong>3-Way Match</strong> validates the invoice against both the Purchase Order and the Goods Receipt Note (GRN).
                All three documents must agree on quantities and prices.
              </Alert>
            </Grid>

            <Grid item xs={12} md={4}>
              <Card>
                <CardContent sx={{ textAlign: 'center' }}>
                  <Typography variant="h3" fontWeight={700} color={matching.overall_match_score >= 0.8 ? 'success.main' : 'error.main'}>
                    {(matching.overall_match_score * 100).toFixed(0)}%
                  </Typography>
                  <Typography variant="subtitle2" color="text.secondary">Overall Match Score</Typography>
                  <Chip label={matching.match_status} sx={{ mt: 1 }}
                    color={matching.match_status === 'MATCHED' ? 'success' : matching.match_status === 'TOLERANCE_MATCH' ? 'warning' : 'error'} />
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} md={8}>
              <Card>
                <CardContent>
                  <Typography variant="subtitle2" fontWeight={700} gutterBottom>Match Breakdown</Typography>
                  {[
                    { label: 'Vendor Match', value: matching.vendor_match },
                    { label: 'Quantity Match (vs GRN)', value: matching.quantity_match },
                    { label: 'Price Match (vs PO)', value: matching.price_match },
                    { label: 'Tax Match', value: matching.tax_match },
                    { label: 'Total Match', value: matching.total_match },
                  ].map(({ label, value }) => (
                    <Box key={label} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.75, borderBottom: '1px solid #f0f0f0' }}>
                      <Typography variant="body2">{label}</Typography>
                      <Chip label={value === null ? 'N/A' : value ? 'MATCH' : 'MISMATCH'} size="small"
                        color={value === null ? 'default' : value ? 'success' : 'error'} />
                    </Box>
                  ))}
                  {matching.tolerance_applied && (
                    <Alert severity="info" sx={{ mt: 1 }} icon={<Warning />}>
                      Tolerance rules applied
                    </Alert>
                  )}
                </CardContent>
              </Card>
            </Grid>
            {/* Line-level 3-way table: PO vs GRN vs Invoice */}
            {matching.line_matches && matching.line_matches.length > 0 && (
              <Grid item xs={12}>
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" fontWeight={700} gutterBottom>
                      Line-Level 3-Way Match
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                      Ordered (PO) → Received (GRN) → Billed (Invoice). Quantity is verified Invoice vs GRN; unit price Invoice vs PO.
                    </Typography>
                    <Box sx={{ overflowX: 'auto' }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell rowSpan={2} sx={{ fontWeight: 700, verticalAlign: 'bottom' }}>Item</TableCell>
                          <TableCell colSpan={2} align="center" sx={{ bgcolor: '#e3f2fd', fontWeight: 700, borderLeft: '2px solid #fff' }}>PURCHASE ORDER</TableCell>
                          <TableCell colSpan={1} align="center" sx={{ bgcolor: '#e8f5e9', fontWeight: 700, borderLeft: '2px solid #fff' }}>GOODS RECEIPT</TableCell>
                          <TableCell colSpan={2} align="center" sx={{ bgcolor: '#fff3e0', fontWeight: 700, borderLeft: '2px solid #fff' }}>INVOICE</TableCell>
                          <TableCell colSpan={3} align="center" sx={{ bgcolor: '#f5f5f5', fontWeight: 700, borderLeft: '2px solid #fff' }}>RESULT</TableCell>
                        </TableRow>
                        <TableRow sx={{ '& th': { fontSize: 11, fontWeight: 600 } }}>
                          <TableCell align="right" sx={{ bgcolor: '#e3f2fd' }}>Qty</TableCell>
                          <TableCell align="right" sx={{ bgcolor: '#e3f2fd' }}>Unit Price</TableCell>
                          <TableCell align="right" sx={{ bgcolor: '#e8f5e9' }}>Qty Recd</TableCell>
                          <TableCell align="right" sx={{ bgcolor: '#fff3e0' }}>Qty</TableCell>
                          <TableCell align="right" sx={{ bgcolor: '#fff3e0' }}>Unit Price</TableCell>
                          <TableCell align="center" sx={{ bgcolor: '#f5f5f5' }}>Qty</TableCell>
                          <TableCell align="center" sx={{ bgcolor: '#f5f5f5' }}>Price</TableCell>
                          <TableCell align="center" sx={{ bgcolor: '#f5f5f5' }}>Status</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {matching.line_matches.map((lm: any, i: number) => (
                          <TableRow key={i} sx={{ bgcolor: lm.status === 'MATCH' ? 'inherit' : '#fff5f5' }}>
                            <TableCell><Typography variant="caption" fontWeight={600}>{lm.item || `Line ${lm.line_number}`}</Typography></TableCell>
                            <TableCell align="right">{lm.po ? lm.po.qty : '—'}</TableCell>
                            <TableCell align="right">{lm.po ? `₹${lm.po.price}` : '—'}</TableCell>
                            <TableCell align="right">{lm.grn ? lm.grn.qty : '—'}</TableCell>
                            <TableCell align="right">{lm.invoice ? lm.invoice.qty : '—'}</TableCell>
                            <TableCell align="right">{lm.invoice ? `₹${lm.invoice.price}` : '—'}</TableCell>
                            <TableCell align="center">
                              <Chip size="small" label={lm.qty_ok ? '✓' : '✗'} color={lm.qty_ok ? 'success' : 'error'} />
                            </TableCell>
                            <TableCell align="center">
                              <Chip size="small" label={lm.price_ok ? '✓' : '✗'} color={lm.price_ok ? 'success' : 'error'} />
                            </TableCell>
                            <TableCell align="center">
                              <Chip size="small" label={lm.status}
                                color={lm.status === 'MATCH' ? 'success' : lm.status === 'NO_PO_LINE' ? 'warning' : 'error'} />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    </Box>
                  </CardContent>
                </Card>
              </Grid>
            )}

            {/* PO draw-down (for blanket / multi-invoice POs) */}
            {matching.variance_report && (matching.variance_report as any).drawdown && (
              <Grid item xs={12}>
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" fontWeight={700} gutterBottom>PO Balance Draw-down</Typography>
                    <Table size="small">
                      <TableHead>
                        <TableRow sx={{ bgcolor: '#f5f5f5' }}>
                          <TableCell>PO Line</TableCell>
                          <TableCell align="right">PO Qty</TableCell>
                          <TableCell align="right">Remaining Before</TableCell>
                          <TableCell align="right">This Invoice</TableCell>
                          <TableCell align="right">Remaining After</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {((matching.variance_report as any).drawdown.lines || []).map((d: any, i: number) => (
                          <TableRow key={i}>
                            <TableCell>{d.po_line || d.invoice_desc}</TableCell>
                            <TableCell align="right">{d.po_qty ?? '—'}</TableCell>
                            <TableCell align="right">{d.remaining_before ?? '—'}</TableCell>
                            <TableCell align="right">{d.consumed ?? '—'}</TableCell>
                            <TableCell align="right">{d.remaining_after ?? '—'}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </CardContent>
                </Card>
              </Grid>
            )}
          </Grid>
        ) : <Alert severity="info">No matching result available. Document may not require PO matching.</Alert>}
      </TabPanel>

      {/* OCR / Source Text */}
      <TabPanel value={tab} index={5}>
        <Card>
          <CardContent>
            <Box sx={{ display: 'flex', gap: 3, mb: 2, flexWrap: 'wrap' }}>
              <Box>
                <Typography variant="caption" color="text.secondary">OCR Method</Typography>
                <Typography variant="body2" fontWeight={700}>
                  {doc.doc_type === 'DIGITAL' ? 'PDF Text Layer (no OCR needed)' :
                   doc.doc_type === 'HANDWRITTEN' ? 'GPT-4o Vision (handwriting transcription)' :
                   doc.doc_type === 'SCANNED' ? 'Tesseract / GPT-4o Vision OCR' : '—'}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">OCR Confidence</Typography>
                <Typography variant="body2" fontWeight={700} color={
                  doc.ocr_confidence == null ? 'text.secondary' :
                  Number(doc.ocr_confidence) >= 0.85 ? 'success.main' :
                  Number(doc.ocr_confidence) >= 0.70 ? 'warning.main' : 'error.main'
                }>
                  {doc.ocr_confidence != null ? `${(Number(doc.ocr_confidence) * 100).toFixed(1)}%` : 'N/A (digital text)'}
                </Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">Characters Extracted</Typography>
                <Typography variant="body2" fontWeight={700}>{doc.ocr_text?.length?.toLocaleString() || 0}</Typography>
              </Box>
            </Box>
            <Typography variant="subtitle2" fontWeight={700} gutterBottom>Raw OCR / Source Text</Typography>
            {doc.ocr_text ? (
              <Box component="pre" sx={{ fontSize: 12, whiteSpace: 'pre-wrap', overflow: 'auto', maxHeight: 500, bgcolor: '#1e1e1e', color: '#d4d4d4', p: 2, borderRadius: 2 }}>
                {doc.ocr_text}
              </Box>
            ) : (
              <Alert severity="info">No source text captured yet (document still processing or extraction not reached).</Alert>
            )}
          </CardContent>
        </Card>
      </TabPanel>

      {/* AI Explanation Dialog */}
      <Dialog open={aiDialogOpen} onClose={() => setAiDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pb: 1 }}>
          <AutoAwesome sx={{ color: '#7b1fa2' }} />
          AI Explanation — {doc.document_id}
          <IconButton onClick={() => setAiDialogOpen(false)} sx={{ ml: 'auto' }}>
            <Close />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers sx={{ p: 2 }}>
          {!explanation ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}><CircularProgress /></Box>
          ) : (
            <Grid container spacing={2}>
              <Grid item xs={12}>
                <Card sx={{
                  border: '2px solid',
                  borderColor: explanation.decision_color === 'success' ? '#4caf50' : explanation.decision_color === 'error' ? '#f44336' : explanation.decision_color === 'warning' ? '#ff9800' : '#2196f3',
                  bgcolor: explanation.decision_color === 'success' ? '#f1f8e9' : explanation.decision_color === 'error' ? '#fff5f5' : explanation.decision_color === 'warning' ? '#fff8e1' : '#e3f2fd',
                }}>
                  <CardContent>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
                      <AutoAwesome sx={{ color: 'primary.main', fontSize: 28 }} />
                      <Box sx={{ flex: 1 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                          <Typography variant="subtitle2" color="text.secondary" fontWeight={600}>AI ROUTING DECISION</Typography>
                          <Chip label={explanation.decision.replace(/_/g, ' ')} color={explanation.decision_color as any} size="small" sx={{ fontWeight: 700, fontSize: 13 }} />
                          <Chip label={explanation.pipeline === 'langgraph' ? 'LangGraph' : 'Celery'} size="small" variant="outlined" sx={{ fontSize: 10 }} />
                        </Box>
                        <Typography variant="body2" sx={{ fontStyle: 'italic' }}>{explanation.primary_reason}</Typography>
                      </Box>
                    </Box>
                  </CardContent>
                </Card>
              </Grid>

              {[
                { label: 'Rules Evaluated', value: explanation.rules_evaluated, color: 'text.primary' },
                { label: 'Rules Passed',    value: explanation.rules_passed,    color: 'success.main' },
                { label: 'Rules Failed',    value: explanation.rules_failed,    color: explanation.rules_failed > 0 ? 'error.main' : 'text.disabled' },
              ].map(({ label, value, color }) => (
                <Grid item xs={4} key={label}>
                  <Card>
                    <CardContent sx={{ textAlign: 'center', py: '12px !important' }}>
                      <Typography variant="h4" fontWeight={700} color={color}>{value}</Typography>
                      <Typography variant="caption" color="text.secondary">{label}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
              ))}

              <Grid item xs={12} md={6}>
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" fontWeight={700} gutterBottom>Confidence Breakdown</Typography>
                    {explanation.confidence_breakdown && (() => {
                      const cb = explanation.confidence_breakdown
                      const rows = [
                        { label: 'Overall Confidence',   value: cb.overall },
                        { label: 'OCR Confidence',        value: cb.ocr_confidence },
                        { label: 'Validation Pass Rate',  value: cb.validation_pass_rate },
                        { label: 'Profile Confidence',    value: cb.profile_confidence },
                        { label: 'Match Score',           value: cb.match_score },
                      ].filter((r) => r.value != null)
                      return (
                        <>
                          {cb.confidence_band && (
                            <Chip label={`${cb.confidence_band} CONFIDENCE`} size="small" color={cb.confidence_band === 'HIGH' ? 'success' : cb.confidence_band === 'MEDIUM' ? 'warning' : 'error'} sx={{ mb: 1.5 }} />
                          )}
                          {rows.map(({ label, value }) => (
                            <Box key={label} sx={{ mb: 1.5 }}>
                              <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                                <Typography variant="caption" color="text.secondary">{label}</Typography>
                                <Typography variant="caption" fontWeight={700}>{((value as number) * 100).toFixed(0)}%</Typography>
                              </Box>
                              <LinearProgress variant="determinate" value={(value as number) * 100} sx={{ height: 8, borderRadius: 4, bgcolor: '#eee', '& .MuiLinearProgress-bar': { bgcolor: (value as number) >= 0.85 ? '#4caf50' : (value as number) >= 0.60 ? '#ff9800' : '#f44336' } }} />
                            </Box>
                          ))}
                        </>
                      )
                    })()}
                  </CardContent>
                </Card>
              </Grid>

              <Grid item xs={12} md={6}>
                <Card>
                  <CardContent>
                    <Typography variant="subtitle2" fontWeight={700} gutterBottom>Contributing Factors</Typography>
                    {(explanation.contributing_factors || []).map((f: any, i: number) => (
                      <Box key={i} sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, py: 1, borderBottom: '1px solid #f0f0f0' }}>
                        {f.direction === 'POSITIVE' ? <TrendingUp sx={{ color: 'success.main', mt: 0.3, flexShrink: 0 }} fontSize="small" />
                         : f.direction === 'NEGATIVE' ? <TrendingDown sx={{ color: 'error.main', mt: 0.3, flexShrink: 0 }} fontSize="small" />
                         : <TrendingFlat sx={{ color: 'text.secondary', mt: 0.3, flexShrink: 0 }} fontSize="small" />}
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                          <Typography variant="body2" fontWeight={600}>{f.factor_name}</Typography>
                          <Typography variant="caption" color="text.secondary">{f.value}</Typography>
                        </Box>
                        <Typography variant="caption" color="text.disabled" sx={{ flexShrink: 0 }}>×{(f.weight * 100).toFixed(0)}%</Typography>
                      </Box>
                    ))}
                    {(explanation.contributing_factors || []).length === 0 && <Typography variant="body2" color="text.secondary">No contributing factors available</Typography>}
                  </CardContent>
                </Card>
              </Grid>

              {explanation.rules_triggered?.length > 0 && (
                <Grid item xs={12}>
                  <Card>
                    <CardContent>
                      <Typography variant="subtitle2" fontWeight={700} gutterBottom>Rules Triggered (Failures)</Typography>
                      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                        {explanation.rules_triggered.map((r: string) => <Chip key={r} label={r.replace(/_/g, ' ')} size="small" color="error" variant="outlined" />)}
                      </Stack>
                    </CardContent>
                  </Card>
                </Grid>
              )}

              {explanation.alternative_decisions?.length > 0 && (
                <Grid item xs={12}>
                  <Card>
                    <CardContent>
                      <Typography variant="subtitle2" fontWeight={700} gutterBottom>Alternative Outcomes</Typography>
                      {explanation.alternative_decisions.map((alt: any, i: number) => (
                        <Alert key={i} severity="info" sx={{ mb: 1 }} icon={false}>
                          <Typography variant="body2" fontWeight={600}>Would have been: <Chip label={alt.decision.replace(/_/g, ' ')} size="small" color="success" sx={{ ml: 0.5 }} /></Typography>
                          <Typography variant="caption" display="block">{alt.reason}</Typography>
                          <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>Condition: {alt.would_apply_if}</Typography>
                        </Alert>
                      ))}
                    </CardContent>
                  </Card>
                </Grid>
              )}

              <Grid item xs={12}>
                <Typography variant="caption" color="text.disabled">
                  Generated at {explanation.generated_at ? new Date(explanation.generated_at).toLocaleString() : '—'} · Pipeline: {explanation.pipeline}
                </Typography>
              </Grid>
            </Grid>
          )}
        </DialogContent>
      </Dialog>

      {/* Audit Trail */}
      <TabPanel value={tab} index={6}>
        <List dense>
          {auditLogs.map((log: any, i) => (
            <React.Fragment key={log.id}>
              <ListItem alignItems="flex-start">
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                      <Typography variant="body2" fontWeight={700}>{log.action.replace(/_/g, ' ')}</Typography>
                      {log.agent && <Chip label={log.agent} size="small" variant="outlined" />}
                      {log.stage && <Chip label={log.stage.replace(/_/g, ' ')} size="small" />}
                    </Box>
                  }
                  secondary={
                    <Box>
                      <Typography variant="caption" color="text.secondary">
                        {new Date(log.timestamp).toLocaleString()} | {log.entity_type}
                      </Typography>
                      {log.after_state && (
                        <Box component="pre" sx={{ fontSize: 10, mt: 0.5, bgcolor: '#f5f5f5', p: 1, borderRadius: 1, maxHeight: 80, overflow: 'auto' }}>
                          {JSON.stringify(log.after_state, null, 2)}
                        </Box>
                      )}
                    </Box>
                  }
                />
              </ListItem>
              {i < auditLogs.length - 1 && <Box sx={{ borderBottom: '1px solid #f0f0f0', ml: 2 }} />}
            </React.Fragment>
          ))}
          {auditLogs.length === 0 && <Alert severity="info">No audit records yet</Alert>}
        </List>
      </TabPanel>
    </Box>
  )
}