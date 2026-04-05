import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getOrders } from '../api/client'
import { format } from 'date-fns'

const STATUS_STYLES = {
  paid:      { color: 'var(--accent-green)',  label: 'Paid',      badge: 'badge-active' },
  confirmed: { color: 'var(--accent)',        label: 'Confirmed', badge: 'badge-active' },
  pending:   { color: 'var(--accent-gold)',   label: 'Pending',   badge: 'badge-scheduled' },
  failed:    { color: 'var(--accent-hot)',    label: 'Failed',    badge: 'badge-completed' },
  refunded:  { color: 'var(--text-muted)',    label: 'Refunded',  badge: 'badge-completed' },
}

export default function Orders() {
  const [orders, setOrders]   = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter]   = useState('all')
  const navigate = useNavigate()

  useEffect(() => {
    getOrders()
      .then(({ data }) => setOrders(data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const filtered = filter === 'all'
    ? orders
    : orders.filter(o => o.status === filter)

  const tabs = [
    { key: 'all',    label: 'All Orders' },
    { key: 'paid',   label: '✅ Paid' },
    { key: 'failed', label: 'Cancelled' },
  ]

  return (
    <div className="page">
      <div className="container">

        {/* Header */}
        <div style={{ marginBottom: 32, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <h1 style={{ fontSize: 64, marginBottom: 8 }}>MY ORDERS</h1>
            <p style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
              {orders.length} total orders
            </p>
          </div>
          <button className="btn btn-outline" onClick={() => navigate('/cart')}>
            🛒 View Cart
          </button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 28, flexWrap: 'wrap' }}>
          {tabs.map(t => (
            <button
              key={t.key}
              className={`btn btn-sm ${filter === t.key ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setFilter(t.key)}
            >
              {t.label}
              <span style={{ background: 'var(--bg-elevated)', borderRadius: 10, padding: '1px 6px', fontSize: 10, fontFamily: 'var(--font-mono)', marginLeft: 4 }}>
                {t.key === 'all' ? orders.length : orders.filter(o => o.status === t.key).length}
              </span>
            </button>
          ))}
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 80, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            Loading...
          </div>
        ) : filtered.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">📦</div>
            <div className="empty-state-title">No orders yet</div>
            <p style={{ marginBottom: 20 }}>Reserve a flash sale item to see your orders here.</p>
            <button className="btn btn-primary" onClick={() => navigate('/sales')}>
              Browse Flash Sales
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {filtered.map(order => {
              const style = STATUS_STYLES[order.status] || STATUS_STYLES.pending

              return (
                <div key={order.id} className="card" style={{ padding: '20px 24px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>

                    {/* Order ID */}
                    <div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>
                        ORDER ID
                      </div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--accent)' }}>
                        {order.id.slice(0, 8)}...
                      </div>
                    </div>

                    {/* Quantity */}
                    <div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>QTY</div>
                      <div style={{ fontFamily: 'var(--font-display)', fontSize: 24, lineHeight: 1 }}>{order.quantity}</div>
                    </div>

                    {/* Unit price */}
                    <div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>UNIT PRICE</div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14 }}>${Number(order.unit_price).toFixed(2)}</div>
                    </div>

                    {/* Total */}
                    <div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>TOTAL</div>
                      <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, color: 'var(--accent)', lineHeight: 1 }}>
                        ${Number(order.total_price).toFixed(2)}
                      </div>
                    </div>

                    {/* Date */}
                    <div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>DATE</div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                        {format(new Date(order.created_at), 'MMM d, yyyy HH:mm')}
                      </div>
                    </div>

                    {/* Status */}
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8 }}>
                      <span className={`badge ${style.badge}`} style={{ color: style.color }}>
                        {style.label}
                      </span>
                      {order.status === 'confirmed' && (
                        <button
                          className="btn btn-primary btn-sm"
                          onClick={() => navigate('/cart')}
                          style={{ fontSize: 11 }}
                        >
                          💳 Complete Payment
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}