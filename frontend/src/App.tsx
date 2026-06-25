import React from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider, createTheme, CssBaseline, Box, CircularProgress } from '@mui/material'
import { useAuthStore } from './store'
import Layout from './components/Layout/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import Dashboard from './pages/Dashboard/Dashboard'
import Upload from './pages/Upload/Upload'
import Documents from './pages/Documents/Documents'
import DocumentDetail from './pages/Documents/DocumentDetail'
import Approvals from './pages/Approvals/Approvals'
import Exceptions from './pages/Exceptions/Exceptions'
import ExceptionDetail from './pages/Exceptions/ExceptionDetail'
import Admin from './pages/Admin/Admin'
import Audit from './pages/Audit/Audit'
import MockDB from './pages/MockDB/MockDB'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
  },
})

const theme = createTheme({
  palette: {
    // Professional white theme. Brand = gold (buttons/accents) + black chrome (sidebar/top bar).
    // Functional STATUS colors are semantic so the demo reads clearly:
    //   success = green, warning = orange (stuck), error = red. No blue anywhere (info -> gold).
    mode: 'light',
    primary: { main: '#A8862B', dark: '#6B5518', light: '#D4AF37', contrastText: '#FFFFFF' },
    secondary: { main: '#1A1A1A', dark: '#000000', light: '#3A3A3A', contrastText: '#FFFFFF' },
    success: { main: '#2E7D32', dark: '#1B5E20', light: '#4CAF50', contrastText: '#FFFFFF' },
    warning: { main: '#ED6C02', dark: '#C25700', light: '#FF9800', contrastText: '#FFFFFF' },
    error:   { main: '#D32F2F', dark: '#B71C1C', light: '#EF5350', contrastText: '#FFFFFF' },
    info:    { main: '#8C6E2F', dark: '#5A4A1F', light: '#C9A227', contrastText: '#FFFFFF' },
    background: { default: '#F7F8FA', paper: '#FFFFFF' },
    text: { primary: '#1A1A1A', secondary: '#5A5A5A' },
    divider: 'rgba(0,0,0,0.10)',
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
    h4: { fontWeight: 700 },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
  },
  components: {
    MuiCard: { styleOverrides: { root: { borderRadius: 12 } } },
    MuiButton: { styleOverrides: { root: { borderRadius: 8, textTransform: 'none', fontWeight: 600 } } },
    MuiChip: { styleOverrides: { root: { borderRadius: 6 } } },
  },
})

function AuthBootstrap({ children }: { children: React.ReactNode }) {
  const { setAuth } = useAuthStore()
  const hasToken = !!localStorage.getItem('access_token')
  const [ready, setReady] = React.useState(hasToken)

  React.useEffect(() => {
    if (hasToken) { setReady(true); return }
    import('./api/client').then(({ authApi }) => {
      authApi.login('admin', 'admin')
        .then(({ data }) => { setAuth(data.user, data.access_token); setReady(true) })
        .catch(() =>
          authApi.login('admin@company.com', 'password123')
            .then(({ data }) => { setAuth(data.user, data.access_token); setReady(true) })
            .catch(() => setReady(true)),
        )
    })
  }, [hasToken, setAuth])

  // Demo: once per browser session, wipe previously-uploaded docs so each demo
  // session starts clean and new uploads number from DOC-101 again.
  React.useEffect(() => {
    if (!ready) return
    if (sessionStorage.getItem('demo_reset_v1')) return
    sessionStorage.setItem('demo_reset_v1', '1')
    import('./api/client').then(({ documentsApi }) => {
      documentsApi.demoReset().catch(() => {})
    })
  }, [ready])

  if (!ready) {
    return (
      <Box sx={{ display: 'flex', height: '100vh', alignItems: 'center', justifyContent: 'center' }}>
        <CircularProgress />
      </Box>
    )
  }
  return <>{children}</>
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <BrowserRouter>
          <Routes>
            <Route
              path="/"
              element={
                <AuthBootstrap>
                  <ErrorBoundary>
                    <Layout />
                  </ErrorBoundary>
                </AuthBootstrap>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="upload" element={<Upload />} />
              <Route path="documents" element={<Documents />} />
              <Route path="documents/:id" element={<DocumentDetail />} />
              <Route path="approvals" element={<Approvals />} />
              <Route path="exceptions" element={<Exceptions />} />
              <Route path="exceptions/:id" element={<ExceptionDetail />} />
              <Route path="admin" element={<Admin />} />
              <Route path="audit" element={<Audit />} />
              <Route path="mock-db" element={<MockDB />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
