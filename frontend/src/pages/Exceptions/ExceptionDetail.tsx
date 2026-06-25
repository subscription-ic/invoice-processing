import React, { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Box, Card, CardContent, Typography, Chip, Button, Grid,
  Table, TableBody, TableCell, TableHead, TableRow, Alert,
  TextField, Dialog, DialogTitle, DialogContent, DialogActions,
  CircularProgress, Stack, Divider, LinearProgress,
} from '@mui/material'
import {
  ArrowBack, ContentCopy, CompareArrows, WarningAmber, ErrorOutline,
  CheckCircleOutline, PlayArrow, CheckCircle, OpenInNew, AccessTime,
  AssignmentLate, Person, Business,
} from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { exceptionsApi, documentFileUrl } from '../../api/client'

// ── helpers ───────────────────────────────────────────────────────────────────

const SEV_COLOR: Record<string, 'error' | 'warning' | 'info' | 'success' | 'default'> = {
  CRITICAL: 'error', HIGH: 'error', MEDIUM: 'warning', LOW: 'info',
}

const ICON_MAP: Record<string, React.ReactNode> = {
  duplicate:   <ContentCopy fontSize="small" />,
  mismatch:    <CompareArrows fontSize="small" />,
  arithmetic:  <ErrorOutline fontSize="small" />,
  validation:  <WarningAmber fontSize="small" />,
  po:          <AssignmentLate fontSize="small" />,
  ocr:         <WarningAmber fontSize="small" />,
  handwriting: <WarningAmber fontSize="small" />,
  image:       <WarningAmber fontSize="small" />,
  generic:     <ErrorOutline fontSize="small" />,
}

const ICON_BG: Record<string, string> = {
  duplicate: '#fdecea', mismatch: '#ffffff', arithmetic: '#fdecea',
  validation: '#ffffff', po: '#ffffff', ocr: '#ffffff',
  handwriting: '#ffffff', image: '#ffffff', generic: '#ffffff',
}

const ICON_FG: Record<string, string> = {
  duplicate: '#c62828', mismatch: '#8c6e2f', arithmetic: '#c62828',
  validation: '#c9a227', po: '#6b5518', ocr: '#a8862b',
  handwriting: '#a8862b', image: '#a8862b', generic: '#424242',
}

function fmt(n: number | null | undefined, currency = 'INR') {
  if (n == null) return '—'
  return `${currency} ${Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
}

function fmtDate(d: string | null | undefined) {
  if (!d) return '—'
  return new Date(d).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

// ── sub-components ─────────────────────────────────────────────────────────────

function StatBox({
  label, value, sub, color = 'text.primary',
}: { label: string; value: React.ReactNode; sub?: string; color?: string }) {
  return (
    <Card variant="outlined" sx={{ borderRadius: 2, flex: 1 }}>
      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
        <Typography variant="caption" color="text.secondary" fontWeight={600} textTransform="uppercase" letterSpacing={0.5}>
          {label}
        </Typography>
        <Typography variant="h6" fontWeight={700} color={color} sx={{ mt: 0.5, lineHeight: 1.2 }}>
          {value}
        </Typography>
        {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
      </CardContent>
    </Card>
  )
}

function Section({ title, children, accent }: { title: string; children: React.ReactNode; accent?: string }) {
  return (
    <Card sx={{ mb: 2.5, borderRadius: 2, overflow: 'hidden' }}>
      <Box sx={{
        px: 2.5, py: 1.5,
        borderLeft: `4px solid ${accent || '#c9a227'}`,
        bgcolor: 'grey.50',
        borderBottom: '1px solid', borderColor: 'divider',
      }}>
        <Typography variant="subtitle1" fontWeight={700}>{title}</Typography>
      </Box>
      <CardContent sx={{ p: 2.5 }}>{children}</CardContent>
    </Card>
  )
}

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Box sx={{ display: 'flex', py: 0.75, gap: 2, borderBottom: '1px solid', borderColor: 'divider', '&:last-child': { borderBottom: 0 } }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 150, flexShrink: 0 }}>{label}</Typography>
      <Typography variant="body2" fontWeight={500}>{value ?? '—'}</Typography>
    </Box>
  )
}

// ── main component ─────────────────────────────────────────────────────────────

export default function ExceptionDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [resolveOpen, setResolveOpen] = useState(false)
  const [resolution, setResolution] = useState('')

  const { data: summary, isLoading, isError } = useQuery({
    queryKey: ['exception-summary', id],
    queryFn: async () => { const { data } = await exceptionsApi.summary(id!); return data },
    enabled: !!id,
  })

  const resolveMutation = useMutation({
    mutationFn: (notes: string) =>
      exceptionsApi.resolve(id!, { resolution_notes: notes, status: 'RESOLVED' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['exceptions'] })
      queryClient.invalidateQueries({ queryKey: ['exception-summary', id] })
      setResolveOpen(false)
      setResolution('')
    },
  })

  const startMutation = useMutation({
    mutationFn: () => {
      const user = JSON.parse(localStorage.getItem('user') || '{}')
      return exceptionsApi.assign(id!, { assigned_to: user.id })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['exception-summary', id] }),
  })

  if (isLoading) {
    return <Box sx={{ display: 'flex', justifyContent: 'center', pt: 10 }}><CircularProgress /></Box>
  }
  if (isError || !summary) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">Could not load exception details.</Alert>
        <Button startIcon={<ArrowBack />} onClick={() => navigate('/exceptions')} sx={{ mt: 2 }}>
          Back to Exceptions
        </Button>
      </Box>
    )
  }

  const { exception: ex, document: doc, what_failed = [], validation_failures = [], matching_detail, duplicate_comparison } = summary
  const isResolved = ex.status === 'RESOLVED' || ex.status === 'CLOSED'
  const slaBreached = ex.sla_deadline && new Date(ex.sla_deadline) < new Date()
  const slaMinsLeft = ex.sla_deadline
    ? Math.max(0, Math.round((new Date(ex.sla_deadline).getTime() - Date.now()) / 60000))
    : null
  const slaProgress = slaMinsLeft != null && ex.sla_hours
    ? Math.min(100, 100 - (slaMinsLeft / (ex.sla_hours * 60)) * 100)
    : 0

  return (
    <Box sx={{ maxWidth: 1100, mx: 'auto' }}>

      {/* ── Breadcrumb / nav ── */}
      <Box sx={{ mb: 2.5, display: 'flex', alignItems: 'center', gap: 1 }}>
        <Button startIcon={<ArrowBack />} onClick={() => navigate('/exceptions')} size="small" sx={{ color: 'text.secondary' }}>
          Exception Centre
        </Button>
        <Typography variant="body2" color="text.disabled">/</Typography>
        <Typography variant="body2" color="text.secondary">{ex.exception_code}</Typography>
      </Box>

      {/* ── Page header ── */}
      <Card sx={{ mb: 2.5, borderRadius: 2, borderLeft: '5px solid', borderColor: slaBreached ? 'error.main' : isResolved ? 'success.main' : 'warning.main' }}>
        <CardContent sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 2 }}>
            <Box sx={{ flex: 1 }}>
              <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mb: 1 }}>
                <Chip label={ex.severity} size="small" color={SEV_COLOR[ex.severity] || 'default'} />
                <Chip
                  label={ex.status.replace(/_/g, ' ')}
                  size="small"
                  color={isResolved ? 'success' : slaBreached ? 'error' : 'warning'}
                />
                <Chip label={ex.queue.replace(/_/g, ' ')} size="small" variant="outlined" />
                <Chip label={ex.exception_code} size="small" variant="outlined" sx={{ fontFamily: 'monospace', fontSize: 11 }} />
              </Stack>
              <Typography variant="h5" fontWeight={700} sx={{ mb: 0.5 }}>{ex.title}</Typography>
              <Stack direction="row" spacing={2} flexWrap="wrap">
                <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <AccessTime fontSize="inherit" />
                  Raised {fmtDate(ex.created_at)}
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Person fontSize="inherit" />
                  {ex.agent_raised_by?.replace(/_/g, ' ') || '—'}
                </Typography>
                {doc && (
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Business fontSize="inherit" />
                    {doc.vendor_name || doc.document_id}
                  </Typography>
                )}
              </Stack>
            </Box>
            <Stack direction="row" spacing={1} flexShrink={0}>
              {ex.status === 'OPEN' && (
                <Button
                  variant="outlined"
                  color="info"
                  startIcon={<PlayArrow />}
                  size="small"
                  onClick={() => startMutation.mutate()}
                  disabled={startMutation.isPending}
                >
                  {startMutation.isPending ? 'Starting…' : 'Start'}
                </Button>
              )}
              {!isResolved && (
                <Button
                  variant="contained"
                  color="success"
                  startIcon={<CheckCircle />}
                  size="small"
                  onClick={() => setResolveOpen(true)}
                >
                  Resolve
                </Button>
              )}
            </Stack>
          </Box>
        </CardContent>
      </Card>

      {/* ── Stat boxes row ── */}
      <Stack direction="row" spacing={2} sx={{ mb: 2.5, flexWrap: 'wrap' }}>
        <StatBox
          label="Invoice Number"
          value={doc?.invoice_number || '—'}
          sub={doc?.original_filename}
        />
        <StatBox
          label="Invoice Amount"
          value={fmt(doc?.total_amount, doc?.currency)}
          sub={`Tax: ${fmt(doc?.tax_amount, doc?.currency)}`}
        />
        <StatBox
          label="SLA Remaining"
          value={
            isResolved ? 'Resolved'
              : slaBreached ? 'Breached'
              : slaMinsLeft != null ? (slaMinsLeft >= 60 ? `${Math.floor(slaMinsLeft / 60)}h ${slaMinsLeft % 60}m` : `${slaMinsLeft}m`)
              : '—'
          }
          sub={ex.sla_deadline ? `Deadline: ${fmtDate(ex.sla_deadline)}` : undefined}
          color={isResolved ? 'success.main' : slaBreached ? 'error.main' : slaMinsLeft != null && slaMinsLeft < 60 ? 'warning.main' : 'text.primary'}
        />
        <StatBox
          label="Queue"
          value={ex.queue.replace(/_/g, ' ')}
          sub={`${ex.sla_hours}h SLA`}
        />
      </Stack>

      {/* SLA progress bar */}
      {!isResolved && ex.sla_deadline && (
        <Box sx={{ mb: 2.5 }}>
          <LinearProgress
            variant="determinate"
            value={slaProgress}
            color={slaBreached ? 'error' : slaProgress > 75 ? 'warning' : 'primary'}
            sx={{ height: 6, borderRadius: 3 }}
          />
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
            {slaBreached
              ? `SLA breached by ${Math.round(-slaMinsLeft! / 60 * 10) / 10}h`
              : `${slaProgress.toFixed(0)}% of ${ex.sla_hours}h SLA used`}
          </Typography>
        </Box>
      )}

      {/* Resolved banner */}
      {isResolved && ex.resolution_notes && (
        <Alert severity="success" icon={<CheckCircleOutline />} sx={{ mb: 2.5, borderRadius: 2 }}>
          <Typography variant="subtitle2" fontWeight={700}>Resolved</Typography>
          <Typography variant="body2">{ex.resolution_notes}</Typography>
        </Alert>
      )}

      {/* ── Root cause summary ── */}
      {what_failed.length > 0 && (
        <Section title="Root Cause Summary" accent="#d32f2f">
          <Stack spacing={1.5}>
            {what_failed.map((item: any, i: number) => (
              <Box
                key={i}
                sx={{
                  display: 'flex', gap: 2, alignItems: 'flex-start',
                  p: 1.5, borderRadius: 1.5,
                  bgcolor: ICON_BG[item.icon] || '#ffffff',
                  border: '1px solid', borderColor: 'divider',
                }}
              >
                {/* Numbered badge */}
                <Box sx={{
                  minWidth: 28, height: 28, borderRadius: '50%',
                  bgcolor: ICON_FG[item.icon] || '#424242',
                  color: '#fff', display: 'flex', alignItems: 'center',
                  justifyContent: 'center', fontSize: 13, fontWeight: 700, flexShrink: 0,
                }}>
                  {i + 1}
                </Box>
                <Box sx={{ flex: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, mb: 0.25 }}>
                    <Box sx={{ color: ICON_FG[item.icon] || '#424242', display: 'flex' }}>
                      {ICON_MAP[item.icon] ?? ICON_MAP.generic}
                    </Box>
                    <Typography variant="body2" fontWeight={700} color={ICON_FG[item.icon] || 'text.primary'}>
                      {item.heading}
                    </Typography>
                  </Box>
                  <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.6 }}>
                    {item.detail}
                  </Typography>
                </Box>
              </Box>
            ))}
          </Stack>
        </Section>
      )}

      {/* ── Duplicate comparison ── */}
      {duplicate_comparison && (
        <Section title="Duplicate Invoice Comparison" accent="#c62828">
          <Box sx={{ mb: 2 }}>
            <Alert severity="error" icon={<ContentCopy />} sx={{ borderRadius: 1.5 }}>
              Invoice number <strong>{doc?.invoice_number}</strong> already exists in the system.
              The existing document must be reviewed before this one can be processed.
            </Alert>
          </Box>

          <Table size="small" sx={{ '& th': { bgcolor: 'grey.100', fontWeight: 700 } }}>
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: '26%' }}>Field</TableCell>
                <TableCell>This Invoice <Chip label="NEW" size="small" color="warning" sx={{ ml: 0.5, height: 16, fontSize: 10 }} /></TableCell>
                <TableCell>Existing Invoice <Chip label="IN SYSTEM" size="small" color="default" sx={{ ml: 0.5, height: 16, fontSize: 10 }} /></TableCell>
                <TableCell sx={{ width: 70, textAlign: 'center' }}>Match</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {duplicate_comparison.fields_compared.map((row: any, i: number) => (
                <TableRow
                  key={i}
                  sx={{ bgcolor: row.match === false ? 'rgba(198,40,40,0.05)' : 'inherit' }}
                >
                  <TableCell sx={{ fontWeight: 600, color: 'text.secondary', fontSize: 13 }}>{row.field}</TableCell>
                  <TableCell sx={{ fontSize: 13 }}>{row.new_value ?? '—'}</TableCell>
                  <TableCell sx={{ fontSize: 13 }}>{row.existing_value ?? '—'}</TableCell>
                  <TableCell sx={{ textAlign: 'center' }}>
                    {row.match === true && <CheckCircleOutline fontSize="small" sx={{ color: 'success.main' }} />}
                    {row.match === false && <ErrorOutline fontSize="small" sx={{ color: 'error.main' }} />}
                    {row.match === null && <Typography variant="body2" color="text.disabled">—</Typography>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          <Box sx={{ mt: 2, display: 'flex', gap: 1 }}>
            <Button
              size="small"
              variant="contained"
              endIcon={<OpenInNew fontSize="small" />}
              onClick={() => window.open(documentFileUrl(duplicate_comparison.existing_invoice.id), '_blank')}
            >
              View existing PDF
            </Button>
            <Button
              size="small"
              variant="outlined"
              endIcon={<OpenInNew fontSize="small" />}
              onClick={() => navigate(`/documents/${duplicate_comparison.existing_invoice.id}`)}
            >
              Open document details
            </Button>
          </Box>
        </Section>
      )}

      {/* ── PO / GRN matching detail ── */}
      {matching_detail && (
        <Section title="PO / GRN Match Detail" accent="#8c6e2f">
          {/* Score cards */}
          <Grid container spacing={1.5} sx={{ mb: 2.5 }}>
            {[
              { label: 'Overall Score', value: `${(matching_detail.overall_match_score * 100).toFixed(0)}%`, ok: matching_detail.overall_match_score >= 0.9 },
              { label: 'Quantity', value: matching_detail.quantity_match ? 'Match' : 'Mismatch', ok: matching_detail.quantity_match },
              { label: 'Unit Price', value: matching_detail.price_match ? 'Match' : 'Mismatch', ok: matching_detail.price_match },
              { label: 'Tax', value: matching_detail.tax_match ? 'Match' : 'Mismatch', ok: matching_detail.tax_match },
              { label: 'Total Amount', value: matching_detail.total_match ? 'Match' : 'Mismatch', ok: matching_detail.total_match },
              { label: 'Vendor', value: matching_detail.vendor_match ? 'Match' : 'Mismatch', ok: matching_detail.vendor_match },
            ].map((m) => (
              <Grid item xs={6} sm={4} md={2} key={m.label}>
                <Box sx={{
                  p: 1.5, borderRadius: 1.5, textAlign: 'center',
                  border: '1px solid', borderColor: m.ok ? 'success.light' : 'error.light',
                  bgcolor: m.ok ? 'rgba(46,125,50,0.06)' : 'rgba(198,40,40,0.06)',
                }}>
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.25 }}>{m.label}</Typography>
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0.5 }}>
                    {m.ok
                      ? <CheckCircleOutline fontSize="small" sx={{ color: 'success.main' }} />
                      : <ErrorOutline fontSize="small" sx={{ color: 'error.main' }} />}
                    <Typography variant="body2" fontWeight={700} color={m.ok ? 'success.main' : 'error.main'}>
                      {m.value}
                    </Typography>
                  </Box>
                </Box>
              </Grid>
            ))}
          </Grid>

          {/* Variance table */}
          {matching_detail.variance_report && Object.keys(matching_detail.variance_report).length > 0 && (
            <>
              <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1 }}>Variance Breakdown</Typography>
              <Table size="small" sx={{ '& th': { bgcolor: 'grey.100', fontWeight: 700 } }}>
                <TableHead>
                  <TableRow>
                    <TableCell>Field</TableCell>
                    <TableCell>Invoice Value</TableCell>
                    <TableCell>PO / GRN Value</TableCell>
                    <TableCell>Variance</TableCell>
                    <TableCell sx={{ textAlign: 'center', width: 80 }}>Result</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {Object.entries(matching_detail.variance_report).map(([field, info]: [string, any]) => (
                    <TableRow key={field} sx={{ bgcolor: !info.match ? 'rgba(198,40,40,0.05)' : 'inherit' }}>
                      <TableCell sx={{ fontWeight: 600, fontSize: 13 }}>{field.replace(/_/g, ' ')}</TableCell>
                      <TableCell sx={{ fontSize: 13 }}>{info.invoice_value ?? '—'}</TableCell>
                      <TableCell sx={{ fontSize: 13 }}>{info.po_value ?? info.grn_value ?? '—'}</TableCell>
                      <TableCell>
                        <Chip
                          label={info.variance_pct ?? '—'}
                          size="small"
                          color={!info.match ? 'error' : 'success'}
                          variant="outlined"
                          sx={{ fontWeight: 700, fontSize: 12 }}
                        />
                      </TableCell>
                      <TableCell sx={{ textAlign: 'center' }}>
                        {info.match
                          ? <CheckCircleOutline fontSize="small" sx={{ color: 'success.main' }} />
                          : <ErrorOutline fontSize="small" sx={{ color: 'error.main' }} />}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </>
          )}

          {matching_detail.matching_notes && (
            <Alert severity="info" icon={false} sx={{ mt: 2, borderRadius: 1.5 }}>
              <Typography variant="body2">{matching_detail.matching_notes}</Typography>
            </Alert>
          )}
        </Section>
      )}

      {/* ── Validation rule failures ── */}
      {validation_failures.length > 0 && (
        <Section title="Failed Validation Rules" accent="#c9a227">
          <Table size="small" sx={{ '& th': { bgcolor: 'grey.100', fontWeight: 700 } }}>
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: '22%' }}>Rule</TableCell>
                <TableCell>Expected</TableCell>
                <TableCell>Actual</TableCell>
                <TableCell>Why it failed</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {validation_failures.map((vf: any, i: number) => (
                <TableRow key={i}>
                  <TableCell>
                    <Typography variant="body2" fontWeight={700}>{vf.rule_name}</Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>{vf.rule_code}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', color: 'success.dark' }}>{vf.expected_value ?? '—'}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontFamily: 'monospace', color: 'error.main', fontWeight: 600 }}>{vf.actual_value ?? '—'}</Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" color="text.secondary">{vf.reason ?? '—'}</Typography>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Section>
      )}

      {/* ── Invoice snapshot ── */}
      {doc && (
        <Section title="Invoice Details" accent="#c9a227">
          <Grid container spacing={3}>
            <Grid item xs={12} sm={6}>
              <Typography variant="caption" color="text.secondary" fontWeight={700} textTransform="uppercase" letterSpacing={0.5}>
                Document
              </Typography>
              <Box sx={{ mt: 1 }}>
                <KV label="Document ID" value={<Typography variant="body2" fontFamily="monospace">{doc.document_id}</Typography>} />
                <KV label="File name" value={doc.original_filename} />
                <KV label="Status" value={
                  <Chip label={doc.status?.replace(/_/g, ' ')} size="small"
                    color={doc.status === 'APPROVED' ? 'success' : doc.status === 'FAILED' ? 'error' : doc.status === 'HUMAN_REVIEW_REQUIRED' ? 'warning' : 'default'} />
                } />
                <KV label="Uploaded" value={fmtDate(doc.created_at)} />
              </Box>
            </Grid>
            <Grid item xs={12} sm={6}>
              <Typography variant="caption" color="text.secondary" fontWeight={700} textTransform="uppercase" letterSpacing={0.5}>
                Invoice
              </Typography>
              <Box sx={{ mt: 1 }}>
                <KV label="Invoice number" value={<strong>{doc.invoice_number || '—'}</strong>} />
                <KV label="Invoice date" value={doc.invoice_date || '—'} />
                <KV label="Total amount" value={<Typography variant="body2" fontWeight={700}>{fmt(doc.total_amount, doc.currency)}</Typography>} />
                <KV label="Tax amount" value={fmt(doc.tax_amount, doc.currency)} />
              </Box>
            </Grid>
            <Grid item xs={12}>
              <Divider sx={{ my: 0.5 }} />
              <Typography variant="caption" color="text.secondary" fontWeight={700} textTransform="uppercase" letterSpacing={0.5}>
                Vendor
              </Typography>
              <Box sx={{ mt: 1 }}>
                <KV label="Vendor name" value={doc.vendor_name || '—'} />
                <KV label="GSTIN" value={doc.vendor_gstin
                  ? <Typography variant="body2" fontFamily="monospace">{doc.vendor_gstin}</Typography>
                  : '—'} />
              </Box>
            </Grid>
          </Grid>
          <Box sx={{ mt: 2.5, display: 'flex', gap: 1 }}>
            <Button
              size="small"
              variant="contained"
              endIcon={<OpenInNew fontSize="small" />}
              onClick={() => window.open(documentFileUrl(doc.id), '_blank')}
            >
              View PDF
            </Button>
            <Button
              size="small"
              variant="outlined"
              endIcon={<OpenInNew fontSize="small" />}
              onClick={() => navigate(`/documents/${doc.id}`)}
            >
              Open document details
            </Button>
          </Box>
        </Section>
      )}

      {/* ── Resolve dialog ── */}
      <Dialog open={resolveOpen} onClose={() => setResolveOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ pb: 1 }}>
          <Typography fontWeight={700}>Resolve Exception</Typography>
          <Typography variant="body2" color="text.secondary">{ex.title}</Typography>
        </DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mb: 2, borderRadius: 1.5 }}>
            Describe exactly how you resolved this exception. This will be saved to the audit trail.
          </Alert>
          <TextField
            label="Resolution Notes"
            multiline
            rows={4}
            fullWidth
            value={resolution}
            onChange={(e) => setResolution(e.target.value)}
            placeholder="e.g. Verified with vendor — this is a re-submission of the original. Original invoice INV-001 was already paid. Rejecting duplicate."
            required
          />
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setResolveOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            color="success"
            disabled={!resolution.trim() || resolveMutation.isPending}
            onClick={() => resolveMutation.mutate(resolution)}
          >
            {resolveMutation.isPending ? 'Saving…' : 'Mark Resolved'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
