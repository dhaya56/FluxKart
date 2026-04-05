import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getSales } from '../api/client'
import SaleCard from '../components/SaleCard'
import { Zap, Shield, Clock, TrendingDown } from 'lucide-react'

const TICKER_ITEMS = [
  '⚡ Flash Sale Engine', 'Zero Overselling', 'Behavioral Scoring',
  'Staggered Admission', 'Recovery Windows', 'Circuit Breaker Protection',
  '10,000 Concurrent Users', 'p95 < 150ms', 'Atomic Inventory',
  '⚡ Flash Sale Engine', 'Zero Overselling', 'Behavioral Scoring',
  'Staggered Admission', 'Recovery Windows', 'Circuit Breaker Protection',
  '10,000 Concurrent Users', 'p95 < 150ms', 'Atomic Inventory',
]

const FEATURES = [
  {
    icon: <Zap size={20} />,
    title: 'Atomic Reservations',
    desc: 'Redis Lua scripts guarantee zero overselling under any concurrency level.',
  },
  {
    icon: <Shield size={20} />,
    title: 'Bot Defense',
    desc: 'Behavioral scoring dynamically shrinks TTL for suspicious users.',
  },
  {
    icon: <Clock size={20} />,
    title: 'Staggered Admission',
    desc: 'Pre-registered users admitted in FIFO batches — no thundering herd.',
  },
  {
    icon: <TrendingDown size={20} />,
    title: 'Graceful Degradation',
    desc: 'Redis down? Automatic fallback to PostgreSQL pessimistic locking.',
  },
]

export default function Landing() {
  const [sales, setSales] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getSales()
      .then(({ data }) => setSales(data.slice(0, 3)))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      {/* Ticker */}
      <div className="ticker-wrap">
        <div className="ticker-content">
          {TICKER_ITEMS.map((item, i) => (
            <span key={i} className="ticker-item">{item}</span>
          ))}
        </div>
      </div>

      {/* Hero */}
      <section style={{
        minHeight: '85vh',
        display: 'flex',
        alignItems: 'center',
        position: 'relative',
        overflow: 'hidden',
      }}>
        {/* Background grid */}
        <div style={{
          position: 'absolute', inset: 0,
          backgroundImage: `
            linear-gradient(var(--border) 1px, transparent 1px),
            linear-gradient(90deg, var(--border) 1px, transparent 1px)
          `,
          backgroundSize: '60px 60px',
          opacity: 0.3,
          maskImage: 'radial-gradient(ellipse 80% 80% at 50% 50%, black, transparent)',
        }} />

        {/* Glow orb */}
        <div style={{
          position: 'absolute',
          top: '20%', left: '60%',
          width: 600, height: 600,
          background: 'radial-gradient(circle, #00E5FF08, transparent 70%)',
          borderRadius: '50%',
          transform: 'translate(-50%, -50%)',
          pointerEvents: 'none',
        }} />

        <div className="container" style={{ position: 'relative', zIndex: 1 }}>
          <div style={{ maxWidth: 720 }}>
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              background: 'var(--accent-dim)',
              border: '1px solid var(--border-glow)',
              borderRadius: 20,
              padding: '4px 14px',
              marginBottom: 24,
            }}>
              <span className="live-dot" />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
                Live Flash Sales
              </span>
            </div>

            <h1 style={{ fontSize: 'clamp(56px, 10vw, 120px)', lineHeight: 0.9, marginBottom: 24 }}>
              FLASH<br />
              <span style={{ color: 'var(--accent)', WebkitTextStroke: '1px var(--accent)' }}>SALES</span><br />
              ENGINE
            </h1>

            <p style={{ fontSize: 18, color: 'var(--text-secondary)', maxWidth: 480, marginBottom: 40, lineHeight: 1.6 }}>
              Distributed inventory reservation system. Zero overselling. 
              10,000 concurrent users. Behavioral scoring. Staggered admission.
            </p>

            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <Link to="/sales" className="btn btn-primary btn-lg">
                ⚡ View Live Sales
              </Link>
              <Link to="/register" className="btn btn-outline btn-lg">
                Create Account
              </Link>
            </div>

            {/* Stats */}
            <div style={{ display: 'flex', gap: 32, marginTop: 56, flexWrap: 'wrap' }}>
              {[
                { value: '10K', label: 'Concurrent Users' },
                { value: '<150ms', label: 'p95 Latency' },
                { value: '0', label: 'Oversells' },
                { value: '99.9%', label: 'Uptime' },
              ].map(({ value, label }) => (
                <div key={label}>
                  <div style={{ fontFamily: 'var(--font-display)', fontSize: 36, color: 'var(--accent)', lineHeight: 1 }}>{value}</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginTop: 4 }}>{label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section style={{ padding: '80px 0', borderTop: '1px solid var(--border)' }}>
        <div className="container">
          <div style={{ marginBottom: 48, textAlign: 'center' }}>
            <h2 style={{ fontSize: 56, marginBottom: 12 }}>BUILT DIFFERENT</h2>
            <p style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
              Production-grade architecture solving real flash sale problems
            </p>
          </div>
          <div className="grid-2">
            {FEATURES.map((f) => (
              <div key={f.title} className="card" style={{ display: 'flex', gap: 16 }}>
                <div style={{
                  width: 40, height: 40, flexShrink: 0,
                  background: 'var(--accent-dim)',
                  border: '1px solid var(--border-glow)',
                  borderRadius: 4,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: 'var(--accent)',
                }}>
                  {f.icon}
                </div>
                <div>
                  <div style={{ fontWeight: 700, marginBottom: 6 }}>{f.title}</div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: 14 }}>{f.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Live Sales Preview */}
      {!loading && sales.length > 0 && (
        <section style={{ padding: '80px 0', borderTop: '1px solid var(--border)' }}>
          <div className="container">
            <div className="section-header">
              <div>
                <h2 className="section-title">LIVE NOW</h2>
                <div className="section-subtitle">Active flash sales — limited stock</div>
              </div>
              <Link to="/sales" className="btn btn-ghost">View all →</Link>
            </div>
            <div className="grid-3">
              {sales.map(s => <SaleCard key={s.id} sale={s} />)}
            </div>
          </div>
        </section>
      )}

      {/* Footer */}
      <footer style={{
        borderTop: '1px solid var(--border)',
        padding: '32px 24px',
        textAlign: 'center',
        color: 'var(--text-muted)',
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
      }}>
        FLUXKART — Flash Sale Engine ·{' '}
        <span style={{ color: 'var(--accent)' }}>Built for scale</span>
      </footer>
    </div>
  )
}