import React, { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDropzone } from 'react-dropzone'
import {
  Box, Card, CardContent, Typography, Button, LinearProgress,
  List, ListItem, ListItemText, ListItemIcon, Chip, Alert,
  CircularProgress, IconButton, Divider, Tooltip,
} from '@mui/material'
import {
  CloudUpload, CheckCircle, Error as ErrorIcon, PictureAsPdf, Image,
  Description, Delete, OpenInNew,
} from '@mui/icons-material'
import { documentsApi } from '../../api/client'

interface UploadFile {
  id: string
  file: File
  status: 'pending' | 'uploading' | 'success' | 'error'
  progress: number
  documentId?: string
  error?: string
}

const ALLOWED_TYPES = ['application/pdf', 'image/jpeg', 'image/png', 'image/tiff',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document']

const FILE_ICONS: Record<string, React.ReactNode> = {
  'application/pdf': <PictureAsPdf color="error" />,
  'image/jpeg':      <Image color="primary" />,
  'image/png':       <Image color="primary" />,
  'image/tiff':      <Image color="primary" />,
}

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const uid = () => Math.random().toString(36).slice(2)

// Max concurrent uploads — keeps server load predictable
const CONCURRENT_UPLOADS = 5

async function runConcurrent<T>(
  items: T[],
  worker: (item: T) => Promise<void>,
  concurrency: number,
): Promise<void> {
  const queue = [...items]
  const active: Promise<void>[] = []

  const next = (): Promise<void> | null => {
    if (queue.length === 0) return null
    const item = queue.shift()!
    const p = worker(item).finally(() => {
      active.splice(active.indexOf(p), 1)
      const n = next()
      if (n) active.push(n)
    })
    return p
  }

  for (let i = 0; i < Math.min(concurrency, items.length); i++) {
    const p = next()
    if (p) active.push(p)
  }

  while (active.length > 0) {
    await Promise.race(active)
  }
}

export default function Upload() {
  const navigate = useNavigate()
  const [files, setFiles] = useState<UploadFile[]>([])
  const [uploading, setUploading] = useState(false)

  const onDrop = useCallback((accepted: File[]) => {
    setFiles(prev => [
      ...prev,
      ...accepted.map(f => ({ id: uid(), file: f, status: 'pending' as const, progress: 0 })),
    ])
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'image/*': ['.jpg', '.jpeg', '.png', '.tiff', '.tif'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
    },
    maxSize: 50 * 1024 * 1024,
  })

  const removeFile = (id: string) =>
    setFiles(prev => prev.filter(f => f.id !== id))

  const clearAll = () =>
    setFiles(prev => prev.filter(f => f.status === 'uploading'))

  const uploadAll = async () => {
    const pending = files.filter(f => f.status === 'pending')
    if (pending.length === 0) return

    setUploading(true)

    const uploadOne = async (item: UploadFile) => {
      setFiles(prev => prev.map(f =>
        f.id === item.id ? { ...f, status: 'uploading', progress: 20 } : f
      ))

      try {
        const { data } = await documentsApi.upload(item.file)

        setFiles(prev => prev.map(f =>
          f.id === item.id
            ? { ...f, status: 'success', progress: 100, documentId: data.document_id }
            : f
        ))

        // Auto-navigate only when uploading a single file
        if (pending.length === 1) {
          navigate(`/documents/${data.document_id}`)
        }
      } catch (err: any) {
        setFiles(prev => prev.map(f =>
          f.id === item.id
            ? { ...f, status: 'error', progress: 0, error: err.response?.data?.detail || 'Upload failed' }
            : f
        ))
      }
    }

    await runConcurrent(pending, uploadOne, CONCURRENT_UPLOADS)
    setUploading(false)
  }

  const pending  = files.filter(f => f.status === 'pending').length
  const success  = files.filter(f => f.status === 'success').length
  const errCount = files.filter(f => f.status === 'error').length

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h5" fontWeight={700}>Upload Documents</Typography>
        <Typography variant="body2" color="text.secondary">
          Upload invoices, bills, or financial documents. The AI pipeline processes each one automatically.
        </Typography>
      </Box>

      {/* Drop Zone */}
      <Card elevation={0} sx={{ mb: 3, border: '1px solid #e0e0e0', borderRadius: 2 }}>
        <CardContent>
          <Box
            {...getRootProps()}
            sx={{
              border: `2px dashed ${isDragActive ? '#a8862b' : '#e0e0e0'}`,
              borderRadius: 2,
              p: { xs: 4, md: 7 },
              textAlign: 'center',
              cursor: 'pointer',
              bgcolor: isDragActive ? '#ffffff' : 'background.paper',
              transition: 'all 0.2s',
              '&:hover': { borderColor: '#a8862b', bgcolor: '#ffffff' },
            }}
          >
            <input {...getInputProps()} />
            <CloudUpload sx={{ fontSize: 56, color: isDragActive ? '#a8862b' : '#e0e0e0', mb: 2 }} />
            <Typography variant="h6" fontWeight={700} gutterBottom>
              {isDragActive ? 'Drop files here' : 'Drag & Drop or click to select'}
            </Typography>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              PDF, JPG, PNG, TIFF, DOCX — max 50 MB per file
            </Typography>
            <Button variant="outlined" sx={{ mt: 2, borderRadius: 1.5 }}>Browse Files</Button>
          </Box>
        </CardContent>
      </Card>

      {/* AI pipeline info */}
      <Card elevation={0} sx={{ mb: 3, bgcolor: '#ffffff', border: '1px solid #ead18a', borderRadius: 2 }}>
        <CardContent sx={{ py: '12px !important' }}>
          <Typography variant="body2" color="#a8862b" fontWeight={600} gutterBottom>
            AI Pipeline
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Intake → Classification → OCR / Vision → Extraction → Validation → Business Profile →
            PO/GRN Matching → Approval Routing → ERP Posting → Payment Scheduling
          </Typography>
        </CardContent>
      </Card>

      {/* File Queue */}
      {files.length > 0 && (
        <Card elevation={0} sx={{ border: '1px solid #e0e0e0', borderRadius: 2 }}>
          <CardContent>
            {/* Queue header */}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <Typography variant="subtitle1" fontWeight={700}>
                  Upload Queue
                </Typography>
                <Chip label={`${files.length} file${files.length !== 1 ? 's' : ''}`} size="small" />
              </Box>
              <Box sx={{ display: 'flex', gap: 1 }}>
                {(success > 0 || errCount > 0) && (
                  <Button size="small" onClick={clearAll} disabled={uploading}>
                    Clear Done
                  </Button>
                )}
                <Button
                  variant="contained"
                  onClick={uploadAll}
                  disabled={uploading || pending === 0}
                  startIcon={uploading ? <CircularProgress size={16} color="inherit" /> : <CloudUpload />}
                  sx={{ borderRadius: 1.5 }}
                >
                  {uploading ? 'Uploading…' : `Upload ${pending} File${pending !== 1 ? 's' : ''}`}
                </Button>
              </Box>
            </Box>

            {/* Status summary */}
            {(success > 0 || errCount > 0) && (
              <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
                {success > 0 && (
                  <Chip
                    label={`${success} sent to pipeline`}
                    color="success"
                    size="small"
                    icon={<CheckCircle />}
                  />
                )}
                {errCount > 0 && (
                  <Chip
                    label={`${errCount} failed`}
                    color="error"
                    size="small"
                    icon={<ErrorIcon />}
                  />
                )}
              </Box>
            )}

            {/* Batch hint */}
            {files.length > 1 && (
              <Alert severity="info" sx={{ mb: 2, borderRadius: 1.5, py: 0.5 }}>
                Batch mode — uploading {Math.min(CONCURRENT_UPLOADS, pending)} at a time.
                Use the <strong>View</strong> button next to each file to watch its pipeline progress.
              </Alert>
            )}

            <List dense disablePadding>
              {files.map((item, idx) => (
                <React.Fragment key={item.id}>
                  <ListItem
                    disablePadding
                    sx={{ py: 0.75 }}
                    secondaryAction={
                      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                        {item.documentId && (
                          <Tooltip title="View pipeline progress">
                            <Button
                              size="small"
                              variant="outlined"
                              endIcon={<OpenInNew fontSize="small" />}
                              onClick={() => navigate(`/documents/${item.documentId}`)}
                              sx={{ borderRadius: 1.5, textTransform: 'none' }}
                            >
                              View
                            </Button>
                          </Tooltip>
                        )}
                        <Tooltip title="Remove">
                          <span>
                            <IconButton
                              edge="end"
                              size="small"
                              onClick={() => removeFile(item.id)}
                              disabled={item.status === 'uploading'}
                            >
                              <Delete fontSize="small" />
                            </IconButton>
                          </span>
                        </Tooltip>
                      </Box>
                    }
                  >
                    <ListItemIcon sx={{ minWidth: 40 }}>
                      {item.status === 'success'   ? <CheckCircle color="success" /> :
                       item.status === 'error'     ? <ErrorIcon color="error" /> :
                       item.status === 'uploading' ? <CircularProgress size={20} /> :
                       (FILE_ICONS[item.file.type] ?? <Description />)}
                    </ListItemIcon>
                    <ListItemText
                      primary={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, pr: 14 }}>
                          <Typography variant="body2" fontWeight={600} noWrap sx={{ maxWidth: 320 }}>
                            {item.file.name}
                          </Typography>
                          <Chip
                            label={
                              item.status === 'success'   ? 'SENT TO PIPELINE' :
                              item.status === 'uploading' ? 'UPLOADING' :
                              item.status === 'error'     ? 'FAILED' :
                              'PENDING'
                            }
                            size="small"
                            color={
                              item.status === 'success'   ? 'success' :
                              item.status === 'error'     ? 'error' :
                              item.status === 'uploading' ? 'info' :
                              'default'
                            }
                          />
                        </Box>
                      }
                      secondary={
                        <Box sx={{ pr: 14 }}>
                          <Typography variant="caption" color="text.secondary">
                            {formatSize(item.file.size)}
                            {item.error && ` · ${item.error}`}
                          </Typography>
                          {item.status === 'uploading' && (
                            <LinearProgress sx={{ mt: 0.5, height: 3, borderRadius: 2 }} />
                          )}
                        </Box>
                      }
                    />
                  </ListItem>
                  {idx < files.length - 1 && <Divider sx={{ opacity: 0.5 }} />}
                </React.Fragment>
              ))}
            </List>
          </CardContent>
        </Card>
      )}
    </Box>
  )
}
