import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

// Surface any uncaught JS / Promise errors visibly instead of white-screen
window.onerror = (_msg, _url, _line, _col, error) => {
  const pre = document.createElement('pre')
  pre.style.cssText = 'position:fixed;inset:0;z-index:99999;background:#0d0d0d;color:#ef4444;padding:32px;font-size:13px;white-space:pre-wrap;overflow:auto'
  pre.textContent = `JS ERROR\n${error?.message ?? _msg}\n\n${error?.stack ?? ''}`
  document.body.appendChild(pre)
}
window.addEventListener('unhandledrejection', (e) => {
  const pre = document.createElement('pre')
  pre.style.cssText = 'position:fixed;inset:0;z-index:99999;background:#0d0d0d;color:#d4af37;padding:32px;font-size:13px;white-space:pre-wrap;overflow:auto'
  pre.textContent = `UNHANDLED PROMISE\n${e.reason}`
  document.body.appendChild(pre)
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)