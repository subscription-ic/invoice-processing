import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box, Card, CardContent, Typography, Chip, Button, Tabs, Tab,
  Dialog, DialogTitle, DialogContent, DialogActions, TextField,
  Alert, IconButton, Tooltip, Grid,
} from '@mui/material'
import { DataGrid, GridColDef, GridRenderCellParams } from '@mui/x-data-grid'
import { CheckCircle, Cancel, Visibility } from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { approvalsApi } from '../../api/client'
import type { Approval } from '../../types'

export default function Approvals() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState(0)
  const [actionDialog, setActionDialog] = useState<{ open: boolean; approval: Approval | null; action: string }>({ open: false, approval: null, action: '' })
  const [comments, setComments] = useState('')

  const { data: myApprovals = [], isLoading: myLoading } = useQuery<Approval[]>({
    queryKey: ['my-approvals'],
    queryFn: async () => { const { data } = await approvalsApi.myApprovals({ status: 'PENDING' }); return data },
    refetchInterval: 30_000,
  })

  const { data: allApprovals = [], isLoading: allLoading } = useQuery<Approval[]>({
    queryKey: ['all-approvals'],
    queryFn: async () => { const { data } = await approvalsApi.list({ page_size: 50 }); return data },
    enabled: tab === 1,
  })

  const actionMutation = useMutation({
    mutationFn: ({ id, action, comments }: { id: string; action: string; comments: string }) =>
      approvalsApi.action(id, { action, comments }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['my-approvals'] })
      queryClient.invalidateQueries({ queryKey: ['all-approvals'] })
      setActionDialog({ open: false, approval: null, action: '' })
      setComments('')
    },
  })

  const openAction = (approval: Approval, action: string) => {
    setActionDialog({ open: true, approval, action })
    setComments('')
  }

  const columns: GridColDef[] = [
    { field: 'document_id', headerName: 'Document', width: 200 },
    { field: 'approval_level', headerName: 'Level', width: 80 },
    { field: 'approver_name', headerName: 'Approver', width: 160 },
    {
      field: 'status', headerName: 'Status', width: 130,
      renderCell: (p: GridRenderCellParams) => (
        <Chip label={p.value} size="small"
          color={p.value === 'APPROVED' ? 'success' : p.value === 'REJECTED' ? 'error' : p.value === 'PENDING' ? 'warning' : 'default'} />
      ),
    },
    {
      field: 'deadline', headerName: 'Deadline', width: 160,
      renderCell: (p: GridRenderCellParams) => p.value ? new Date(p.value).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' }) : '—',
    },
    { field: 'comments', headerName: 'Comments', flex: 1 },
    {
      field: 'actions', headerName: '', width: 160, sortable: false,
      renderCell: (p: GridRenderCellParams) => (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <Tooltip title="View Document">
            <IconButton size="small" onClick={() => navigate(`/documents/${p.row.document_id}`)}>
              <Visibility fontSize="small" />
            </IconButton>
          </Tooltip>
          {p.row.status === 'PENDING' && (
            <>
              <Tooltip title="Approve">
                <IconButton size="small" color="success" onClick={() => openAction(p.row as Approval, 'APPROVE')}>
                  <CheckCircle fontSize="small" />
                </IconButton>
              </Tooltip>
              <Tooltip title="Reject">
                <IconButton size="small" color="error" onClick={() => openAction(p.row as Approval, 'REJECT')}>
                  <Cancel fontSize="small" />
                </IconButton>
              </Tooltip>
            </>
          )}
        </Box>
      ),
    },
  ]

  const displayData = tab === 0 ? myApprovals : allApprovals

  return (
    <Box>
      <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between' }}>
        <Box>
          <Typography variant="h5" fontWeight={700}>Approval Center</Typography>
          <Typography variant="body2" color="text.secondary">
            Manage document approvals across the organization
          </Typography>
        </Box>
        {myApprovals.length > 0 && (
          <Chip label={`${myApprovals.length} Pending Your Approval`} color="warning" />
        )}
      </Box>

      {myApprovals.length > 0 && tab === 0 && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          You have {myApprovals.length} pending approval(s) requiring action.
        </Alert>
      )}

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label={`My Approvals (${myApprovals.length})`} />
        <Tab label="All Approvals" />
      </Tabs>

      <Card>
        <DataGrid
          rows={displayData.map((a) => ({ ...a, id: a.id }))}
          columns={columns}
          loading={tab === 0 ? myLoading : allLoading}
          autoHeight
          disableRowSelectionOnClick
          sx={{ border: 'none' }}
        />
      </Card>

      {/* Approve/Reject Dialog */}
      <Dialog open={actionDialog.open} onClose={() => setActionDialog({ ...actionDialog, open: false })} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ color: actionDialog.action === 'APPROVE' ? 'success.main' : 'error.main' }}>
          {actionDialog.action === 'APPROVE' ? '✓ Approve Document' : '✗ Reject Document'}
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            Document: {actionDialog.approval?.document_id}
          </Typography>
          <TextField
            label="Comments (optional)"
            multiline
            rows={3}
            fullWidth
            value={comments}
            onChange={(e) => setComments(e.target.value)}
            sx={{ mt: 2 }}
            placeholder={actionDialog.action === 'REJECT' ? 'Please provide a reason for rejection...' : 'Add approval notes...'}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setActionDialog({ ...actionDialog, open: false })}>Cancel</Button>
          <Button
            variant="contained"
            color={actionDialog.action === 'APPROVE' ? 'success' : 'error'}
            disabled={actionMutation.isPending}
            onClick={() => {
              if (actionDialog.approval) {
                actionMutation.mutate({ id: actionDialog.approval.id, action: actionDialog.action, comments })
              }
            }}
          >
            {actionMutation.isPending ? 'Processing...' : actionDialog.action}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}