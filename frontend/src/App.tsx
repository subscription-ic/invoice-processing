import React from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider, createTheme, CssBaseline, Box, CircularProgress } from '@mui/material'
import { useAuthStore } from './store'
import Layout from './components/Layout/Layout'
import Dashboard from './pages/Dashboard/Dashboard'
import Upload from './pages/Upload/Upload'
import Documents from './pages/Documents/Documents'
import DocumentDetail from './pages/Documents/DocumentDetail'
import Approvals from './pages/Approvals/Approvals'
import Exceptions from './pages/Exceptions/Exceptions'
import Admin from './pages/Admin/Admin'
import Audit from './pages/Audit/Audit'
import MockDB from './pages/MockDB/MockDB'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
})

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#1976d2', dark: '#115293' },
    secondary: { main: '#dc004e' },
    background: { default: '#f4f6f8' },
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

// Silently authenticate in the background so the app opens without a login screen.
function AuthBootstrap({ children }: { children: React.ReactNode }) {
  const { setAuth } = useAuthStore()
  // Source of truth = the actual token in localStorage (not the persisted flag).
  const hasToken = !!localStorage.getItem('access_token')
  const [ready, setReady] = React.useState(hasToken)

  React.useEffect(() => {
    if (hasToken) { setReady(true); return }
    import('./api/client').then(({ authApi }) => {
      // Try the simple admin user first, fall back to the seeded email user.
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
                  <Layout />
                </AuthBootstrap>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="upload" element={<Upload />} />
              <Route path="documents" element={<Documents />} />
              <Route path="documents/:id" element={<DocumentDetail />} />
              <Route path="approvals" element={<Approvals />} />
              <Route path="exceptions" element={<Exceptions />} />
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