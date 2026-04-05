import { useEffect, useState } from 'react'
import { getSales } from '../api/client'
import SaleCard from '../components/SaleCard'

export default function Sales() {
  const [sales, setSales] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')

  const fetchSales = async () => {
    try {
      const { data } = await getSales()
      setSales(data)
    } catch {}
    setLoading(false)
  }

  useEffect(() => {
    fetchSales()
    const hasScheduled = sales.some(s => s.status === 'scheduled')
    const interval = setInterval(fetchSales, hasScheduled ? 2000 : 5000)
    return () => clearInterval(interval)
  }, [sales.some(s => s.status === 'scheduled')])

  const now = new Date()
  const isLive      = (s) => s.status === 'active' && new Date(s.ends_at) > now
  const isActivating = (s) => s.status === 'scheduled' && new Date(s.starts_at) <= new Date()
  const isUpcoming  = (s) => s.status === 'scheduled' && new Date(s.starts_at) > new Date()
  const isEnded     = (s) => s.status === 'completed'

  const counts = {
    all:       sales.length,
    active:    sales.filter(isLive).length,
    scheduled: sales.filter(s => isUpcoming(s) || isActivating(s)).length,
    completed: sales.filter(isEnded).length,
  }

  const filtered = (() => {
    let result
    if (filter === 'active')    result = sales.filter(isLive)
    else if (filter === 'scheduled') result = sales.filter(isUpcoming)
    else if (filter === 'completed') result = sales.filter(isEnded)
    else {
      // All tab — live first, then upcoming, then ended at bottom
      const live       = sales.filter(isLive)
      const activating = sales.filter(isActivating)
      const upcoming   = sales.filter(isUpcoming)
      const ended      = sales.filter(isEnded)
      result = [...live, ...activating, ...upcoming, ...ended]
    }
    return result
  })()

  const TABS = [
    { key: 'all',       label: 'All' },
    { key: 'active',    label: '⚡ Live' },
    { key: 'scheduled', label: '🔔 Upcoming' },
    { key: 'completed', label: 'Ended' },
  ]

  return (
    <div className="page">
      <div className="container">
        {/* Header */}
        <div style={{ marginBottom: 40 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
            <h1 style={{ fontSize: 64 }}>FLASH SALES</h1>
            {counts.active > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                <span className="live-dot" />
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)', textTransform: 'uppercase' }}>
                  Live
                </span>
              </div>
            )}
          </div>
          <p style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
            Inventory updates every 5 seconds · {counts.active} live now · {counts.scheduled} upcoming
          </p>
        </div>

        {/* Filter Tabs */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 32, flexWrap: 'wrap' }}>
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              className={`btn btn-sm ${filter === key ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setFilter(key)}
            >
              {label}
              <span style={{
                background: filter === key ? 'rgba(0,0,0,0.2)' : 'var(--bg-elevated)',
                borderRadius: 10,
                padding: '1px 6px',
                fontSize: 10,
                fontFamily: 'var(--font-mono)',
              }}>
                {counts[key]}
              </span>
            </button>
          ))}
        </div>

        {/* Divider between live/upcoming and ended in All tab */}
        {loading ? (
          <div style={{ textAlign: 'center', padding: 80, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            Loading sales...
          </div>
        ) : filtered.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">⚡</div>
            <div className="empty-state-title">
              {filter === 'active'    ? 'No live sales right now' :
               filter === 'scheduled' ? 'No upcoming sales' :
               filter === 'completed' ? 'No completed sales' :
               'No sales found'}
            </div>
            <p>Check back soon.</p>
          </div>
        ) : (
          <>
            <div className="grid-3">
              {filter === 'all' ? (
                <>
                  {/* Live + upcoming */}
                  {filtered.filter(s => !isEnded(s)).map(s => <SaleCard key={s.id} sale={s} />)}
                </>
              ) : (
                filtered.map(s => <SaleCard key={s.id} sale={s} />)
              )}
            </div>

            {/* Ended section — only in All tab */}
            {filter === 'all' && filtered.filter(isEnded).length > 0 && (
              <>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 16,
                  margin: '48px 0 24px',
                }}>
                  <hr style={{ flex: 1, border: 'none', borderTop: '1px solid var(--border)' }} />
                  <span style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11,
                    color: 'var(--text-muted)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.1em',
                    whiteSpace: 'nowrap',
                  }}>
                    Ended Sales
                  </span>
                  <hr style={{ flex: 1, border: 'none', borderTop: '1px solid var(--border)' }} />
                </div>
                <div className="grid-3" style={{ opacity: 0.5 }}>
                  {filtered.filter(isEnded).map(s => <SaleCard key={s.id} sale={s} />)}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}