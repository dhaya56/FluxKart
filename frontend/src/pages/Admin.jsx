import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { format } from 'date-fns'
import {
  adminGetSales, adminPauseSale, adminResumeSale,
  adminCompleteSale, adminAdjustInventory, adminGetDLQ,
  adminGetCircuitBreakers,
} from '../api/client'
import api from '../api/client'

// ── Extra admin API calls not in client.js yet ────────────────────────────────
const adminCreateSale   = (data)        => api.post('/admin/sales', data)
const adminEditSale     = (id, data)    => api.put(`/admin/sales/${id}`, data)
const adminDeleteSale   = (id)          => api.delete(`/admin/sales/${id}`)
const adminActivateSale = (id)          => api.post(`/admin/sales/${id}/activate`)
const adminGetUsers     = ()            => api.get('/admin/users')
const adminDeactivateUser = (id)        => api.post(`/admin/users/${id}/deactivate`)
const adminActivateUser   = (id)        => api.post(`/admin/users/${id}/activate`)
const adminDeleteUser     = (id)        => api.delete(`/admin/users/${id}`)

// ── Helpers ───────────────────────────────────────────────────────────────────
const toLocalInput = (isoStr) => {
  if (!isoStr) return ''
  const d = new Date(isoStr)
  // Format for datetime-local input: YYYY-MM-DDTHH:MM
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 16)
}

const EMPTY_FORM = {
  title: '', description: '', product_name: '',
  original_price: '', sale_price: '',
  total_quantity: '', starts_at: '', ends_at: '',
}

// ── Sale Form Modal ───────────────────────────────────────────────────────────
function SaleFormModal({ sale, onClose, onSave }) {
  const isEdit = Boolean(sale)
  const [form, setForm] = useState(
    isEdit ? {
      title:          sale.title,
      description:    sale.description || '',
      product_name:   sale.product_name,
      original_price: sale.original_price,
      sale_price:     sale.sale_price,
      total_quantity: sale.total_quantity,
      starts_at:      toLocalInput(sale.starts_at),
      ends_at:        toLocalInput(sale.ends_at),
    } : EMPTY_FORM
  )
  const [saving, setSaving] = useState(false)

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }))

  const handleSave = async () => {
    if (!form.title || !form.product_name || !form.original_price ||
        !form.sale_price || !form.total_quantity || !form.starts_at || !form.ends_at) {
      toast.error('All fields except description are required')
      return
    }
    setSaving(true)
    try {
      const payload = {
        ...form,
        original_price: parseFloat(form.original_price),
        sale_price:     parseFloat(form.sale_price),
        total_quantity: parseInt(form.total_quantity),
        starts_at:      new Date(form.starts_at).toISOString(),
        ends_at:        new Date(form.ends_at).toISOString(),
      }
      if (isEdit) {
        await adminEditSale(sale.id, payload)
        toast.success('Sale updated')
      } else {
        await adminCreateSale(payload)
        toast.success('Sale created')
      }
      onSave()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.75)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24,
    }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        width: '100%', maxWidth: 560,
        maxHeight: '90vh', overflowY: 'auto',
        padding: 32,
      }}>
        <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 36, marginBottom: 24 }}>
          {isEdit ? 'EDIT SALE' : 'CREATE SALE'}
        </h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="form-group">
            <label className="form-label">Title</label>
            <input className="form-input" value={form.title} onChange={set('title')} placeholder="iPhone 15 Pro Flash Sale" />
          </div>
          <div className="form-group">
            <label className="form-label">Product Name</label>
            <input className="form-input" value={form.product_name} onChange={set('product_name')} placeholder="iPhone 15 Pro 256GB" />
          </div>
          <div className="form-group">
            <label className="form-label">Description</label>
            <input className="form-input" value={form.description} onChange={set('description')} placeholder="Optional description" />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="form-group">
              <label className="form-label">Original Price ($)</label>
              <input className="form-input" type="number" step="0.01" min="0" value={form.original_price} onChange={set('original_price')} placeholder="1199.99" />
            </div>
            <div className="form-group">
              <label className="form-label">Sale Price ($)</label>
              <input className="form-input" type="number" step="0.01" min="0" value={form.sale_price} onChange={set('sale_price')} placeholder="839.99" />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Total Quantity</label>
            <input className="form-input" type="number" min="1" value={form.total_quantity} onChange={set('total_quantity')} placeholder="50" />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div className="form-group">
              <label className="form-label">Starts At</label>
              <input className="form-input" type="datetime-local" value={form.starts_at} onChange={set('starts_at')} />
            </div>
            <div className="form-group">
              <label className="form-label">Ends At</label>
              <input className="form-input" type="datetime-local" value={form.ends_at} onChange={set('ends_at')} />
            </div>
          </div>

          {/* Price preview */}
          {form.original_price && form.sale_price && (
            <div style={{
              background: 'var(--bg-elevated)', border: '1px solid var(--border)',
              borderRadius: 4, padding: '10px 14px',
              fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)',
            }}>
              Discount: <span style={{ color: 'var(--accent-hot)', fontWeight: 700 }}>
                {Math.round((1 - form.sale_price / form.original_price) * 100)}% off
              </span>
              {' '}· Save ${(form.original_price - form.sale_price).toFixed(2)}
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
            <button className="btn btn-primary" onClick={handleSave} disabled={saving} style={{ flex: 1 }}>
              {saving ? 'Saving...' : isEdit ? 'Save Changes' : 'Create Sale'}
            </button>
            <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main Admin Page ───────────────────────────────────────────────────────────
export default function Admin() {
  const [tab, setTab]       = useState('sales')
  const [sales, setSales]   = useState([])
  const [users, setUsers]   = useState([])
  const [dlq, setDlq]       = useState(null)
  const [cbs, setCbs]       = useState([])
  const [loading, setLoading] = useState(true)
  const [adjusting, setAdjusting] = useState({})
  const [saleModal, setSaleModal] = useState(null) // null | 'create' | sale object

  const fetchSales = async () => {
    const [salesRes, dlqRes, cbRes] = await Promise.all([
      adminGetSales(),
      adminGetDLQ(),
      adminGetCircuitBreakers(),
    ])
    setSales(salesRes.data)
    setDlq(dlqRes.data)
    setCbs(cbRes.data.circuit_breakers || [])
  }

  const fetchUsers = async () => {
    const res = await adminGetUsers()
    setUsers(res.data)
  }

  const fetchAll = async () => {
    try {
      await Promise.all([fetchSales(), fetchUsers()])
    } catch (err) {
      toast.error('Admin API error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAll()
    const interval = setInterval(fetchAll, 10000)
    return () => clearInterval(interval)
  }, [])

  // ── Sale Actions ────────────────────────────────────────────────────────────
  const handleStatus = async (saleId, action) => {
    try {
      if (action === 'pause')    await adminPauseSale(saleId)
      if (action === 'resume')   await adminResumeSale(saleId)
      if (action === 'complete') await adminCompleteSale(saleId)
      if (action === 'activate') await adminActivateSale(saleId)
      toast.success(`Sale ${action}d`)
      await fetchSales()
    } catch (err) {
      const detail = err.response?.data?.detail || 'Action failed'
      toast.error(detail)

      // If end time passed, open edit modal so admin can fix dates
      if (action === 'activate' && detail.includes('end time')) {
        const sale = sales.find(s => s.id === saleId)
        if (sale) setSaleModal(sale)
      }
    }
  }

  const handleDeleteSale = async (sale) => {
    if (!window.confirm(`Delete "${sale.title}"? This cannot be undone.`)) return
    try {
      await adminDeleteSale(sale.id)
      toast.success('Sale deleted')
      await fetchSales()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Delete failed')
    }
  }

  const handleAdjust = async (saleId, delta) => {
    const reason = prompt(`Reason for ${delta > 0 ? 'adding' : 'removing'} ${Math.abs(delta)} units:`)
    if (!reason) return
    setAdjusting(a => ({ ...a, [saleId]: true }))
    try {
      await adminAdjustInventory(saleId, { adjustment: delta, reason })
      toast.success(`Inventory adjusted by ${delta > 0 ? '+' : ''}${delta}`)
      await fetchSales()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Adjustment failed')
    } finally {
      setAdjusting(a => ({ ...a, [saleId]: false }))
    }
  }

  // ── User Actions ────────────────────────────────────────────────────────────
  const handleUserAction = async (userId, action) => {
    try {
      if (action === 'deactivate') await adminDeactivateUser(userId)
      if (action === 'activate')   await adminActivateUser(userId)
      if (action === 'delete') {
        if (!window.confirm('Permanently delete this user and all their data?')) return
        await adminDeleteUser(userId)
      }
      toast.success(`User ${action}d`)
      await fetchUsers()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Action failed')
    }
  }

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
      Loading admin data...
    </div>
  )

  const TABS = [
    { key: 'sales', label: '⚡ Sales' },
    { key: 'users', label: '👥 Users' },
    { key: 'system', label: '🔧 System' },
  ]

  return (
    <div className="page">
      <div className="container">

        {/* Header */}
        <div style={{ marginBottom: 32, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <h1 style={{ fontSize: 64, marginBottom: 4 }}>ADMIN</h1>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="live-dot" />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)', textTransform: 'uppercase' }}>
                Polling every 10s
              </span>
            </div>
          </div>
          {tab === 'sales' && (
            <button className="btn btn-primary" onClick={() => setSaleModal('create')}>
              + Create Sale
            </button>
          )}
        </div>

        {/* Quick Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 32 }}>
          <div className="stat-box">
            <div className="stat-label">Active Sales</div>
            <div className="stat-value accent">{sales.filter(s => s.status === 'active').length}</div>
          </div>
          <div className="stat-box">
            <div className="stat-label">Total Users</div>
            <div className="stat-value">{users.length}</div>
          </div>
          <div className="stat-box">
            <div className="stat-label">Total Queued</div>
            <div className="stat-value">{sales.reduce((a, s) => a + (s.queue_depth || 0), 0)}</div>
          </div>
          <div className="stat-box">
            <div className="stat-label">DLQ</div>
            <div className={`stat-value ${dlq?.status === 'healthy' ? 'green' : 'hot'}`} style={{ fontSize: 28 }}>
              {dlq?.message_count ?? '—'}
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 24, borderBottom: '1px solid var(--border)', paddingBottom: 16 }}>
          {TABS.map(t => (
            <button
              key={t.key}
              className={`btn btn-sm ${tab === t.key ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Sales Tab ─────────────────────────────────────────────────────── */}
        {tab === 'sales' && (
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Sale</th>
                    <th>Status</th>
                    <th>Price</th>
                    <th>Inventory</th>
                    <th>Redis</th>
                    <th>Queue</th>
                    <th>Dates</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sales.map(sale => {
                    const available = sale.available_quantity ??
                      (sale.total_quantity - (sale.reserved_quantity || 0) - (sale.sold_quantity || 0))
                    const pct = Math.round((available / sale.total_quantity) * 100)

                    return (
                      <tr key={sale.id}>
                        <td>
                          <div style={{ fontWeight: 600, fontSize: 14 }}>{sale.title}</div>
                          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                            {sale.product_name}
                          </div>
                        </td>
                        <td>
                          <span className={`badge badge-${sale.status}`}>
                            {sale.status === 'active' && <span className="live-dot" style={{ width: 6, height: 6 }} />}
                            {sale.status}
                          </span>
                        </td>
                        <td>
                          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>
                            <span style={{ color: 'var(--accent)' }}>${Number(sale.sale_price).toFixed(2)}</span>
                          </div>
                          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', textDecoration: 'line-through' }}>
                            ${Number(sale.original_price).toFixed(2)}
                          </div>
                        </td>
                        <td>
                          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>
                            <span style={{ color: pct < 20 ? 'var(--accent-hot)' : pct < 50 ? 'var(--accent-gold)' : 'var(--accent-green)' }}>
                              {available}
                            </span>
                            <span style={{ color: 'var(--text-muted)' }}> / {sale.total_quantity}</span>
                          </div>
                          <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
                            <button className="btn btn-ghost btn-sm" style={{ fontSize: 10, padding: '2px 6px' }}
                              onClick={() => handleAdjust(sale.id, 10)} disabled={adjusting[sale.id]}>+10</button>
                            <button className="btn btn-ghost btn-sm" style={{ fontSize: 10, padding: '2px 6px' }}
                              onClick={() => handleAdjust(sale.id, -10)} disabled={adjusting[sale.id]}>-10</button>
                          </div>
                        </td>
                        <td>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: sale.redis_inventory != null ? 'var(--accent)' : 'var(--text-muted)' }}>
                            {sale.redis_inventory ?? 'N/A'}
                          </span>
                        </td>
                        <td>
                          <span style={{ fontFamily: 'var(--font-display)', fontSize: 24, color: sale.queue_depth > 0 ? 'var(--accent-gold)' : 'var(--text-muted)', lineHeight: 1 }}>
                            {sale.queue_depth}
                          </span>
                        </td>
                        <td>
                          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>
                            <div>Start: {format(new Date(sale.starts_at), 'MMM d HH:mm')}</div>
                            <div>End:   {format(new Date(sale.ends_at),   'MMM d HH:mm')}</div>
                          </div>
                        </td>
                        <td>
                          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                            <button className="btn btn-ghost btn-sm" onClick={() => setSaleModal(sale)}>Edit</button>
                            {sale.status === 'scheduled' && (
                              <button className="btn btn-outline btn-sm" onClick={() => handleStatus(sale.id, 'activate')}>Activate</button>
                            )}
                            {sale.status === 'active' && (
                              <button className="btn btn-ghost btn-sm" onClick={() => handleStatus(sale.id, 'pause')}>Pause</button>
                            )}
                            {sale.status === 'paused' && (
                              <button className="btn btn-outline btn-sm" onClick={() => handleStatus(sale.id, 'resume')}>Resume</button>
                            )}
                            {['active', 'paused'].includes(sale.status) && (
                              <button className="btn btn-danger btn-sm" onClick={() => handleStatus(sale.id, 'complete')}>End</button>
                            )}
                            {['scheduled', 'completed'].includes(sale.status) && (
                              <button className="btn btn-danger btn-sm" onClick={() => handleDeleteSale(sale)}>Delete</button>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── Users Tab ─────────────────────────────────────────────────────── */}
        {tab === 'users' && (
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Role</th>
                    <th>Orders</th>
                    <th>Reservations</th>
                    <th>Joined</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map(user => (
                    <tr key={user.id}>
                      <td>
                        <div style={{ fontWeight: 600, fontSize: 14 }}>{user.full_name}</div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                          {user.email}
                        </div>
                      </td>
                      <td>
                        {user.is_admin
                          ? <span className="badge badge-active">Admin</span>
                          : <span className="badge badge-completed">User</span>}
                      </td>
                      <td>
                        <span style={{ fontFamily: 'var(--font-display)', fontSize: 24, color: 'var(--accent)', lineHeight: 1 }}>
                          {user.order_count}
                        </span>
                      </td>
                      <td>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>
                          {user.reservation_count}
                        </span>
                      </td>
                      <td>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>
                          {format(new Date(user.created_at), 'MMM d, yyyy')}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${user.is_active ? 'badge-active' : 'badge-paused'}`}>
                          {user.is_active ? 'Active' : 'Suspended'}
                        </span>
                      </td>
                      <td>
                        {!user.is_admin && (
                          <div style={{ display: 'flex', gap: 4 }}>
                            {user.is_active
                              ? <button className="btn btn-ghost btn-sm" onClick={() => handleUserAction(user.id, 'deactivate')}>Suspend</button>
                              : <button className="btn btn-outline btn-sm" onClick={() => handleUserAction(user.id, 'activate')}>Restore</button>
                            }
                            <button className="btn btn-danger btn-sm" onClick={() => handleUserAction(user.id, 'delete')}>Delete</button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── System Tab ────────────────────────────────────────────────────── */}
        {tab === 'system' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
            {/* DLQ */}
            <div className="card">
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 24, marginBottom: 12 }}>DEAD LETTER QUEUE</div>
              <div className={`stat-value ${dlq?.status === 'healthy' ? 'green' : 'hot'}`} style={{ fontSize: 56, lineHeight: 1, marginBottom: 8 }}>
                {dlq?.message_count ?? '—'}
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: dlq?.status === 'healthy' ? 'var(--accent-green)' : 'var(--accent-hot)' }}>
                {dlq?.status ?? 'unknown'} · {dlq?.queue}
              </div>
            </div>

            {/* Circuit Breakers */}
            {cbs.map(cb => (
              <div key={cb.name} className="card">
                <div style={{ fontFamily: 'var(--font-display)', fontSize: 24, marginBottom: 12 }}>
                  {cb.name.toUpperCase().replace(/_/g, ' ')}
                </div>
                <div className={`stat-value ${cb.state === 'closed' ? 'green' : 'hot'}`} style={{ fontSize: 32, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', marginBottom: 8 }}>
                  {cb.state}
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>
                  failures: {cb.failure_count} / {cb.threshold}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Sale Form Modal */}
      {saleModal && (
        <SaleFormModal
          sale={saleModal === 'create' ? null : saleModal}
          onClose={() => setSaleModal(null)}
          onSave={async () => {
            setSaleModal(null)
            await fetchSales()
          }}
        />
      )}
    </div>
  )
}