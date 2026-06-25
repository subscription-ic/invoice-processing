import React, { useState, useMemo } from 'react'
import {
  Box, Typography, Card, CardContent, Chip, CircularProgress,
  List, ListItemButton, ListItemText, ListItemIcon, Divider,
  Table, TableHead, TableBody, TableRow, TableCell, TableContainer,
  IconButton, Tooltip, TextField, Stack, Pagination, Alert,
  Paper, InputAdornment,
} from '@mui/material'
import {
  TableChart, Refresh, Search, ChevronRight, Storage,
  ContentCopy, CheckCircle, Visibility, VisibilityOff,
} from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '../../api/client'

// ── helpers ──────────────────────────────────────────────────────────────────

function fmt(val: any, col: string): { display: string; chip?: 'success' | 'error' | 'warning' | 'info' | 'default'; mono?: boolean } {
  if (val === null || val === undefined) return { display: 'NULL', chip: 'default' }
  if (typeof val === 'boolean') return { display: val ? 'true' : 'false', chip: val ? 'success' : 'error' }

  const s = String(val)

  // Status-like columns get coloured chips
  const STATUS_MAP: Record<string, 'success' | 'error' | 'warning' | 'info' | 'default'> = {
    OPEN: 'success', ACTIVE: 'success', ACCEPTED: 'success', APPROVED: 'success',
    COMPLETED: 'success', POSTED: 'success', MATCHED: 'success', PASS: 'success',
    PARTIAL: 'warning', PARTIALLY_RECEIVED: 'warning', TOLERANCE_MATCH: 'warning',
    PENDING: 'info', PROCESSING: 'info', EXTRACTING: 'info', VALIDATING: 'info',
    MATCHING: 'info', PENDING_APPROVAL: 'info', SCHEDULED: 'info', RUNNING: 'info',
    FAILED: 'error', REJECTED: 'error', EXCEPTION: 'error', MISMATCH: 'error',
    CANCELLED: 'error', CLOSED: 'default', NOT_APPLICABLE: 'default', SKIPPED: 'default',
    FAIL: 'error', WARNING: 'warning',
  }
  if (col.includes('status') || col.includes('_status') || col === 'match_status') {
    const colour = STATUS_MAP[s] || 'default'
    return { display: s.replace(/_/g, ' '), chip: colour }
  }

  // JSON / long text → truncate
  if (s.startsWith('{') || s.startsWith('[')) {
    try {
      const parsed = JSON.parse(s)
      const keys = Array.isArray(parsed) ? `[${parsed.length} items]` : `{${Object.keys(parsed).join(', ')}}`
      return { display: keys, mono: true }
    } catch {
      return { display: s.slice(0, 60) + (s.length > 60 ? '…' : ''), mono: true }
    }
  }

  // UUID — monospace short
  if (/^[0-9a-f-]{36}$/.test(s)) return { display: s.slice(0, 8) + '…', mono: true }

  // Amounts / numbers
  if (col.includes('amount') || col.includes('value') || col.includes('_rate') || col.includes('qty')) {
    const n = parseFloat(s)
    if (!isNaN(n)) return { display: n.toLocaleString('en-IN', { maximumFractionDigits: 4 }), mono: true }
  }

  return { display: s.length > 80 ? s.slice(0, 80) + '…' : s }
}

// Columns that contain PII / sensitive financial data
const PII_COLS = new Set([
  'name', 'gstin', 'pan', 'invoice_number', 'net_payable', 'tds_deduction',
  'total_amount', 'invoice_amount', 'tax_amount', 'bank_account', 'account_number',
  'phone', 'email', 'property_name', 'vendor_code', 'credit_limit', 'monthly_rent',
  'purchase_value', 'value', 'vendor_name', 'contact_name', 'contact_email',
  'contact_phone', 'unit_price', 'original_filename', 'salary',
])

function isPiiColumn(col: string): boolean {
  if (PII_COLS.has(col)) return true
  if (col.endsWith('_name') || col.endsWith('_amount') || col.endsWith('_value')) return true
  if (col.includes('phone') || col.includes('email') || col.includes('account')) return true
  if (col.includes('gstin') || col.includes('_pan')) return true
  return false
}

// Table category groupings for the sidebar
const TABLE_GROUPS: Record<string, string[]> = {
  'ERP Master': ['vendors', 'vendor_contacts', 'purchase_orders', 'po_line_items', 'grns', 'grn_line_items', 'cost_centers', 'gl_codes', 'employees', 'assets', 'contracts', 'lease_contracts', 'budgets'],
  'Documents': ['documents', 'document_line_items', 'workflow_states', 'validation_results', 'matching_results', 'erp_postings', 'payment_schedules'],
  'Workflow': ['approvals', 'approval_rules', 'exceptions', 'notifications'],
  'Audit / Config': ['audit_logs', 'configurations', 'validation_profiles', 'validation_rules'],
  'Users': ['users'],
}

function groupOf(name: string): string {
  for (const [g, tables] of Object.entries(TABLE_GROUPS)) {
    if (tables.includes(name)) return g
  }
  return 'Other'
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function MockDB() {
  const [selectedTable, setSelectedTable] = useState<string>('vendors')
  const [page, setPage] = useState(1)
  const [pageSize] = useState(50)
  const [sidebarSearch, setSidebarSearch] = useState('')
  const [copied, setCopied] = useState(false)
  const [maskPii, setMaskPii] = useState(true)

  // ── Queries ──
  const { data: tables = [], isLoading: tablesLoading, refetch: refetchTables } = useQuery({
    queryKey: ['db-tables'],
    queryFn: async () => (await adminApi.getDBTables()).data as { table_name: string; row_count: number }[],
  })

  const { data: schema = [], isLoading: schemaLoading } = useQuery({
    queryKey: ['db-schema', selectedTable],
    queryFn: async () => (await adminApi.getDBTableSchema(selectedTable)).data as { name: string; type: string; nullable: boolean }[],
    enabled: !!selectedTable,
  })

  const { data: tableData, isLoading: dataLoading, refetch: refetchData } = useQuery({
    queryKey: ['db-data', selectedTable, page, pageSize],
    queryFn: async () => (await adminApi.getDBTableData(selectedTable, page, pageSize)).data,
    enabled: !!selectedTable,
  })

  // ── Sidebar groups ──
  const filteredTables = useMemo(() =>
    tables.filter((t) => t.table_name.includes(sidebarSearch.toLowerCase())),
    [tables, sidebarSearch],
  )

  const grouped = useMemo(() => {
    const g: Record<string, typeof filteredTables> = {}
    for (const t of filteredTables) {
      const grp = groupOf(t.table_name)
      if (!g[grp]) g[grp] = []
      g[grp].push(t)
    }
    return g
  }, [filteredTables])

  const selectedMeta = tables.find((t) => t.table_name === selectedTable)

  const copySQL = () => {
    navigator.clipboard.writeText(`SELECT * FROM "${selectedTable}" LIMIT 100;`)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Box sx={{ display: 'flex', gap: 2, height: 'calc(100vh - 96px)', overflow: 'hidden' }}>

      {/* ── Sidebar ── */}
      <Paper
        elevation={2}
        sx={{
          width: 240, flexShrink: 0, display: 'flex', flexDirection: 'column',
          borderRadius: 2, overflow: 'hidden',
        }}
      >
        {/* Header */}
        <Box sx={{ px: 2, py: 1.5, bgcolor: '#0d0d0d', color: 'white', display: 'flex', alignItems: 'center', gap: 1 }}>
          <Storage fontSize="small" />
          <Typography variant="subtitle2" fontWeight={700}>PostgreSQL</Typography>
          {tablesLoading && <CircularProgress size={12} sx={{ ml: 'auto', color: 'white' }} />}
          {!tablesLoading && (
            <Tooltip title="Refresh">
              <IconButton size="small" onClick={() => refetchTables()} sx={{ ml: 'auto', color: 'white', p: 0.5 }}>
                <Refresh fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
        </Box>

        {/* Search */}
        <Box sx={{ px: 1, py: 1, borderBottom: '1px solid #e0e0e0' }}>
          <TextField
            size="small" fullWidth placeholder="Filter tables…" value={sidebarSearch}
            onChange={(e) => setSidebarSearch(e.target.value)}
            InputProps={{ startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> }}
            sx={{ '& .MuiInputBase-root': { fontSize: 13 } }}
          />
        </Box>

        {/* Table list */}
        <Box sx={{ flex: 1, overflowY: 'auto' }}>
          {Object.entries(grouped).map(([group, groupTables]) => (
            <React.Fragment key={group}>
              <Typography variant="caption" sx={{ px: 2, py: 0.5, display: 'block', bgcolor: '#ffffff', color: 'text.secondary', fontWeight: 700, letterSpacing: 0.5, textTransform: 'uppercase', fontSize: 10 }}>
                {group}
              </Typography>
              <List dense disablePadding>
                {groupTables.map((t) => (
                  <ListItemButton
                    key={t.table_name}
                    selected={selectedTable === t.table_name}
                    onClick={() => { setSelectedTable(t.table_name); setPage(1) }}
                    sx={{
                      py: 0.5, pl: 2,
                      '&.Mui-selected': { bgcolor: '#ffffff' },
                      '&.Mui-selected:hover': { bgcolor: '#ead18a' },
                    }}
                  >
                    <ListItemIcon sx={{ minWidth: 28 }}>
                      <TableChart sx={{ fontSize: 15, color: selectedTable === t.table_name ? '#c9a227' : '#90a4ae' }} />
                    </ListItemIcon>
                    <ListItemText
                      primary={t.table_name}
                      secondary={`${t.row_count.toLocaleString()} rows`}
                      primaryTypographyProps={{ fontSize: 12, fontWeight: selectedTable === t.table_name ? 700 : 400 }}
                      secondaryTypographyProps={{ fontSize: 10 }}
                    />
                  </ListItemButton>
                ))}
              </List>
            </React.Fragment>
          ))}
        </Box>

        {/* Footer */}
        <Box sx={{ px: 2, py: 1, borderTop: '1px solid #e0e0e0', bgcolor: '#ffffff' }}>
          <Typography variant="caption" color="text.secondary">
            {tables.length} tables · public schema
          </Typography>
        </Box>
      </Paper>

      {/* ── Main panel ── */}
      <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>

        {/* Toolbar */}
        <Card sx={{ mb: 1, flexShrink: 0 }}>
          <CardContent sx={{ py: '10px !important', px: 2, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <ChevronRight fontSize="small" color="disabled" />
              <Typography variant="subtitle1" fontWeight={700} sx={{ fontFamily: 'monospace' }}>
                {selectedTable}
              </Typography>
              {selectedMeta && (
                <Chip label={`${selectedMeta.row_count.toLocaleString()} rows`} size="small" variant="outlined" />
              )}
            </Box>

            <Stack direction="row" spacing={0.5} sx={{ ml: 'auto' }}>
              <Tooltip title={maskPii ? 'Show sensitive data' : 'Mask sensitive data'}>
                <IconButton
                  size="small"
                  onClick={() => setMaskPii((v) => !v)}
                  sx={{ color: maskPii ? 'warning.main' : 'success.main' }}
                >
                  {maskPii ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
                </IconButton>
              </Tooltip>
              <Tooltip title={copied ? 'Copied!' : 'Copy SELECT statement'}>
                <IconButton size="small" onClick={copySQL}>
                  {copied ? <CheckCircle fontSize="small" color="success" /> : <ContentCopy fontSize="small" />}
                </IconButton>
              </Tooltip>
              <Tooltip title="Refresh data">
                <IconButton size="small" onClick={() => refetchData()}>
                  <Refresh fontSize="small" />
                </IconButton>
              </Tooltip>
            </Stack>

            {/* Column pills */}
            {!schemaLoading && schema.length > 0 && (
              <Box sx={{ width: '100%', display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
                {schema.map((col) => (
                  <Tooltip key={col.name} title={`${col.type}${col.nullable ? '' : ' NOT NULL'}`}>
                    <Chip
                      label={col.name}
                      size="small"
                      variant="outlined"
                      sx={{
                        fontSize: 10, height: 20, fontFamily: 'monospace',
                        bgcolor: col.name === 'id' ? '#ffffff' : col.name.includes('_id') ? '#ffffff' : 'transparent',
                      }}
                    />
                  </Tooltip>
                ))}
              </Box>
            )}
          </CardContent>
        </Card>

        {/* Table */}
        <Card sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {dataLoading ? (
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1 }}>
              <CircularProgress />
            </Box>
          ) : !tableData ? (
            <Alert severity="info" sx={{ m: 2 }}>Select a table to browse its data.</Alert>
          ) : tableData.rows.length === 0 ? (
            <Alert severity="info" sx={{ m: 2 }}>Table is empty.</Alert>
          ) : (
            <>
              <TableContainer sx={{ flex: 1, overflow: 'auto' }}>
                <Table stickyHeader size="small" sx={{ minWidth: 600 }}>
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ bgcolor: '#0d0d0d', color: 'white', fontSize: 11, fontWeight: 700, width: 40, textAlign: 'center', py: 1 }}>
                        #
                      </TableCell>
                      {tableData.columns.map((col: string) => (
                        <TableCell
                          key={col}
                          sx={{
                            bgcolor: '#0d0d0d', color: 'white', fontSize: 11,
                            fontWeight: 700, py: 1, fontFamily: 'monospace',
                            whiteSpace: 'nowrap',
                            minWidth: col === 'id' ? 100 : col.includes('_id') ? 100 : col.includes('data') || col.includes('text') || col.includes('entries') ? 160 : 90,
                          }}
                        >
                          {col}
                        </TableCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {tableData.rows.map((row: Record<string, any>, ri: number) => (
                      <TableRow
                        key={ri}
                        sx={{
                          '&:nth-of-type(even)': { bgcolor: '#ffffff' },
                          '&:hover': { bgcolor: '#ffffff' },
                        }}
                      >
                        <TableCell sx={{ color: '#90a4ae', fontSize: 11, textAlign: 'center' }}>
                          {(page - 1) * pageSize + ri + 1}
                        </TableCell>
                        {tableData.columns.map((col: string) => {
                          const rawVal = row[col]
                          const masked = maskPii && isPiiColumn(col) && rawVal !== null && rawVal !== undefined && rawVal !== ''
                          const { display, chip, mono } = masked
                            ? { display: '*****', chip: undefined, mono: true }
                            : fmt(rawVal, col)
                          return (
                            <TableCell
                              key={col}
                              sx={{
                                fontSize: 12,
                                py: 0.75,
                                fontFamily: mono ? 'monospace' : 'inherit',
                                maxWidth: 280,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                color: masked ? '#e0e0e0' : undefined,
                              }}
                            >
                              {chip !== undefined ? (
                                <Chip
                                  label={display}
                                  size="small"
                                  color={chip}
                                  variant={chip === 'default' ? 'outlined' : 'filled'}
                                  sx={{ fontSize: 10, height: 20 }}
                                />
                              ) : (
                                <Tooltip title={masked ? '(masked)' : String(rawVal ?? '')} placement="top" enterDelay={600}>
                                  <span style={{ color: rawVal === null ? '#e0e0e0' : undefined }}>
                                    {display}
                                  </span>
                                </Tooltip>
                              )}
                            </TableCell>
                          )
                        })}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>

              {/* Pagination footer */}
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', px: 2, py: 1, borderTop: '1px solid #e0e0e0', flexShrink: 0, bgcolor: '#ffffff' }}>
                <Typography variant="caption" color="text.secondary">
                  {tableData.total.toLocaleString()} total rows · showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, tableData.total)} · {pageSize} per page
                </Typography>
                <Pagination
                  count={tableData.total_pages}
                  page={page}
                  onChange={(_, v) => setPage(v)}
                  size="small"
                  color="primary"
                />
              </Box>
            </>
          )}
        </Card>
      </Box>
    </Box>
  )
}
