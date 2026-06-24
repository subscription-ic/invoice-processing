import React, { useState } from 'react'
import {
  Box, Tabs, Tab, Typography, Card, CardContent, Button, Chip,
  Dialog, DialogTitle, DialogContent, DialogActions, TextField,
  MenuItem, Alert, Grid, Accordion, AccordionSummary, AccordionDetails,
  Table, TableHead, TableBody, TableRow, TableCell, Stack, Divider,
  Tooltip,
} from '@mui/material'
import { DataGrid, GridColDef } from '@mui/x-data-grid'
import {
  Add, ExpandMore, CheckCircle, Cancel, Inventory2,
  ReceiptLong, LocalShipping, StoreMallDirectory, Visibility, VisibilityOff,
} from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi, vendorsApi, poApi } from '../../api/client'
import { maskMiddle, maskAmount } from '../../utils/format'

function TabPanel({ children, value, index }: { children: React.ReactNode; value: number; index: number }) {
  return value === index ? <Box sx={{ pt: 2 }}>{children}</Box> : null
}

// ── Stat card ──────────────────────────────────────────────────────────────
function StatCard({ icon, label, value, color }: { icon: React.ReactNode; label: string; value: number | string; color: string }) {
  return (
    <Card sx={{ flex: 1, minWidth: 140 }}>
      <CardContent sx={{ display: 'flex', alignItems: 'center', gap: 2, py: '12px !important' }}>
        <Box sx={{ color, fontSize: 32, lineHeight: 1, display: 'flex' }}>{icon}</Box>
        <Box>
          <Typography variant="h5" fontWeight={700} color={color}>{value}</Typography>
          <Typography variant="caption" color="text.secondary">{label}</Typography>
        </Box>
      </CardContent>
    </Card>
  )
}

export default function Admin() {
  const [tab, setTab] = useState(0)
  const queryClient = useQueryClient()
  const [vendorDialog, setVendorDialog] = useState(false)
  const [poDialog, setPoDialog] = useState(false)
  const [error, setError] = useState('')
  const [expandedPO, setExpandedPO] = useState<string | false>(false)
  const [expandedGRN, setExpandedGRN] = useState<string | false>(false)
  const [maskPii, setMaskPii] = useState(true)

  // ── Admin gate ──
  const [unlocked, setUnlocked] = useState(sessionStorage.getItem('admin_unlocked') === 'yes')
  const [adminUser, setAdminUser] = useState('')
  const [adminPass, setAdminPass] = useState('')
  const [gateError, setGateError] = useState('')

  const tryUnlock = () => {
    if (adminUser === 'admin' && adminPass === 'admin') {
      sessionStorage.setItem('admin_unlocked', 'yes')
      setUnlocked(true); setGateError('')
    } else {
      setGateError('Invalid admin credentials')
    }
  }

  // ── Vendor form ──
  const [vendor, setVendor] = useState({
    vendor_code: '', name: '', gstin: '', pan: '', state: 'Maharashtra',
    payment_terms: 'NET30', vendor_type: 'GOODS', is_approved: true,
  })

  // ── PO form ──
  const [po, setPo] = useState({
    po_number: '', vendor_id: '', po_date: new Date().toISOString().slice(0, 10),
    total_amount: '', payment_terms: 'NET30',
    line_desc: '', line_qty: '', line_price: '', line_uom: 'EA',
  })

  // Tab indices: 0 Vendors | 1 POs | 2 GRNs | 3 Contracts | 4 Lease | 5 Assets | 6 ERP Postings | 7 Payments

  const { data: vendors = [], isLoading: vLoad } = useQuery({
    queryKey: ['admin-vendors'], queryFn: async () => (await vendorsApi.list({ page_size: 100 })).data, enabled: tab === 0,
  })
  const { data: pos = [], isLoading: pLoad } = useQuery({
    queryKey: ['admin-pos'], queryFn: async () => (await poApi.list({ page_size: 100 })).data, enabled: tab === 1,
  })
  const { data: grns = [], isLoading: gLoad } = useQuery({
    queryKey: ['admin-grns'], queryFn: async () => (await adminApi.getGRNs()).data, enabled: tab === 2,
  })
  const { data: contracts = [], isLoading: cLoad } = useQuery({
    queryKey: ['admin-contracts'], queryFn: async () => (await adminApi.getContracts()).data, enabled: tab === 3,
  })
  const { data: leases = [], isLoading: lLoad } = useQuery({
    queryKey: ['admin-leases'], queryFn: async () => (await adminApi.getLeaseContracts()).data, enabled: tab === 4,
  })
  const { data: assets = [], isLoading: aLoad } = useQuery({
    queryKey: ['admin-assets'], queryFn: async () => (await adminApi.getAssets()).data, enabled: tab === 5,
  })
  const { data: erpPostings = [], isLoading: erpLoad } = useQuery({
    queryKey: ['admin-erp'], queryFn: async () => (await adminApi.getErpPostings()).data, enabled: tab === 6,
  })
  const { data: payments = [], isLoading: payLoad } = useQuery({
    queryKey: ['admin-payments'], queryFn: async () => (await adminApi.getPaymentSchedules()).data, enabled: tab === 7,
  })
  const { data: allVendors = [] } = useQuery({
    queryKey: ['all-vendors-dropdown'], queryFn: async () => (await vendorsApi.list({ page_size: 100 })).data,
  })

  // Fetch PO line items when a PO accordion is expanded
  const { data: poLineItems = [] } = useQuery({
    queryKey: ['po-lines', expandedPO],
    queryFn: async () => expandedPO ? (await adminApi.getPOLineItems(expandedPO)).data : [],
    enabled: !!expandedPO,
  })

  // ── Mutations ──
  const createVendor = useMutation({
    mutationFn: (data: object) => vendorsApi.create(data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['admin-vendors'] }); setVendorDialog(false); setError('') },
    onError: (e: any) => setError(e?.response?.data?.detail || 'Failed to create vendor'),
  })
  const createPo = useMutation({
    mutationFn: (data: object) => poApi.create(data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['admin-pos'] }); setPoDialog(false); setError('') },
    onError: (e: any) => setError(e?.response?.data?.detail || 'Failed to create PO'),
  })

  const submitVendor = () => createVendor.mutate({ ...vendor, credit_limit: 1000000, currency: 'INR' })
  const submitPo = () => {
    const qty = parseFloat(po.line_qty || '0')
    const price = parseFloat(po.line_price || '0')
    createPo.mutate({
      po_number: po.po_number, vendor_id: po.vendor_id, po_date: po.po_date,
      total_amount: po.total_amount || (qty * price).toString(), payment_terms: po.payment_terms, currency: 'INR',
      line_items: po.line_desc ? [{ line_number: 1, description: po.line_desc, quantity: qty, unit_price: price, uom: po.line_uom, total_amount: qty * price }] : [],
    })
  }

  // ── Columns ──
  const m = (v: any) => (maskPii && v ? maskMiddle(String(v)) : v || '—')
  const ma = (v: any) => (maskPii && v != null ? maskAmount() : (v != null ? `₹${Number(v).toLocaleString('en-IN')}` : '—'))

  const vendorCols: GridColDef[] = [
    { field: 'vendor_code', headerName: 'Code', width: 90, renderCell: (p) => m(p.value) },
    { field: 'name', headerName: 'Vendor Name', flex: 1, minWidth: 200, renderCell: (p) => m(p.value) },
    { field: 'gstin', headerName: 'GSTIN', width: 160, renderCell: (p) => m(p.value) },
    { field: 'pan', headerName: 'PAN', width: 110, renderCell: (p) => m(p.value) },
    { field: 'city', headerName: 'City', width: 100 },
    { field: 'state', headerName: 'State', width: 120 },
    { field: 'vendor_type', headerName: 'Type', width: 90 },
    { field: 'payment_terms', headerName: 'Terms', width: 90 },
    {
      field: 'is_approved', headerName: 'Approved', width: 90, type: 'boolean',
      renderCell: (p) => p.value ? <CheckCircle color="success" fontSize="small" /> : <Cancel color="error" fontSize="small" />,
    },
  ]
  const contractCols: GridColDef[] = [
    { field: 'contract_number', headerName: 'Contract #', width: 150 },
    { field: 'vendor_name', headerName: 'Vendor', flex: 1, renderCell: (p) => m(p.value) },
    { field: 'contract_type', headerName: 'Type', width: 120 },
    { field: 'value', headerName: 'Value (₹)', width: 130, renderCell: (p) => ma(p.value) },
    { field: 'status', headerName: 'Status', width: 100 },
  ]
  const leaseCols: GridColDef[] = [
    { field: 'contract_number', headerName: 'Contract #', width: 150 },
    { field: 'property_name', headerName: 'Property', flex: 1, renderCell: (p) => m(p.value) },
    { field: 'monthly_rent', headerName: 'Rent (₹/mo)', width: 130, renderCell: (p) => ma(p.value) },
    { field: 'gst_rate', headerName: 'GST%', width: 80 },
    { field: 'tds_rate', headerName: 'TDS%', width: 80 },
    { field: 'status', headerName: 'Status', width: 100 },
  ]
  const assetCols: GridColDef[] = [
    { field: 'asset_code', headerName: 'Code', width: 120 },
    { field: 'name', headerName: 'Asset', flex: 1, renderCell: (p) => m(p.value) },
    { field: 'category', headerName: 'Category', width: 120 },
    { field: 'purchase_value', headerName: 'Value (₹)', width: 130, renderCell: (p) => ma(p.value) },
    { field: 'status', headerName: 'Status', width: 100 },
  ]
  const payCols: GridColDef[] = [
    { field: 'document_ref', headerName: 'Document', width: 180 },
    { field: 'invoice_number', headerName: 'Invoice #', width: 140, renderCell: (p) => m(p.value) },
    { field: 'net_payable', headerName: 'Net Payable (₹)', width: 140, renderCell: (p) => ma(p.value) },
    { field: 'tds_deduction', headerName: 'TDS (₹)', width: 100, renderCell: (p) => ma(p.value) },
    { field: 'payment_terms', headerName: 'Terms', width: 100 },
    { field: 'due_date', headerName: 'Due Date', width: 110 },
    { field: 'status', headerName: 'Status', width: 120 },
  ]

  // ── Admin gate ──
  if (!unlocked) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <Card sx={{ width: 380 }}>
          <CardContent>
            <Typography variant="h6" fontWeight={700} gutterBottom>Admin Access</Typography>
            <Typography variant="body2" color="text.secondary" gutterBottom>The ERP console requires admin login.</Typography>
            {gateError && <Alert severity="error" sx={{ my: 1 }}>{gateError}</Alert>}
            <TextField label="Username" fullWidth sx={{ my: 1 }} value={adminUser} onChange={(e) => setAdminUser(e.target.value)} />
            <TextField label="Password" type="password" fullWidth sx={{ mb: 2 }} value={adminPass}
              onChange={(e) => setAdminPass(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && tryUnlock()} />
            <Button variant="contained" fullWidth onClick={tryUnlock}>Sign In</Button>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>Credentials: admin / admin</Typography>
          </CardContent>
        </Card>
      </Box>
    )
  }

  return (
    <Box>
      {/* Header */}
      <Box sx={{ mb: 2, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 1 }}>
        <Box>
          <Typography variant="h5" fontWeight={700}>Mock ERP Database</Typography>
          <Typography variant="body2" color="text.secondary">
            Live view of the ERP master data — seeded from po.xlsx and grn.xlsx. All AI matching reads from this data.
          </Typography>
        </Box>
        <Chip
          icon={maskPii ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
          label={maskPii ? 'Sensitive data masked' : 'Showing real data'}
          color={maskPii ? 'warning' : 'success'}
          size="small"
          onClick={() => setMaskPii((v) => !v)}
          clickable
          variant="outlined"
          sx={{ mt: 0.5 }}
        />
      </Box>

      {/* Stats strip */}
      <Stack direction="row" spacing={2} sx={{ mb: 2, flexWrap: 'wrap', gap: 1 }}>
        <StatCard icon={<StoreMallDirectory fontSize="inherit" />} label="Vendors" value={vendors.length || (tab !== 0 ? '—' : 0)} color="#1976d2" />
        <StatCard icon={<ReceiptLong fontSize="inherit" />} label="Purchase Orders" value={pos.length || (tab !== 1 ? '—' : 0)} color="#388e3c" />
        <StatCard icon={<LocalShipping fontSize="inherit" />} label="GRNs" value={grns.length || (tab !== 2 ? '—' : 0)} color="#f57c00" />
        <StatCard icon={<Inventory2 fontSize="inherit" />} label="ERP Postings" value={erpPostings.length || (tab !== 6 ? '—' : 0)} color="#7b1fa2" />
      </Stack>

      <Alert severity="info" sx={{ mb: 2 }}>
        Upload an invoice whose <strong>PO number</strong> matches one listed below to trigger automatic 2-way or 3-way matching.
      </Alert>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto"
        sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label={`Vendors (${vendors.length})`} />
        <Tab label={`Purchase Orders (${pos.length})`} />
        <Tab label={`GRNs (${grns.length})`} />
        <Tab label={`Contracts (${contracts.length})`} />
        <Tab label={`Lease Contracts (${leases.length})`} />
        <Tab label={`Assets (${assets.length})`} />
        <Tab label={`ERP Postings (${erpPostings.length})`} />
        <Tab label={`Payment Schedules (${payments.length})`} />
      </Tabs>

      {/* ── Vendors ── */}
      <TabPanel value={tab} index={0}>
        <Box sx={{ mb: 1, display: 'flex', justifyContent: 'flex-end' }}>
          <Button variant="contained" startIcon={<Add />} onClick={() => { setError(''); setVendorDialog(true) }}>Add Vendor</Button>
        </Box>
        <Card>
          <DataGrid
            rows={vendors.map((v: any, i: number) => ({ id: v.id || i, ...v }))}
            columns={vendorCols}
            loading={vLoad}
            autoHeight
            disableRowSelectionOnClick
            pageSizeOptions={[10, 25]}
            initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
            sx={{ border: 'none', '& .MuiDataGrid-cell': { fontSize: 13 } }}
          />
        </Card>
      </TabPanel>

      {/* ── Purchase Orders (expandable line items) ── */}
      <TabPanel value={tab} index={1}>
        <Box sx={{ mb: 1, display: 'flex', justifyContent: 'flex-end' }}>
          <Button variant="contained" startIcon={<Add />} onClick={() => { setError(''); setPoDialog(true) }}>Add PO</Button>
        </Box>
        {pLoad && <Typography color="text.secondary" sx={{ py: 2 }}>Loading…</Typography>}
        {pos.map((p: any) => (
          <Accordion
            key={p.id}
            expanded={expandedPO === p.id}
            onChange={(_, open) => setExpandedPO(open ? p.id : false)}
            sx={{ mb: 1 }}
          >
            <AccordionSummary expandIcon={<ExpandMore />}>
              <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap', width: '100%' }}>
                <Chip label={maskPii ? maskMiddle(p.po_number) : p.po_number} color="primary" size="small" sx={{ fontWeight: 700, fontFamily: 'monospace' }} />
                <Typography variant="body2" fontWeight={600} sx={{ minWidth: 200 }}>{maskPii ? maskMiddle(p.vendor_name) : (p.vendor_name || '—')}</Typography>
                <Chip label={p.status} size="small"
                  color={p.status === 'OPEN' ? 'success' : p.status === 'CLOSED' ? 'default' : 'warning'} />
                <Typography variant="body2" sx={{ ml: 'auto', mr: 2 }}>
                  {maskPii ? maskAmount() : `₹${Number(p.total_amount).toLocaleString('en-IN')}`}
                </Typography>
                <Typography variant="caption" color="text.secondary">{p.po_date}</Typography>
              </Box>
            </AccordionSummary>
            <AccordionDetails sx={{ bgcolor: '#fafafa', pt: 0 }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                Line Items
              </Typography>
              {poLineItems.length === 0 ? (
                <Typography variant="caption" color="text.secondary">No line items loaded.</Typography>
              ) : (
                <Table size="small">
                  <TableHead>
                    <TableRow sx={{ bgcolor: '#e3f2fd' }}>
                      <TableCell sx={{ fontWeight: 700, fontSize: 12 }}>#</TableCell>
                      <TableCell sx={{ fontWeight: 700, fontSize: 12 }}>Description</TableCell>
                      <TableCell align="right" sx={{ fontWeight: 700, fontSize: 12 }}>Qty</TableCell>
                      <TableCell sx={{ fontWeight: 700, fontSize: 12 }}>UOM</TableCell>
                      <TableCell align="right" sx={{ fontWeight: 700, fontSize: 12 }}>Unit Price (₹)</TableCell>
                      <TableCell align="right" sx={{ fontWeight: 700, fontSize: 12 }}>Total (₹)</TableCell>
                      <TableCell align="center" sx={{ fontWeight: 700, fontSize: 12 }}>Tax</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {poLineItems.map((li: any) => {
                      const taxRate = li.igst_rate || (li.cgst_rate + li.sgst_rate)
                      return (
                        <TableRow key={li.id}>
                          <TableCell sx={{ fontSize: 12 }}>{li.line_number}</TableCell>
                          <TableCell sx={{ fontSize: 12, maxWidth: 320 }}>{li.description}</TableCell>
                          <TableCell align="right" sx={{ fontSize: 12 }}>{li.quantity}</TableCell>
                          <TableCell sx={{ fontSize: 12 }}>{li.uom}</TableCell>
                          <TableCell align="right" sx={{ fontSize: 12 }}>{maskPii ? maskAmount() : `₹${Number(li.unit_price).toLocaleString('en-IN')}`}</TableCell>
                          <TableCell align="right" sx={{ fontSize: 12 }}>{maskPii ? maskAmount() : `₹${Number(li.total_amount).toLocaleString('en-IN')}`}</TableCell>
                          <TableCell align="center" sx={{ fontSize: 12 }}>
                            {taxRate > 0 ? <Chip label={`${taxRate}%`} size="small" variant="outlined" /> : '—'}
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              )}
            </AccordionDetails>
          </Accordion>
        ))}
        {!pLoad && pos.length === 0 && <Alert severity="info">No purchase orders found. Run seed_erp_from_excel.py to import from Excel.</Alert>}
      </TabPanel>

      {/* ── GRNs ── */}
      <TabPanel value={tab} index={2}>
        <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 2 }}>
          Goods Receipt Notes — linked to Purchase Orders. Used for 3-way matching.
        </Typography>
        {gLoad && <Typography color="text.secondary" sx={{ py: 2 }}>Loading…</Typography>}
        {grns.map((g: any) => (
          <Accordion
            key={g.id}
            expanded={expandedGRN === g.id}
            onChange={(_, open) => setExpandedGRN(open ? g.id : false)}
            sx={{ mb: 1 }}
          >
            <AccordionSummary expandIcon={<ExpandMore />}>
              <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap', width: '100%' }}>
                <Chip label={g.grn_number} color="warning" size="small" sx={{ fontWeight: 700, fontFamily: 'monospace' }} />
                <Chip
                  label={g.po_number || 'No PO'}
                  size="small"
                  color={g.po_number ? 'primary' : 'default'}
                  variant="outlined"
                  sx={{ fontFamily: 'monospace' }}
                />
                <Typography variant="body2" fontWeight={600}>{maskPii ? maskMiddle(g.vendor_name) : (g.vendor_name || '—')}</Typography>
                <Chip
                  label={g.status}
                  size="small"
                  color={g.status === 'ACCEPTED' ? 'success' : g.status === 'REJECTED' ? 'error' : 'warning'}
                />
                <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto', mr: 1 }}>
                  {g.received_date}
                </Typography>
                {g.quality_check_passed != null && (
                  g.quality_check_passed
                    ? <CheckCircle fontSize="small" color="success" />
                    : <Cancel fontSize="small" color="error" />
                )}
              </Box>
            </AccordionSummary>
            <AccordionDetails sx={{ bgcolor: '#fafafa' }}>
              <Grid container spacing={2}>
                <Grid item xs={12} sm={6}>
                  {[
                    ['Warehouse / Location', g.warehouse_location || '—'],
                    ['Total Accepted Qty', g.total_accepted_qty],
                    ['Line Items', g.line_items_count],
                  ].map(([k, v]) => (
                    <Box key={String(k)} sx={{ display: 'flex', gap: 1, py: 0.5, borderBottom: '1px solid #f0f0f0' }}>
                      <Typography variant="caption" color="text.secondary" sx={{ width: 160, flexShrink: 0 }}>{k}</Typography>
                      <Typography variant="caption" fontWeight={600}>{String(v)}</Typography>
                    </Box>
                  ))}
                </Grid>
                <Grid item xs={12} sm={6}>
                  <Typography variant="caption" color="text.secondary">Description / Remarks</Typography>
                  <Typography variant="body2" sx={{ mt: 0.5, fontSize: 12 }}>{g.remarks || '—'}</Typography>
                </Grid>
              </Grid>
            </AccordionDetails>
          </Accordion>
        ))}
        {!gLoad && grns.length === 0 && <Alert severity="info">No GRNs found. Run seed_erp_from_excel.py to import from Excel.</Alert>}
      </TabPanel>

      {/* ── Contracts ── */}
      <TabPanel value={tab} index={3}>
        <Card>
          <DataGrid
            rows={contracts.map((d: any, i: number) => ({ id: d.id || i, ...d }))}
            columns={contractCols} loading={cLoad} autoHeight disableRowSelectionOnClick
            pageSizeOptions={[10, 25]} initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
            sx={{ border: 'none', '& .MuiDataGrid-cell': { fontSize: 13 } }}
          />
        </Card>
      </TabPanel>

      {/* ── Lease Contracts ── */}
      <TabPanel value={tab} index={4}>
        <Card>
          <DataGrid
            rows={leases.map((d: any, i: number) => ({ id: d.id || i, ...d }))}
            columns={leaseCols} loading={lLoad} autoHeight disableRowSelectionOnClick
            pageSizeOptions={[10, 25]} initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
            sx={{ border: 'none', '& .MuiDataGrid-cell': { fontSize: 13 } }}
          />
        </Card>
      </TabPanel>

      {/* ── Assets ── */}
      <TabPanel value={tab} index={5}>
        <Card>
          <DataGrid
            rows={assets.map((d: any, i: number) => ({ id: d.id || i, ...d }))}
            columns={assetCols} loading={aLoad} autoHeight disableRowSelectionOnClick
            pageSizeOptions={[10, 25]} initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
            sx={{ border: 'none', '& .MuiDataGrid-cell': { fontSize: 13 } }}
          />
        </Card>
      </TabPanel>

      {/* ── ERP Postings ── */}
      <TabPanel value={tab} index={6}>
        <Typography variant="subtitle2" fontWeight={700} gutterBottom>Completed ERP Postings — Journal Entries</Typography>
        {erpLoad && <Typography>Loading…</Typography>}
        {erpPostings.map((p: any) => (
          <Accordion key={p.id} sx={{ mb: 1 }}>
            <AccordionSummary expandIcon={<ExpandMore />}>
              <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', flexWrap: 'wrap' }}>
                <Chip label={p.erp_reference} color="primary" size="small" />
                <Typography variant="body2" fontWeight={600}>{p.document_ref}</Typography>
                <Typography variant="caption">Invoice: {maskPii ? '*****' : (p.invoice_number || '—')}</Typography>
                <Chip label={p.posting_status} size="small" color={p.posting_status === 'POSTED' ? 'success' : 'error'} />
                <Typography variant="caption">{maskPii ? maskAmount() : `₹${Number(p.total_amount).toLocaleString('en-IN')}`}</Typography>
                <Chip label={p.erp_system} size="small" variant="outlined" />
              </Box>
            </AccordionSummary>
            <AccordionDetails>
              <Typography variant="caption" color="text.secondary">
                Posting Date: {p.posting_date} | Fiscal Period: {p.fiscal_period}
              </Typography>
              <Box sx={{ mt: 1, bgcolor: '#f5f5f5', borderRadius: 1, p: 1 }}>
                <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ textAlign: 'left', borderBottom: '1px solid #ddd' }}>
                      <th style={{ padding: '4px 8px' }}>GL Account</th>
                      <th style={{ padding: '4px 8px' }}>Description</th>
                      <th style={{ textAlign: 'right', padding: '4px 8px' }}>Debit</th>
                      <th style={{ textAlign: 'right', padding: '4px 8px' }}>Credit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(p.journal_entries || []).map((je: any, i: number) => (
                      <tr key={i} style={{ borderBottom: '1px solid #eee' }}>
                        <td style={{ padding: '4px 8px' }}>{je.account}</td>
                        <td style={{ padding: '4px 8px' }}>{je.description}</td>
                        <td style={{ textAlign: 'right', padding: '4px 8px' }}>{maskPii ? (je.debit ? maskAmount() : '') : (je.debit ? `₹${Number(je.debit).toLocaleString('en-IN')}` : '')}</td>
                        <td style={{ textAlign: 'right', padding: '4px 8px' }}>{maskPii ? (je.credit ? maskAmount() : '') : (je.credit ? `₹${Number(je.credit).toLocaleString('en-IN')}` : '')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Box>
            </AccordionDetails>
          </Accordion>
        ))}
        {!erpLoad && erpPostings.length === 0 && <Alert severity="info">No ERP postings yet. Process a document to completion to see its journal entries here.</Alert>}
      </TabPanel>

      {/* ── Payment Schedules ── */}
      <TabPanel value={tab} index={7}>
        <Card>
          <DataGrid
            rows={payments.map((d: any, i: number) => ({ id: d.id || i, ...d }))}
            columns={payCols} loading={payLoad} autoHeight disableRowSelectionOnClick
            pageSizeOptions={[10, 25]} initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
            sx={{ border: 'none', '& .MuiDataGrid-cell': { fontSize: 13 } }}
          />
        </Card>
      </TabPanel>

      {/* ── Add Vendor Dialog ── */}
      <Dialog open={vendorDialog} onClose={() => setVendorDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add Vendor</DialogTitle>
        <DialogContent>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          <Grid container spacing={2} sx={{ mt: 0 }}>
            <Grid item xs={6}><TextField label="Vendor Code" fullWidth value={vendor.vendor_code} onChange={(e) => setVendor({ ...vendor, vendor_code: e.target.value })} /></Grid>
            <Grid item xs={6}><TextField label="Name" fullWidth value={vendor.name} onChange={(e) => setVendor({ ...vendor, name: e.target.value })} /></Grid>
            <Grid item xs={6}><TextField label="GSTIN" fullWidth value={vendor.gstin} onChange={(e) => setVendor({ ...vendor, gstin: e.target.value })} /></Grid>
            <Grid item xs={6}><TextField label="PAN" fullWidth value={vendor.pan} onChange={(e) => setVendor({ ...vendor, pan: e.target.value })} /></Grid>
            <Grid item xs={6}><TextField label="State" fullWidth value={vendor.state} onChange={(e) => setVendor({ ...vendor, state: e.target.value })} /></Grid>
            <Grid item xs={6}>
              <TextField select label="Payment Terms" fullWidth value={vendor.payment_terms} onChange={(e) => setVendor({ ...vendor, payment_terms: e.target.value })}>
                {['NET15', 'NET30', 'NET45', 'NET60'].map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
              </TextField>
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setVendorDialog(false)}>Cancel</Button>
          <Button variant="contained" onClick={submitVendor} disabled={createVendor.isPending}>Create</Button>
        </DialogActions>
      </Dialog>

      {/* ── Add PO Dialog ── */}
      <Dialog open={poDialog} onClose={() => setPoDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add Purchase Order</DialogTitle>
        <DialogContent>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          <Grid container spacing={2} sx={{ mt: 0 }}>
            <Grid item xs={6}><TextField label="PO Number" fullWidth value={po.po_number} onChange={(e) => setPo({ ...po, po_number: e.target.value })} helperText="Must match invoice's PO #" /></Grid>
            <Grid item xs={6}>
              <TextField select label="Vendor" fullWidth value={po.vendor_id} onChange={(e) => setPo({ ...po, vendor_id: e.target.value })}>
                {allVendors.map((v: any) => <MenuItem key={v.id} value={v.id}>{v.vendor_code} — {v.name}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={6}><TextField label="PO Date" type="date" fullWidth InputLabelProps={{ shrink: true }} value={po.po_date} onChange={(e) => setPo({ ...po, po_date: e.target.value })} /></Grid>
            <Grid item xs={6}><TextField label="Total Amount" type="number" fullWidth value={po.total_amount} onChange={(e) => setPo({ ...po, total_amount: e.target.value })} /></Grid>
            <Grid item xs={12}><Typography variant="caption" fontWeight={700}>Line Item</Typography></Grid>
            <Grid item xs={12}><TextField label="Description" fullWidth value={po.line_desc} onChange={(e) => setPo({ ...po, line_desc: e.target.value })} /></Grid>
            <Grid item xs={4}><TextField label="Qty" type="number" fullWidth value={po.line_qty} onChange={(e) => setPo({ ...po, line_qty: e.target.value })} /></Grid>
            <Grid item xs={4}><TextField label="Unit Price" type="number" fullWidth value={po.line_price} onChange={(e) => setPo({ ...po, line_price: e.target.value })} /></Grid>
            <Grid item xs={4}><TextField label="UOM" fullWidth value={po.line_uom} onChange={(e) => setPo({ ...po, line_uom: e.target.value })} /></Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPoDialog(false)}>Cancel</Button>
          <Button variant="contained" onClick={submitPo} disabled={createPo.isPending}>Create</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
