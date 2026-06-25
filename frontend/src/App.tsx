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
    // Black & gold identity: light content surfaces, black chrome (sidebar/top bar/login),
    // gold accents throughout. Strict palette — NO green / yellow / blue anywhere.
    mode: 'light',
    primary: { main: '#A8862B', dark: '#6B5518', light: '#D4AF37', contrastText: '#000000' },
    secondary: { main: '#8C6E2F', dark: '#5A4A1F', light: '#C9A227', contrastText: '#000000' },
    // success/info/warning are all gold shades (no green/blue/yellow).
    // error keeps a restrained red for destructive/critical states only.
    success: { main: '#A8862B', dark: '#6B5518', light: '#D4AF37', contrastText: '#000000' },
    info: { main: '#8C6E2F', dark: '#5A4A1F', light: '#C9A227', contrastText: '#000000' },
    warning: { main: '#B8860B', dark: '#6B5518', light: '#D4AF37', contrastText: '#000000' },
    error: { main: '#C0392B', dark: '#8E2A20', light: '#E07B6E', contrastText: '#FFFFFF' },
    background: { default: '#FAF8F3', paper: '#FFFFFF' },
    text: { primary: '#1A1A1A', secondary: '#6B5518' },
    divider: 'rgba(168,134,43,0.25)',
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
