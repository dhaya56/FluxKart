import { Link } from 'react-router-dom'
import CountdownTimer from './CountdownTimer'
import InventoryBar from './InventoryBar'

export default function SaleCard({ sale }) {
  const now = new Date()
  const isEnded      = sale.status === 'completed'
  const isLive       = sale.status === 'active' && new Date(sale.ends_at) > new Date()
  const isActivating = sale.status === 'scheduled' && new Date(sale.starts_at) <= new Date()
  const isScheduled  = sale.status === 'scheduled' && new Date(sale.starts_at) > new Date()
  const isPaused     = sale.status === 'paused'

  const discount  = Math.round((1 - sale.sale_price / sale.original_price) * 100)
  const available = sale.available_quantity ??
    (sale.total_quantity - (sale.reserved_quantity || 0) - (sale.sold_quantity || 0))

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <span className={`badge ${isEnded ? 'badge-completed' : isLive ? 'badge-active' : 'badge-scheduled'}`}>
          {isLive && <span className="live-dot" style={{ width: 6, height: 6 }} />}
          {isEnded ? 'Ended' : isLive ? 'Live' : isPaused ? 'Paused' : 'Upcoming'}
        </span>
        <span style={{
          background: 'var(--accent-hot)', color: '#fff',
          fontFamily: 'var(--font-display)', fontSize: 20,
          padding: '2px 10px', borderRadius: 2,
        }}>
          -{discount}%
        </span>
      </div>

      {/* Product info */}
      <div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 4 }}>
          {sale.product_name}
        </div>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 26, lineHeight: 1.1, marginBottom: 8 }}>
          {sale.title}
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <span style={{ fontFamily: 'var(--font-display)', fontSize: 32, color: 'var(--accent)' }}>
            ${Number(sale.sale_price).toFixed(2)}
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-muted)', textDecoration: 'line-through' }}>
            ${Number(sale.original_price).toFixed(2)}
          </span>
        </div>
      </div>

      {/* Inventory — only show for live sales */}
      {isLive && (
        <InventoryBar
          total={sale.total_quantity}
          available={available}
          reserved={sale.reserved_quantity || 0}
        />
      )}

      {/* Timer */}
      {isLive && (
        <CountdownTimer targetDate={sale.ends_at} label="Ends in" size="sm" />
      )}
      {isScheduled && (
        <CountdownTimer targetDate={sale.starts_at} label="Starts in" size="sm" />
      )}

      {/* CTA */}
      {isEnded ? (
        <Link to={`/sales/${sale.id}`} className="btn btn-ghost btn-full" disabled style={{ marginTop: 'auto', pointerEvents: 'none', opacity: 0.4 }}>
          View Sale
        </Link>
      ) : isLive ? (
        <Link to={`/sales/${sale.id}`} className="btn btn-primary btn-full" style={{ marginTop: 'auto' }}>
          ⚡ Reserve Now
        </Link>
      ) : isActivating ? (
        <button className="btn btn-ghost btn-full" disabled style={{ marginTop: 'auto', color: 'var(--accent-gold)' }}>
          ⏳ Sale Starting...
        </button>
      ) : isPaused ? (
        <button className="btn btn-ghost btn-full" disabled style={{ marginTop: 'auto', color: 'var(--accent-gold)' }}>
          ⏸ Temporarily Unavailable
        </button>
      ) : (
        <Link to={`/sales/${sale.id}`} className="btn btn-outline btn-full" style={{ marginTop: 'auto' }}>
          🔔 Pre-Register
        </Link>
      )}
    </div>
  )
}