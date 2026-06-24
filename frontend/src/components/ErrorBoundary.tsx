import React from 'react'
import { Box, Typography, Button, Alert } from '@mui/material'

interface State { hasError: boolean; error?: Error }

export default class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('Render error:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <Box sx={{ p: 4 }}>
          <Alert severity="error" sx={{ mb: 2 }}>
            <Typography variant="subtitle2" fontWeight={700}>This page hit a rendering error</Typography>
            <Typography variant="caption" component="pre" sx={{ whiteSpace: 'pre-wrap', mt: 1 }}>
              {this.state.error?.message}
              {'\n\n'}
              {this.state.error?.stack?.split('\n').slice(0, 5).join('\n')}
            </Typography>
          </Alert>
          <Button variant="contained" onClick={() => { this.setState({ hasError: false }); window.history.back() }}>
            Go Back
          </Button>
          <Button sx={{ ml: 1 }} onClick={() => window.location.reload()}>Reload</Button>
        </Box>
      )
    }
    return this.props.children
  }
}