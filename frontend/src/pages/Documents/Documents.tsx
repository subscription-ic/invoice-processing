import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box, Card, CardContent, Typography, Chip, Button, TextField,
  Select, MenuItem, FormControl, InputLabel, IconButton, Tooltip,
} from '@mui/material'
import { DataGrid, GridColDef, GridRenderCellParams } from '@mui/x-data-grid'
import { Visibility, Refresh, Delete } from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { documentsApi } from '../../api/client'
import type { Document } from '../../types'
import { formatDate, formatDateTime } from '../../utils/format'

const STATUS_COLORS: Record<string, 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning'> = {
  COMPLETED: 'success',
  PENDING_APPROVAL: 'warning',
  PROCESSING: 'info',
  EXCEPTION: 'error',
  HUMAN_REVIEW_REQUIRED: 'error',
  APPROVED: 'success',
  POSTED: 'success',
  FAILED: 'error',
  PENDING: 'default',
  MATCHING: 'info',
  VALIDATING: 'info',
}

const PROFILE_LABELS: Record<string, string> = {
  PO_RAW_MATERIAL: 'PO Raw Material',
  NON_PO_RAW_MATERIAL: 'Non-PO Raw Material',
  PO_CAPEX: 'PO CAPEX',
  NON_PO_CAPEX: 'Non-PO CAPEX',
  PO_OPEX: 'PO OPEX',
  NON_PO_OPEX: 'Non-PO OPEX',
  LEASE_RENT: 'Lease / Rent',
  EMPLOYEE_REIMBURSEMENT: 'Reimbursement',
  PETTY_CASH: 'Petty Cash',
}

export default function Documents() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('')
  const [profileFilter, setProfileFilter] = useState('')
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(25)

  const deleteMutation = useMutation({
    mutationFn: (id: string) => documentsApi.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents'] }),
    onError: (err: any) => {
      window.alert('Delete failed: ' + (err?.response?.data?.detail || err?.message || 'Unknown error'))
    },
  })

  const handleDelete = (e: React.MouseEvent, id: string, name: string) => {
    e.stopPropagation()
    if (window.confirm(`Delete document "${name}"? This removes it from storage and the database permanently.`)) {
      deleteMutation.mutate(id)
    }
  }

  const { data: documents = [], isLoading, refetch } = useQuery<Document[]>({
    queryKey: ['documents', statusFilter, profileFilter, page, pageSize],
    queryFn: async () => {
      const { data } = await documentsApi.list({
        status: statusFilter || undefined,
        business_profile: profileFilter || undefined,
        page: page + 1,
        page_size: pageSize,
      })
      return data
    },
    refetchInterval: 5000,
  })

  const columns: GridColDef[] = [
    { field: 'document_id', headerName: 'Document ID', width: 180 },
    { field: 'original_filename', headerName: 'File Name', flex: 1, minWidth: 200 },
    {
      field: 'status', headerName: 'Status', width: 160,
      renderCell: (params: GridRenderCellParams) => (
        <Chip label={params.value} size="small" color={STATUS_COLORS[params.value] || 'default'} />
      ),
    },
    {
      field: 'business_profile', headerName: 'Profile', width: 180,
      renderCell: (params: GridRenderCellParams) =>
        params.value ? <Chip label={PROFILE_LABELS[params.value] || params.value} size="small" variant="outlined" /> : '—',
    },
    {
      field: 'vendor_name', headerName: 'Vendor', width: 160,
      renderCell: (params: GridRenderCellParams) => params.value || '—',
    },
    {
      field: 'invoice_number', headerName: 'Invoice #', width: 140,
      renderCell: (params: GridRenderCellParams) => params.value || '—',
    },
    {
      field: 'total_amount', headerName: 'Amount', width: 130,
      renderCell: (params: GridRenderCellParams) => {
        if (!params.value) return '—'
        return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(params.value)
      },
    },
    {
      field: 'ai_profile_confidence', headerName: 'AI Confidence', width: 130,
      renderCell: (params: GridRenderCellParams) =>
        params.value ? `${(params.value * 100).toFixed(0)}%` : '—',
    },
    {
      field: 'invoice_date', headerName: 'Invoice Date', width: 120,
      renderCell: (params: GridRenderCellParams) => formatDate(params.value),
    },
    {
      field: 'created_at', headerName: 'Uploaded', width: 150,
      renderCell: (params: GridRenderCellParams) => formatDateTime(params.value),
    },
    {
      field: 'actions', headerName: 'Actions', width: 110, sortable: false, filterable: false,
      renderCell: (params: GridRenderCellParams) => (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <Tooltip title="View Details">
            <IconButton size="small" onClick={() => navigate(`/documents/${params.row.id}`)}>
              <Visibility fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete Document">
            <IconButton
              size="small"
              color="error"
              onClick={(e) => handleDelete(e, params.row.id, params.row.original_filename)}
            >
              <Delete fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      ),
    },
  ]

  return (
    <Box>
      <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          <Typography variant="h5" fontWeight={700}>Documents</Typography>
          <Typography variant="body2" color="text.secondary">All uploaded documents and their processing status</Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
          <Button startIcon={<Refresh />} onClick={() => refetch()} variant="outlined" size="small">
            Refresh
          </Button>
          <Button variant="contained" onClick={() => navigate('/upload')}>Upload New</Button>
        </Box>
      </Box>

      {/* Filters */}
      <Card sx={{ mb: 2 }}>
        <CardContent sx={{ py: 1.5, display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel>Status</InputLabel>
            <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} label="Status">
              <MenuItem value="">All</MenuItem>
              {['PENDING', 'PROCESSING', 'PENDING_APPROVAL', 'APPROVED', 'COMPLETED', 'EXCEPTION', 'HUMAN_REVIEW_REQUIRED', 'FAILED'].map((s) => (
                <MenuItem key={s} value={s}>{s.replace(/_/g, ' ')}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl size="small" sx={{ minWidth: 200 }}>
            <InputLabel>Business Profile</InputLabel>
            <Select value={profileFilter} onChange={(e) => setProfileFilter(e.target.value)} label="Business Profile">
              <MenuItem value="">All Profiles</MenuItem>
              {Object.entries(PROFILE_LABELS).map(([k, v]) => (
                <MenuItem key={k} value={k}>{v}</MenuItem>
              ))}
            </Select>
          </FormControl>
          {(statusFilter || profileFilter) && (
            <Button size="small" onClick={() => { setStatusFilter(''); setProfileFilter('') }}>
              Clear Filters
            </Button>
          )}
        </CardContent>
      </Card>

      <Card>
        <DataGrid
          rows={documents.map((d) => ({ ...d, id: d.id }))}
          columns={columns}
          loading={isLoading}
          pageSizeOptions={[10, 25, 50, 100]}
          paginationModel={{ page, pageSize }}
          onPaginationModelChange={(m) => { setPage(m.page); setPageSize(m.pageSize) }}
          disableRowSelectionOnClick
          autoHeight
          sx={{ border: 'none', '& .MuiDataGrid-cell': { fontSize: 13 } }}
        />
      </Card>
    </Box>
  )
}