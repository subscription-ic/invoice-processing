import React from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box, Grid, Card, CardContent, CardActionArea, Typography, Chip, CircularProgress,
  List, ListItem, ListItemText, Divider, LinearProgress,
} from '@mui/material'
import {
  Description, CheckCircle, Warning, AttachMoney,
  Inventory, FiberManualRecord,
} from '@mui/icons-material'
import {
  PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { useQuery } from '@tanstack/react-query'
import { dashboardApi } from '../../api/client'
import type { DashboardStats } from '../../types'

const STATUS_COLORS: Record<string, string> = {
  COMPLETED:              '#2e7d32',
  PENDING_APPROVAL:       '#e65100',
  PROCESSING:             '#1565c0',
  EXCEPTION:              '#c62828',
  HUMAN_REVIEW_REQUIRED:  '#f57f17',
  APPROVED:               '#388e3c',
  POSTED:                 '#00695c',
  FAILED:                 '#b71c1c',
}

const PIE_COLORS = ['#1565c0', '#2e7d32', '#e65100', '#c62828', '#7b1fa2', '#0288d1', '#558b2f', '#f57f17']

function StatCard({
  title, value, subtitle, icon, color, onClick,
}: {
  title: string
  value: string | number
  subtitle?: string
  icon: React.ReactNode
  color: string
  onClick?: () => void
}) {
  const content = (
    <CardContent sx={{ p: 3, height: '100%' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <Box sx={{ flex: 1 }}>
          <Typography
            sx={{
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: 1.2,
              textTransform: 'uppercase',
              color: 'text.secondary',
              mb: 1,
            }}
          >
            {title}
          </Typography>
          <Typography
            sx={{ fontSize: 36, fontWeight: 800, lineHeight: 1, color, fontVariantNumeric: 'tabular-nums' }}
          >
            {value}
          </Typography>
          {subtitle && (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 0.75, display: 'block' }}>
              {subtitle}
            </Typography>
          )}
        </Box>
        <Box
          sx={{
            width: 48,
            height: 48,
            borderRadius: 2,
            bgcolor: `${color}18`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color,
            flexShrink: 0,
            ml: 2,
          }}
        >
          {icon}
        </Box>
      </Box>
      {onClick && (
        <Typography
          variant="caption"
          sx={{ mt: 1.5, display: 'block', color, fontWeight: 600, opacity: 0.75 }}
        >
          Click to view →
        </Typography>
      )}
    </CardContent>
  )

  return (
    <Card
      elevation={0}
      sx={{
        height: '100%',
        border: '1px solid #e8eaed',
        borderLeft: `4px solid ${color}`,
        borderRadius: 2,
        transition: 'box-shadow 0.2s, transform 0.15s',
        ...(onClick
          ? { '&:hover': { boxShadow: '0 6px 24px rgba(0,0,0,0.1)', transform: 'translateY(-2px)' } }
          : {}),
      }}
    >
      {onClick ? (
        <CardActionArea onClick={onClick} sx={{ height: '100%', borderRadius: 2, alignItems: 'flex-start', display: 'flex', flexDirection: 'column' }}>
          {content}
        </CardActionArea>
      ) : (
        content
      )}
    </Card>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()

  const { data: stats, isLoading, error } = useQuery<DashboardStats>({
    queryKey: ['dashboard-stats'],
    queryFn: async () => {
      const { data } = await dashboardApi.stats()
      return data
    },
    refetchInterval: 30_000,
  })

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', mt: 12 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (error || !stats) {
    return (
      <Typography color="error" sx={{ mt: 4 }}>
        Failed to load dashboard data.
      </Typography>
    )
  }

  const docsByStatus = Object.entries(stats.documents_by_status).map(([name, value]) => ({ name, value }))
  const exByQueue = Object.entries(stats.exception_by_queue).map(([name, value]) => ({ name, value }))

  const formatCurrency = (v: number) =>
    new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v)

  const slaItems = [
    { label: 'Pending Approvals', value: stats.pending_approvals, color: '#e65100' },
    { label: 'Open Exceptions',   value: stats.open_exceptions,   color: '#c62828' },
    { label: 'Processed Today',   value: stats.documents_today,   color: '#1565c0' },
  ]
  const slaMax = Math.max(...slaItems.map((i) => i.value), 1)

  return (
    <Box>
      {/* ── Header ─────────────────────────────────────────────── */}
      <Box
        sx={{
          mb: 4,
          pb: 3,
          borderBottom: '1px solid #e8eaed',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
        }}
      >
        <Box>
          <Typography
            variant="h4"
            sx={{ fontWeight: 800, letterSpacing: -0.5, color: '#0d1b2a' }}
          >
            AP Operations Center
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Real-time visibility across the Procure-to-Pay pipeline
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <FiberManualRecord sx={{ fontSize: 10, color: '#2e7d32', animation: 'pulse 2s infinite' }} />
          <Typography variant="caption" color="text.secondary" sx={{ mr: 1 }}>
            Live
          </Typography>
          <Chip
            label={`Updated ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`}
            size="small"
            variant="outlined"
            sx={{ borderRadius: 1, fontSize: 11 }}
          />
        </Box>
      </Box>

      {/* ── KPI Row ─────────────────────────────────────────────── */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="Total Documents"
            value={stats.total_documents.toLocaleString()}
            subtitle={`${stats.documents_today} uploaded today`}
            icon={<Description />}
            color="#1565c0"
            onClick={() => navigate('/documents')}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="Pending Approvals"
            value={stats.pending_approvals}
            subtitle="Awaiting decision"
            icon={<CheckCircle />}
            color="#e65100"
            onClick={() => navigate('/approvals')}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="Open Exceptions"
            value={stats.open_exceptions}
            subtitle="Require attention"
            icon={<Warning />}
            color="#c62828"
            onClick={() => navigate('/exceptions')}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="Total Invoice Value"
            value={formatCurrency(Number(stats.total_invoice_amount))}
            subtitle="All time"
            icon={<AttachMoney />}
            color="#6a1b9a"
          />
        </Grid>
      </Grid>

      {/* ── Documents Today (featured) + Status Pie ─────────────── */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} md={4}>
          <Card
            elevation={0}
            sx={{
              height: '100%',
              border: '1px solid #e8eaed',
              borderRadius: 2,
              background: 'linear-gradient(135deg, #f0f4ff 0%, #fafbff 100%)',
              cursor: 'pointer',
              transition: 'box-shadow 0.2s, transform 0.15s',
              '&:hover': { boxShadow: '0 6px 24px rgba(0,0,0,0.1)', transform: 'translateY(-2px)' },
            }}
            onClick={() => navigate('/documents')}
          >
            <CardActionArea sx={{ height: '100%', borderRadius: 2, p: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1.5 }}>
                <Box sx={{ width: 36, height: 36, borderRadius: 1.5, bgcolor: '#1565c018', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#1565c0' }}>
                  <Inventory />
                </Box>
                <Typography sx={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.2, textTransform: 'uppercase', color: 'text.secondary' }}>
                  Documents Processed Today
                </Typography>
              </Box>
              <Typography sx={{ fontSize: 64, fontWeight: 900, lineHeight: 1, color: '#1565c0', fontVariantNumeric: 'tabular-nums' }}>
                {stats.documents_today}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                {stats.total_documents.toLocaleString()} total in system
              </Typography>
              <Typography variant="caption" sx={{ mt: 1.5, display: 'block', color: '#1565c0', fontWeight: 600, opacity: 0.75 }}>
                Click to view all →
              </Typography>
            </CardActionArea>
          </Card>
        </Grid>

        <Grid item xs={12} md={8}>
          <Card elevation={0} sx={{ height: '100%', border: '1px solid #e8eaed', borderRadius: 2 }}>
            <CardContent sx={{ p: 3 }}>
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: '#0d1b2a', mb: 2 }}>
                Documents by Status
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <ResponsiveContainer width="40%" height={180}>
                  <PieChart>
                    <Pie
                      data={docsByStatus}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      innerRadius={45}
                      outerRadius={80}
                      label={false}
                      labelLine={false}
                    >
                      {docsByStatus.map((entry, i) => (
                        <Cell
                          key={i}
                          fill={STATUS_COLORS[entry.name] || PIE_COLORS[i % PIE_COLORS.length]}
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(v, n) => [v, String(n).replace(/_/g, ' ')]}
                      contentStyle={{ borderRadius: 8, fontSize: 12, border: '1px solid #e8eaed' }}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
                  {docsByStatus.map((entry, i) => (
                    <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Box
                        sx={{
                          width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
                          bgcolor: STATUS_COLORS[entry.name] || PIE_COLORS[i % PIE_COLORS.length],
                        }}
                      />
                      <Typography variant="caption" sx={{ flex: 1, color: 'text.secondary' }}>
                        {entry.name.replace(/_/g, ' ')}
                      </Typography>
                      <Typography variant="caption" fontWeight={700}>
                        {entry.value}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* ── Top Vendors + Exception Queue ───────────────────────── */}
      <Grid container spacing={3} sx={{ mb: 3 }}>
        <Grid item xs={12} md={7}>
          <Card elevation={0} sx={{ height: '100%', border: '1px solid #e8eaed', borderRadius: 2 }}>
            <CardContent sx={{ p: 3 }}>
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: '#0d1b2a', mb: 2 }}>
                Top Vendors by Invoice Value
              </Typography>
              <List dense disablePadding>
                {stats.top_vendors_by_amount.slice(0, 7).map((v, i) => (
                  <React.Fragment key={i}>
                    <ListItem disablePadding sx={{ py: 0.75 }}>
                      <ListItemText
                        primary={
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <Typography
                                sx={{
                                  fontSize: 11, fontWeight: 800, color: '#6a1b9a',
                                  bgcolor: '#6a1b9a12', px: 0.75, py: 0.25, borderRadius: 0.75,
                                  minWidth: 20, textAlign: 'center',
                                }}
                              >
                                {i + 1}
                              </Typography>
                              <Typography variant="body2" fontWeight={600}>{v.vendor}</Typography>
                            </Box>
                            <Typography variant="caption" fontWeight={700} color="#6a1b9a">
                              {formatCurrency(v.amount)}
                            </Typography>
                          </Box>
                        }
                        secondary={
                          <LinearProgress
                            variant="determinate"
                            value={
                              stats.top_vendors_by_amount[0]?.amount > 0
                                ? (v.amount / stats.top_vendors_by_amount[0].amount) * 100
                                : 0
                            }
                            sx={{
                              height: 5, borderRadius: 3,
                              bgcolor: '#f3e8fd',
                              '& .MuiLinearProgress-bar': { bgcolor: '#6a1b9a', borderRadius: 3 },
                            }}
                          />
                        }
                      />
                    </ListItem>
                    {i < 6 && <Divider sx={{ opacity: 0.5 }} />}
                  </React.Fragment>
                ))}
              </List>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={5}>
          <Card elevation={0} sx={{ height: '100%', border: '1px solid #e8eaed', borderRadius: 2 }}>
            <CardContent sx={{ p: 3 }}>
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: '#0d1b2a', mb: 2 }}>
                Open Exceptions by Queue
              </Typography>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={exByQueue} barSize={28}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#666' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: '#666' }} axisLine={false} tickLine={false} />
                  <Tooltip
                    contentStyle={{ borderRadius: 8, fontSize: 12, border: '1px solid #e8eaed' }}
                    cursor={{ fill: '#f5f5f5' }}
                  />
                  <Bar dataKey="value" name="Open Exceptions" fill="#c62828" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* ── SLA / Queue Health ──────────────────────────────────── */}
      <Grid container spacing={3}>
        <Grid item xs={12}>
          <Card elevation={0} sx={{ border: '1px solid #e8eaed', borderRadius: 2 }}>
            <CardContent sx={{ p: 3 }}>
              <Typography sx={{ fontSize: 13, fontWeight: 700, color: '#0d1b2a', mb: 3 }}>
                Queue Health
              </Typography>
              <Grid container spacing={4}>
                {slaItems.map((item) => (
                  <Grid item xs={12} sm={4} key={item.label}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                      <Typography variant="body2" color="text.secondary">{item.label}</Typography>
                      <Typography variant="body2" fontWeight={800} color={item.color}>
                        {item.value}
                      </Typography>
                    </Box>
                    <LinearProgress
                      variant="determinate"
                      value={(item.value / slaMax) * 100}
                      sx={{
                        height: 8, borderRadius: 4,
                        bgcolor: `${item.color}18`,
                        '& .MuiLinearProgress-bar': { bgcolor: item.color, borderRadius: 4 },
                      }}
                    />
                  </Grid>
                ))}
              </Grid>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  )
}
