import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { getOrders } from '../api/client'
import { Package, Zap, Clock, CheckCircle, User } from 'lucide-react'
import { format } from 'date-fns'

export default function Account() {
  const { user } = useAuth()
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getOrders()
      .then(({ data }) => setOrders(data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const totalSpent = orders.reduce((acc, o) => acc + Number(o.total_price), 0)

  return (
    <div className="page">
      <div className="container">

        {/* Profile Header */}
        <div style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '32px',
          marginBottom: 32,
          display: 'flex',
          alignItems: 'center',
          gap: 24,
          position: 'relative',
          overflow: 'hidden',
        }}>
          {/* Background glow */}
          <div style={{
            position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
            background: 'radial-gradient(ellipse 40% 80% at 0% 50%, var(--accent-dim), transparent)',
            pointerEvents: 'none',
          }} />

          {/* Avatar */}
          <div style={{
            width: 80, height: 80, borderRadius: '50%',
            background: 'var(--accent-dim)',
            border: '2px solid var(--accent)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'var(--font-display)',
            fontSize: 42,
            color: 'var(--accent)',
            flexShrink: 0,
            position: 'relative',
          }}>
            {(user?.full_name || user?.email || 'U')[0].toUpperCase()}
          </div>

          <div style={{ position: 'relative' }}>
            <h1 style={{ fontSize: 42, lineHeight: 1, marginBottom: 6 }}>
              {user?.full_name || 'User'}
            </h1>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-muted)', marginBottom: 12 }}>
              {user?.email}
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <span className="badge badge-active">Active Member</span>
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 11,
                color: 'var(--text-muted)',
                display: 'flex', alignItems: 'center', gap: 4,
              }}>
                <Clock size={11} />
                Member since {format(new Date(user?.created_at || Date.now()), 'MMM yyyy')}
              </span>
            </div>
          </div>
        </div>

        {/* Stats Row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 40 }}>
          <div className="stat-box">
            <div className="stat-label">Total Orders</div>
            <div className="stat-value accent">{orders.length}</div>
          </div>
          <div className="stat-box">
            <div className="stat-label">Total Spent</div>
            <div className="stat-value" style={{ fontSize: 28, color: 'var(--accent-green)' }}>
              ${totalSpent.toFixed(2)}
            </div>
          </div>
          <div className="stat-box">
            <div className="stat-label">Items Saved</div>
            <div className="stat-value" style={{ fontSize: 28, color: 'var(--accent-gold)' }}>
              ${orders.reduce((acc, o) => acc + (Number(o.unit_price) * 0.3 * Number(o.quantity)), 0).toFixed(2)}
            </div>
          </div>
        </div>

        {/* Quick Links */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginBottom: 40 }}>
          {[
            { icon: <Package size={20} />, label: 'My Orders',    sub: `${orders.length} orders`,  to: '/orders', color: 'var(--accent)' },
            { icon: <Zap size={20} />,     label: 'Flash Sales',  sub: 'View live sales',           to: '/sales',  color: 'var(--accent-hot)' },
            { icon: <User size={20} />,    label: 'Profile',      sub: 'Account settings',          to: '/account/profile', color: 'var(--accent-gold)' },
          ].map(({ icon, label, sub, to, color }) => (
            <Link key={to} to={to} style={{ textDecoration: 'none' }}>
              <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 14, cursor: 'pointer' }}>
                <div style={{
                  width: 44, height: 44, borderRadius: 4, flexShrink: 0,
                  background: `${color}18`,
                  border: `1px solid ${color}33`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color,
                }}>
                  {icon}
                </div>
                <div>
                  <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 2 }}>{label}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{sub}</div>
                </div>
              </div>
            </Link>
          ))}
        </div>

        {/* Recent Orders */}
        <div>
          <div className="section-header">
            <div>
              <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 36 }}>RECENT ORDERS</h2>
            </div>
            <Link to="/orders" className="btn btn-ghost btn-sm">View all →</Link>
          </div>

          {loading ? (
            <div style={{ textAlign: 'center', padding: 40, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              Loading...
            </div>
          ) : orders.length === 0 ? (
            <div className="card" style={{ textAlign: 'center', padding: '48px 24px' }}>
              <div style={{ fontSize: 40, marginBottom: 16 }}>📦</div>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, color: 'var(--text-secondary)', marginBottom: 12 }}>
                No orders yet
              </div>
              <p style={{ color: 'var(--text-muted)', marginBottom: 20 }}>
                Grab something from the flash sales before it's gone.
              </p>
              <Link to="/sales" className="btn btn-primary">⚡ View Flash Sales</Link>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {orders.slice(0, 5).map(order => (
                <div key={order.id} className="card" style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div style={{
                      width: 36, height: 36, borderRadius: 4,
                      background: 'var(--accent-dim)',
                      border: '1px solid var(--border-glow)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <CheckCircle size={16} color="var(--accent-green)" />
                    </div>
                    <div>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>
                        ORDER · {order.id.slice(0, 8).toUpperCase()}
                      </div>
                      <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                        Qty: {order.quantity} × ${Number(order.unit_price).toFixed(2)}
                      </div>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontFamily: 'var(--font-display)', fontSize: 24, color: 'var(--accent)', lineHeight: 1, marginBottom: 2 }}>
                      ${Number(order.total_price).toFixed(2)}
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                      {format(new Date(order.created_at), 'MMM d, yyyy')}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  )
}