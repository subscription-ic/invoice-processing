import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box, Card, Typography, Chip, Button, FormControl, InputLabel, Select,
  MenuItem, Dialog, DialogTitle, DialogContent, DialogActions, TextField,
  IconButton, Tooltip,
} from '@mui/material'
import { DataGrid, GridColDef, GridRenderCellParams } from '@mui/x-data-grid'
import { Visibility, CheckCircle, PlayArrow } from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { exceptionsApi } from '../../api/client'
import type { Exception } from '../../types'

const SEVERITY_COLORS: Record<string, any> = {
  CRITICAL: 'error', HIGH: 'error', MEDIUM: 'warning', LOW: 'info',
}

const QUEUE_COLORS: Record<string, string> = {
  AP_TEAM: '#1976d2', FINANCE: '#7b1fa2', PROCUREMENT: '#2e7d32',
  COMPLIANCE: '#d32f2f', WAREHOUSE: '#f57f17',
}

export default function Exceptions() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [queueFilter, setQueueFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [resolveDialog, setResolveDialog] = useState<{ open: boolean; exception: Exception | null }>({ open: false, exception: null })
  const [resolution, setResolution] = useState('')

  const { data: exceptions = [], isLoading } = useQuery<Exception[]>({
    queryKey: ['exceptions', queueFilter, statusFilter],
    queryFn: async () => {
      const { data } = await exceptionsApi.list({
        queue: queueFilter || undefined,
        status: statusFilter || undefined,
        page_size: 100,
      })
      return data
    },
    refetchInterval: 30_000,
  })

  const resolveMutation = useMutation({
    mutationFn: ({ id, notes }: { id: string; notes: string }) =>
      exceptionsApi.resolve(id, { resolution_notes: notes, status: 'RESOLVED' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['exceptions'] })
      setResolveDialog({ open: false, exception: null })
      setResolution('')
    },
  })

  // Claim the exception (assign to self → IN_PROGRESS) then open the detail page
  const startMutation = useMutation({
    mutationFn: (id: string) => {
      const user = JSON.parse(localStorage.getItem('user') || '{}')
      return exceptionsApi.assign(id, { assigned_to: user.id })
    },
    onSuccess: (_data, id) => navigate(`/exceptions/${id}`),
  })

  const columns: GridColDef[] = [
    { field: 'exception_code', headerName: 'Code', width: 180 },
    { field: 'title', headerName: 'Title', flex: 1, minWidth: 200 },
    {
      field: 'severity', headerName: 'Severity', width: 110,
      renderCell: (p: GridRenderCellParams) => <Chip label={p.value} size="small" color={SEVERITY_COLORS[p.value] || 'default'} />,
    },
    {
      field: 'queue', headerName: 'Queue', width: 130,
      renderCell: (p: GridRenderCellParams) => (
        <Chip label={p.value} size="small" sx={{ bgcolor: QUEUE_COLORS[p.value] + '20', color: QUEUE_COLORS[p.value], fontWeight: 600 }} />
      ),
    },
    {
      field: 'status', headerName: 'Status', width: 120,
      renderCell: (p: GridRenderCellParams) => (
        <Chip label={p.value} size="small"
          color={p.value === 'RESOLVED' ? 'success' : p.value === 'ESCALATED' ? 'error' : p.value === 'OPEN' ? 'warning' : 'info'} />
      ),
    },
    {
      field: 'sla_deadline', headerName: 'SLA Deadline', width: 160,
      renderCell: (p: GridRenderCellParams) => {
        if (!p.value) return '—'
        const deadline = new Date(p.value)
        const isBreached = deadline < new Date()
        return (
          <Typography variant="caption" color={isBreached ? 'error' : 'inherit'}>
            {deadline.toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' })}
            {isBreached && ' ⚠️'}
          </Typography>
        )
      },
    },
    { field: 'escalation_count', headerName: 'Escalations', width: 100 },
    {
      field: 'actions', headerName: 'Actions', width: 160, sortable: false,
      renderCell: (p: GridRenderCellParams) => (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <Tooltip title="View Exception Detail">
            <IconButton size="small" color="primary" onClick={() => navigate(`/exceptions/${p.row.id}`)}>
              <Visibility fontSize="small" />
            </IconButton>
          </Tooltip>
          {p.row.status === 'OPEN' && (
            <Tooltip title="Start (mark In Progress)">
              <IconButton size="small" color="info" onClick={() => startMutation.mutate(p.row.id)}>
                <PlayArrow fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
          {p.row.status !== 'RESOLVED' && p.row.status !== 'CLOSED' && (
            <Tooltip title="Resolve">
              <IconButton size="small" color="success" onClick={() => setResolveDialog({ open: true, exception: p.row as Exception })}>
                <CheckCircle fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
        </Box>
      ),
    },
  ]

  return (
    <Box>
      <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          <Typography variant="h5" fontWeight={700}>Exception Center</Typography>
          <Typography variant="body2" color="text.secondary">
            Manage and resolve document processing exceptions
          </Typography>
        </Box>
        <Chip label={`${exceptions.filter((e) => e.status === 'OPEN').length} Open`} color="error" />
      </Box>

      {/* Filters */}
      <Card sx={{ mb: 2, p: 2, display: 'flex', gap: 2, alignItems: 'center' }}>
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Queue</InputLabel>
          <Select value={queueFilter} onChange={(e) => setQueueFilter(e.target.value)} label="Queue">
            <MenuItem value="">All Queues</MenuItem>
            {['AP_TEAM', 'FINANCE', 'PROCUREMENT', 'COMPLIANCE', 'WAREHOUSE'].map((q) => (
              <MenuItem key={q} value={q}>{q.replace(/_/g, ' ')}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>Status</InputLabel>
          <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} label="Status">
            <MenuItem value="">All Statuses</MenuItem>
            {['OPEN', 'IN_PROGRESS', 'ESCALATED', 'RESOLVED', 'CLOSED'].map((s) => (
              <MenuItem key={s} value={s}>{s.replace(/_/g, ' ')}</MenuItem>
            ))}
          </Select>
        </FormControl>
        {(queueFilter || statusFilter) && (
          <Button size="small" onClick={() => { setQueueFilter(''); setStatusFilter('') }}>Clear</Button>
        )}
      </Card>

      <Card>
        <DataGrid
          rows={exceptions.map((e) => ({ ...e, id: e.id }))}
          columns={columns}
          loading={isLoading}
          autoHeight
          disableRowSelectionOnClick
          onRowClick={(params) => navigate(`/exceptions/${params.row.id}`)}
          sx={{
            border: 'none',
            '& .MuiDataGrid-row': { cursor: 'pointer' },
          }}
        />
      </Card>

      {/* Resolve Dialog */}
      <Dialog open={resolveDialog.open} onClose={() => setResolveDialog({ open: false, exception: null })} maxWidth="sm" fullWidth>
        <DialogTitle>Resolve Exception</DialogTitle>
        <DialogContent>
          <Typography variant="body2" gutterBottom color="text.secondary">
            {resolveDialog.exception?.title}
          </Typography>
          <TextField
            label="Resolution Notes"
            multiline
            rows={4}
            fullWidth
            value={resolution}
            onChange={(e) => setResolution(e.target.value)}
            sx={{ mt: 2 }}
            placeholder="Describe how this exception was resolved..."
            required
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResolveDialog({ open: false, exception: null })}>Cancel</Button>
          <Button
            variant="contained"
            color="success"
            disabled={!resolution.trim() || resolveMutation.isPending}
            onClick={() => {
              if (resolveDialog.exception) {
                resolveMutation.mutate({ id: resolveDialog.exception.id, notes: resolution })
              }
            }}
          >
            {resolveMutation.isPending ? 'Resolving...' : 'Mark Resolved'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}