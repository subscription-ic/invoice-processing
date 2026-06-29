import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || ''

export const apiClient = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  headers: { 'Content-Type': 'application/json' },
})

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // On 401, clear the stale token and reload — AuthBootstrap will silently
    // re-authenticate. (Avoid redirecting to /login which no longer exists.)
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/token')) {
      const hadToken = localStorage.getItem('access_token')
      localStorage.removeItem('access_token')
      localStorage.removeItem('user')
      if (hadToken) window.location.reload()
    }
    return Promise.reject(error)
  }
)

// Auth
export const authApi = {
  login: (email: string, password: string) => {
    const form = new FormData()
    form.append('username', email)
    form.append('password', password)
    return apiClient.post('/auth/token', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  me: () => apiClient.get('/auth/me'),
  register: (data: object) => apiClient.post('/auth/register', data),
}

// Documents
export const documentsApi = {
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post('/documents/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000, // allow for backend cold-start; retry handles failures
    })
  },
  list: (params?: object) => apiClient.get('/documents', { params }),
  get: (id: string) => apiClient.get(`/documents/${id}`),
  getWorkflow: (id: string) => apiClient.get(`/documents/${id}/workflow`),
  getValidation: (id: string) => apiClient.get(`/documents/${id}/validation-results`),
  getMatching: (id: string) => apiClient.get(`/documents/${id}/matching`),
  getAuditTrail: (id: string) => apiClient.get(`/documents/${id}/audit-trail`),
  getTaskStatus: (taskId: string) => apiClient.get(`/documents/task/${taskId}/status`),
  delete: (id: string) => apiClient.delete(`/documents/${id}`),
  // Phase 8 — Explainability
  getExplanation: (id: string) => apiClient.get(`/documents/${id}/explanation`),
  // Demo: wipe uploaded docs (DOC-101+) so each session restarts from DOC-101
  demoReset: () => apiClient.post('/documents/demo-reset'),
}

// Vendors
export const vendorsApi = {
  list: (params?: object) => apiClient.get('/vendors', { params }),
  get: (id: string) => apiClient.get(`/vendors/${id}`),
  create: (data: object) => apiClient.post('/vendors', data),
  update: (id: string, data: object) => apiClient.patch(`/vendors/${id}`, data),
}

// Purchase Orders
export const poApi = {
  list: (params?: object) => apiClient.get('/purchase-orders', { params }),
  get: (id: string) => apiClient.get(`/purchase-orders/${id}`),
  create: (data: object) => apiClient.post('/purchase-orders', data),
  update: (id: string, data: object) => apiClient.patch(`/purchase-orders/${id}`, data),
}

// Approvals
export const approvalsApi = {
  list: (params?: object) => apiClient.get('/approvals', { params }),
  myApprovals: (params?: object) => apiClient.get('/approvals/my', { params }),
  action: (id: string, data: object) => apiClient.post(`/approvals/${id}/action`, data),
  delegate: (id: string, delegateId: string) => apiClient.post(`/approvals/${id}/delegate?delegate_id=${delegateId}`),
}

// Exceptions
/** Returns the direct URL for streaming the raw uploaded file (PDF/image). */
export function documentFileUrl(documentId: string): string {
  const base = import.meta.env.VITE_API_URL || window.location.origin
  return `${base}/api/v1/documents/${documentId}/file`
}

export const exceptionsApi = {
  list: (params?: object) => apiClient.get('/exceptions', { params }),
  get: (id: string) => apiClient.get(`/exceptions/${id}`),
  summary: (id: string) => apiClient.get(`/exceptions/${id}/summary`),
  resolve: (id: string, data: object) => apiClient.post(`/exceptions/${id}/resolve`, data),
  assign: (id: string, data: object) => apiClient.post(`/exceptions/${id}/assign`, data),
}

// Dashboard
export const dashboardApi = {
  stats: () => apiClient.get('/dashboard/stats'),
  notifications: () => apiClient.get('/dashboard/notifications'),
  markRead: (id: string) => apiClient.post(`/dashboard/notifications/${id}/read`),
}

// Admin
export const adminApi = {
  getCostCenters: () => apiClient.get('/admin/cost-centers'),
  createCostCenter: (data: object) => apiClient.post('/admin/cost-centers', data),
  getGLCodes: () => apiClient.get('/admin/gl-codes'),
  createGLCode: (data: object) => apiClient.post('/admin/gl-codes', data),
  getContracts: () => apiClient.get('/admin/contracts'),
  createContract: (data: object) => apiClient.post('/admin/contracts', data),
  getLeaseContracts: () => apiClient.get('/admin/lease-contracts'),
  createLeaseContract: (data: object) => apiClient.post('/admin/lease-contracts', data),
  getAssets: () => apiClient.get('/admin/assets'),
  createAsset: (data: object) => apiClient.post('/admin/assets', data),
  getEmployees: () => apiClient.get('/admin/employees'),
  createEmployee: (data: object) => apiClient.post('/admin/employees', data),
  getBudgets: () => apiClient.get('/admin/budgets'),
  createBudget: (data: object) => apiClient.post('/admin/budgets', data),
  getApprovalRules: () => apiClient.get('/admin/approval-rules'),
  createApprovalRule: (data: object) => apiClient.post('/admin/approval-rules', data),
  getValidationProfiles: () => apiClient.get('/admin/validation-profiles'),
  createValidationProfile: (data: object) => apiClient.post('/admin/validation-profiles', data),
  getConfigurations: () => apiClient.get('/admin/configurations'),
  updateConfiguration: (id: string, data: object) => apiClient.patch(`/admin/configurations/${id}`, data),
  getUsers: () => apiClient.get('/admin/users'),
  getErpPostings: () => apiClient.get('/admin/erp-postings'),
  getPaymentSchedules: () => apiClient.get('/admin/payment-schedules'),
  getGRNs: () => apiClient.get('/admin/grns'),
  getPOLineItems: (poId: string) => apiClient.get(`/admin/po-line-items/${poId}`),
  // DB browser
  getDBTables: () => apiClient.get('/admin/db/tables'),
  getDBTableSchema: (table: string) => apiClient.get(`/admin/db/tables/${table}/schema`),
  getDBTableData: (table: string, page: number, pageSize: number) =>
    apiClient.get(`/admin/db/tables/${table}/data`, { params: { page, page_size: pageSize } }),
}