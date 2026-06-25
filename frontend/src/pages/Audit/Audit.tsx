import React, { useState } from 'react'
import {
  Box, Card, Typography, TextField, Button, Chip,
  Table, TableBody, TableCell, TableHead, TableRow, Tooltip,
  Accordion, AccordionSummary, AccordionDetails, Alert,
} from '@mui/material'
import { ExpandMore, Download } from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../api/client'

export default function Audit() {
  const [documentIdFilter, setDocumentIdFilter] = useState('')
  const [searchId, setSearchId] = useState('')

  const { data: auditLogs = [], isLoading, refetch } = useQuery({
    queryKey: ['audit-all', searchId],
    queryFn: async () => {
      if (searchId) {
        const { data } = await apiClient.get(`/documents/${searchId}/audit-trail`)
        return data
      }
      return []
    },
    enabled: !!searchId,
  })

  const handleSearch = () => {
    setSearchId(documentIdFilter)
  }

  const exportCSV = () => {
    if (!auditLogs.length) return
    const headers = ['Timestamp', 'Action', 'Entity Type', 'Agent', 'Stage', 'Details']
    const rows = auditLogs.map((l: any) => [
      new Date(l.timestamp).toISOString(),
      l.action, l.entity_type, l.agent || '',
      l.stage || '',
      JSON.stringify(l.after_state || {}),
    ])
    const csv = [headers, ...rows].map((r) => r.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `audit_${searchId}_${Date.now()}.csv`
    a.click()
  }

  return (
    <Box>
      <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Box>
          <Typography variant="h5" fontWeight={700}>Audit Trail</Typography>
          <Typography variant="body2" color="text.secondary">
            Complete immutable audit history for all documents, agents, and decisions
          </Typography>
        </Box>
      </Box>

      <Card sx={{ mb: 2, p: 2, display: 'flex', gap: 2, alignItems: 'center' }}>
        <TextField
          label="Document ID or document_id"
          value={documentIdFilter}
          onChange={(e) => setDocumentIdFilter(e.target.value)}
          size="small"
          sx={{ minWidth: 300 }}
          placeholder="Enter Document ID or UUID"
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
        />
        <Button variant="contained" onClick={handleSearch}>Search</Button>
        {auditLogs.length > 0 && (
          <Button variant="outlined" startIcon={<Download />} onClick={exportCSV}>
            Export CSV
          </Button>
        )}
      </Card>

      {!searchId && (
        <Alert severity="info">
          Enter a Document ID to view its complete audit trail. Every agent decision, validation result, matching operation, and approval action is recorded.
        </Alert>
      )}

      {searchId && auditLogs.length === 0 && !isLoading && (
        <Alert severity="warning">No audit records found for document: {searchId}</Alert>
      )}

      {auditLogs.length > 0 && (
        <Card>
          <Box sx={{ p: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography variant="subtitle1" fontWeight={700}>
              {auditLogs.length} Audit Records — Document: {searchId}
            </Typography>
            <Chip label="Immutable" color="info" size="small" />
          </Box>
          <Table size="small">
            <TableHead>
              <TableRow sx={{ bgcolor: '#ffffff' }}>
                <TableCell>Timestamp</TableCell>
                <TableCell>Action</TableCell>
                <TableCell>Entity</TableCell>
                <TableCell>Agent</TableCell>
                <TableCell>Stage</TableCell>
                <TableCell>State Change</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {auditLogs.map((log: any, idx: number) => (
                <TableRow key={log.id || idx} sx={{ '&:hover': { bgcolor: '#ffffff' } }}>
                  <TableCell>
                    <Typography variant="caption">
                      {new Date(log.timestamp).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'medium' })}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" fontWeight={600}>
                      {log.action.replace(/_/g, ' ')}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip label={log.entity_type} size="small" variant="outlined" />
                  </TableCell>
                  <TableCell>
                    {log.agent && <Chip label={log.agent.replace(/_/g, ' ')} size="small" color="primary" variant="outlined" />}
                  </TableCell>
                  <TableCell>
                    {log.stage && (
                      <Typography variant="caption" color="text.secondary">
                        {log.stage.replace(/_/g, ' ')}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    {log.after_state && (
                      <Tooltip title={JSON.stringify(log.after_state, null, 2)} placement="left">
                        <Box component="pre" sx={{ fontSize: 10, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'pointer', bgcolor: '#ffffff', p: 0.5, borderRadius: 1 }}>
                          {JSON.stringify(log.after_state)}
                        </Box>
                      </Tooltip>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </Box>
  )
}