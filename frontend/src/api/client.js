import axios from 'axios'

const BASE = '/api'

const api = axios.create({
  baseURL: BASE,
  timeout: 10000,
})

// Attach JWT on every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Auto-refresh on 401
api.interceptors.response.use(
  (res) => res,
  async (err) => {
    if (err.response?.status === 401) {
      const refresh = localStorage.getItem('refresh_token')
      if (refresh) {
        try {
          const { data } = await axios.post(`${BASE}/auth/refresh`, { refresh_token: refresh })
          localStorage.setItem('access_token', data.access_token)
          err.config.headers.Authorization = `Bearer ${data.access_token}`
          return api.request(err.config)
        } catch {
          localStorage.clear()
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(err)
  }
)

// ── Auth ─────────────────────────────────────────────────────────
export const login = (email, password) => {
  const form = new URLSearchParams()
  form.append('username', email)
  form.append('password', password)
  return api.post('/auth/login', form)
}
export const register = (data) => api.post('/auth/register', data)
export const getMe = () => api.get('/auth/me')

// ── Sales ────────────────────────────────────────────────────────
export const getSales = () => api.get('/sales')
export const getSale = (id) => api.get(`/sales/${id}`)
export const preregister = (saleId) => api.post(`/sales/${saleId}/preregister`)
export const getAdmissionStatus = (saleId) => api.get(`/sales/${saleId}/admission-status`)

// ── Reservations ─────────────────────────────────────────────────
export const createReservation = (data) => api.post('/reservations', data)
export const getQueueStatus = (saleId) => api.get(`/reservations/queue-status?sale_id=${saleId}`)
export const getReservation = (id) => api.get(`/reservations/${id}`)
export const recoverReservation = (saleId) => api.post(`/reservations/recover?sale_id=${saleId}`)
export const modifyQuantity = (reservationId, newQty) =>
  api.patch(`/reservations/${reservationId}/quantity`, { new_quantity: newQty })

// ── Cart ─────────────────────────────────────────────────────────
export const getCart = () => api.get('/orders/cart')
export const payOrder = (orderId, paymentData) => api.post(`/orders/${orderId}/pay`, paymentData)
export const cancelOrder = (orderId) => api.post(`/orders/${orderId}/cancel`)

// ── Orders ───────────────────────────────────────────────────────
export const getOrders = () => api.get('/orders')
export const getOrder = (id) => api.get(`/orders/${id}`)

// ── Admin ────────────────────────────────────────────────────────
export const adminGetSales = () => api.get('/admin/sales')
export const adminGetSaleStats = (id) => api.get(`/admin/sales/${id}/stats`)
export const adminPauseSale = (id) => api.post(`/admin/sales/${id}/pause`)
export const adminResumeSale = (id) => api.post(`/admin/sales/${id}/resume`)
export const adminCompleteSale = (id) => api.post(`/admin/sales/${id}/complete`)
export const adminAdjustInventory = (id, data) => api.post(`/admin/sales/${id}/adjust-inventory`, data)
export const adminGetQueue = (saleId) => api.get(`/admin/queue/${saleId}`)
export const adminGetDLQ = () => api.get('/admin/dlq')
export const adminGetCircuitBreakers = () => api.get('/admin/circuit-breakers')

export default api