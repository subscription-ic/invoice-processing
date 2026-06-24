// Format any date (string or Date) as dd/mm/yyyy
export function formatDate(value?: string | Date | null): string {
  if (!value) return '—'
  const d = typeof value === 'string' ? new Date(value) : value
  if (isNaN(d.getTime())) return String(value)
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const yyyy = d.getFullYear()
  return `${dd}/${mm}/${yyyy}`
}

// Format date + time as dd/mm/yyyy HH:MM
export function formatDateTime(value?: string | Date | null): string {
  if (!value) return '—'
  const d = typeof value === 'string' ? new Date(value) : value
  if (isNaN(d.getTime())) return String(value)
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const yyyy = d.getFullYear()
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${dd}/${mm}/${yyyy} ${hh}:${mi}`
}

export function formatCurrency(value?: number | string | null): string {
  if (value == null || value === '') return '—'
  const n = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(n)) return '—'
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

// PII masking — show first 2 chars then *****
export function maskMiddle(value?: string | null): string {
  if (!value) return '—'
  const s = String(value).trim()
  if (s.length <= 2) return '*****'
  return s.slice(0, 2) + '*****'
}

// Masks a monetary amount
export function maskAmount(): string {
  return '₹ *****'
}