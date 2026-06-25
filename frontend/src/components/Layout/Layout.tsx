import React, { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import {
  Box, Drawer, AppBar, Toolbar, Typography, IconButton, List,
  ListItemButton, ListItemIcon, ListItemText, Divider, Badge,
  Avatar, Menu, MenuItem, Tooltip, Chip,
} from '@mui/material'
import {
  Menu as MenuIcon, Dashboard, CloudUpload, Description, CheckCircle,
  Warning, Settings, History, Notifications, AccountCircle, Logout,
  ChevronLeft,
} from '@mui/icons-material'
import { useAuthStore, useUIStore } from '../../store'
import ErrorBoundary from '../ErrorBoundary'
import { useQuery } from '@tanstack/react-query'
import { dashboardApi } from '../../api/client'

const DRAWER_WIDTH = 260

const NAV_ITEMS = [
  { label: 'Dashboard',    icon: <Dashboard />,   path: '/'           },
  { label: 'Upload',       icon: <CloudUpload />, path: '/upload'     },
  { label: 'Documents',    icon: <Description />, path: '/documents'  },
  { label: 'Approvals',    icon: <CheckCircle />, path: '/approvals'  },
  { label: 'Exceptions',   icon: <Warning />,     path: '/exceptions' },
  { label: 'Audit Trail',  icon: <History />,     path: '/audit'      },
  { label: 'Mock ERP DB',  icon: <Settings />,    path: '/admin'      },
]

export default function Layout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuthStore()
  const { sidebarOpen, toggleSidebar, notifications, setNotifications } = useUIStore()
  const [anchorEl, setAnchorEl] = useState<null | HTMLElement>(null)
  const [notifAnchor, setNotifAnchor] = useState<null | HTMLElement>(null)

  useQuery({
    queryKey: ['notifications'],
    queryFn: async () => {
      const { data } = await dashboardApi.notifications()
      setNotifications(data)
      return data
    },
    refetchInterval: 30_000,
  })

  const unreadCount = notifications.filter((n) => !n.is_read).length

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', maxWidth: '100vw', overflowX: 'hidden' }}>
      {/* App Bar */}
      <AppBar
        position="fixed"
        sx={{ zIndex: (theme) => theme.zIndex.drawer + 1, bgcolor: '#0d0d0d', borderBottom: '1px solid #D4AF37' }}
      >
        <Toolbar>
          <IconButton color="inherit" onClick={toggleSidebar} edge="start" sx={{ mr: 2 }}>
            {sidebarOpen ? <ChevronLeft /> : <MenuIcon />}
          </IconButton>
          <Typography variant="h6" noWrap sx={{ flexGrow: 1, fontWeight: 700, color: '#D4AF37' }}>
            AP Automation Platform
          </Typography>
          <Tooltip title="Notifications">
            <IconButton color="inherit" onClick={(e) => setNotifAnchor(e.currentTarget)}>
              <Badge badgeContent={unreadCount} color="error">
                <Notifications />
              </Badge>
            </IconButton>
          </Tooltip>
          <Tooltip title={user?.name}>
            <IconButton color="inherit" onClick={(e) => setAnchorEl(e.currentTarget)}>
              <Avatar sx={{ width: 32, height: 32, bgcolor: '#D4AF37', color: '#000', fontSize: 14 }}>
                {user?.name?.[0]?.toUpperCase()}
              </Avatar>
            </IconButton>
          </Tooltip>
        </Toolbar>
      </AppBar>

      {/* Notifications Menu */}
      <Menu
        anchorEl={notifAnchor}
        open={Boolean(notifAnchor)}
        onClose={() => setNotifAnchor(null)}
        PaperProps={{ sx: { width: 360, maxHeight: 400 } }}
      >
        <Box sx={{ p: 2 }}>
          <Typography variant="subtitle2" fontWeight={700}>Notifications</Typography>
        </Box>
        <Divider />
        {notifications.slice(0, 10).map((n) => (
          <MenuItem
            key={n.id}
            onClick={() => { setNotifAnchor(null); if (n.action_url) navigate(n.action_url) }}
            sx={{ bgcolor: n.is_read ? 'transparent' : 'action.hover', whiteSpace: 'normal' }}
          >
            <Box>
              <Typography variant="body2" fontWeight={600}>{n.title}</Typography>
              <Typography variant="caption" color="text.secondary">{n.body}</Typography>
            </Box>
          </MenuItem>
        ))}
        {notifications.length === 0 && (
          <MenuItem disabled><Typography variant="body2">No notifications</Typography></MenuItem>
        )}
      </Menu>

      {/* User Menu */}
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        <MenuItem disabled>
          <Box>
            <Typography variant="body2" fontWeight={700}>{user?.name}</Typography>
            <Typography variant="caption" color="text.secondary">{user?.role}</Typography>
          </Box>
        </MenuItem>
        <Divider />
        <MenuItem onClick={() => { logout(); navigate('/login') }}>
          <Logout sx={{ mr: 1, fontSize: 18 }} /> Logout
        </MenuItem>
      </Menu>

      {/* Sidebar */}
      <Drawer
        variant="persistent"
        open={sidebarOpen}
        sx={{
          width: sidebarOpen ? DRAWER_WIDTH : 0,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: DRAWER_WIDTH,
            boxSizing: 'border-box',
            bgcolor: '#0d0d0d',
            color: 'white',
            borderRight: '1px solid #2a2a2a',
          },
        }}
      >
        <Toolbar />
        <Box sx={{ overflow: 'auto', mt: 1 }}>
          <List dense>
            {NAV_ITEMS.map((item) => {
              const isActive = item.path === '/'
                ? location.pathname === '/'
                : location.pathname.startsWith(item.path)
              return (
                <ListItemButton
                  key={item.path}
                  selected={isActive}
                  onClick={() => navigate(item.path)}
                  sx={{
                    mx: 1, mb: 0.5, borderRadius: 2,
                    '&.Mui-selected': { bgcolor: '#D4AF37', color: '#000', '&:hover': { bgcolor: '#E6C75A' } },
                    '&:hover': { bgcolor: 'rgba(212,175,55,0.12)' },
                    color: 'white',
                  }}
                >
                  <ListItemIcon sx={{ color: isActive ? '#000' : 'rgba(212,175,55,0.8)', minWidth: 36 }}>
                    {item.icon}
                  </ListItemIcon>
                  <ListItemText
                    primary={item.label}
                    primaryTypographyProps={{ fontSize: 14, fontWeight: isActive ? 700 : 400 }}
                  />
                </ListItemButton>
              )
            })}
          </List>
        </Box>
        <Box sx={{ p: 2, mt: 'auto' }}>
          <Typography variant="caption" color="rgba(255,255,255,0.4)">
            AP Platform v1.0.0
          </Typography>
        </Box>
      </Drawer>

      {/* Main Content — flexGrow fills the space beside the drawer; no extra margin */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          minWidth: 0,
          p: 3,
          mt: 8,
          transition: 'all 0.2s',
          bgcolor: 'background.default',
          minHeight: 'calc(100vh - 64px)',
          boxSizing: 'border-box',
          overflowX: 'hidden',
        }}
      >
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </Box>
    </Box>
  )
}