import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  getSale, preregister, getAdmissionStatus,
  createReservation, getQueueStatus,
} from '../api/client'
import { useAuth } from '../context/AuthContext'
import CountdownTimer from '../components/CountdownTimer'
import InventoryBar from '../components/InventoryBar'
import WaitingRoom from '../components/WaitingRoom'

const IDEMPOTENCY_KEY = () => `res-${Date.now()}-${Math.random().toString(36).slice(2)}`

export default function SaleDetail() {
  const { id } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [sale, setSale]           = useState(null)
  const [loading, setLoading]     = useState(true)
  const [quantity, setQuantity]   = useState(1)
  const [reserving, setReserving] = useState(false)
  const [reservation, setReservation] = useState(null)

  // Queue / admission state
  const [queuePosition, setQueuePosition] = useState(null)  // number = in queue
  const [admitted, setAdmitted]           = useState(false)
  const [admissionSeconds, setAdmissionSeconds] = useState(0)
  const [preregistered, setPreregistered] = useState(false)
  const [preregistering, setPreregistering] = useState(false)
  const [soldOut, setSoldOut]             = useState(false)
  const [admissionCountdown, setAdmissionCountdown] = useState(0)
  const [queueDepth, setQueueDepth] = useState(0)

  // ── Fetch sale ──────────────────────────────────────────────────────────────
  const fetchSale = useCallback(async () => {
    try {
      const { data } = await getSale(id)
      setSale(data)
    } catch (err) {
      // Only redirect on actual 404 — ignore transient network errors
      if (err.response?.status === 404) {
        toast.error('Sale not found')
        navigate('/sales')
      }
      // Any other error (500, timeout) — silently ignore, keep showing current data
    } finally {
      setLoading(false)
    }
  }, [id, navigate])

  useEffect(() => {
    fetchSale()
    const interval = setInterval(fetchSale, sale?.status === 'scheduled' ? 2000 : 5000)
    return () => clearInterval(interval)
  }, [fetchSale, sale?.status])

  // ── Poll admission status when pre-registered ───────────────────────────────
  useEffect(() => {
    if (!preregistered || admitted || !user) return
    const poll = setInterval(async () => {
      try {
        const { data } = await getAdmissionStatus(id)
        if (data.admitted) {
          setAdmitted(true)
          setAdmissionSeconds(data.seconds_remaining)
          toast.success('🎉 You are admitted! Reserve now!', { duration: 5000 })
          clearInterval(poll)
        }
      } catch {}
    }, 2000)
    return () => clearInterval(poll)
  }, [preregistered, admitted, id, user])

  // ── Handlers ────────────────────────────────────────────────────────────────
  const handlePreregister = async () => {
    if (!user) { navigate('/login', { state: { from: location.pathname } }); return }
    setPreregistering(true)
    try {
      await preregister(id)
      setPreregistered(true)
      toast.success('Pre-registered! You will be admitted when the sale starts.')
    } catch (err) {
      if (err.response?.data?.detail?.includes('Already')) {
        setPreregistered(true)
        toast('Already pre-registered', { icon: 'ℹ️' })
      } else {
        toast.error(err.response?.data?.detail || 'Failed to pre-register')
      }
    } finally {
      setPreregistering(false)
    }
  }

  const handleReserve = async () => {
    if (!user) { navigate('/login', { state: { from: location.pathname } }); return }
    setReserving(true)
    try {
      const { data, status } = await createReservation({
        sale_id:         id,
        quantity,
        idempotency_key: IDEMPOTENCY_KEY(),
      })

      if (status === 202) {
        setQueuePosition(data.position)
        setQueueDepth(data.queue_depth)
        toast(`Entered queue — position #${data.position}`, { icon: '⏳', duration: 4000 })
      } else if (data.status === 'pending') {
        setReservation(data)
        toast.success(`Reserved! Redirecting to your orders in 5 seconds...`)
        setTimeout(() => navigate('/orders'), 5000)
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Reservation failed')
    } finally {
      setReserving(false)
    }
  }

  // ── WaitingRoom callbacks ───────────────────────────────────────────────────
  const handleAdmitted = () => {
    setAdmitted(true)
    setAdmissionCountdown(30)
    setQueuePosition(null)
    toast.success('🎉 Your turn! You have 30 seconds to reserve.', { duration: 6000 })
  }

  // Admission window countdown — 30s to complete reservation
  useEffect(() => {
    if (!admitted || admissionCountdown <= 0) return
    const t = setInterval(() => {
      setAdmissionCountdown(s => {
        if (s <= 1) {
          clearInterval(t)
          setAdmitted(false)
          setAdmissionCountdown(0)
          toast.error('Time up! You have been returned to the queue.')
          return 0
        }
        return s - 1
      })
    }, 1000)
    return () => clearInterval(t)
  }, [admitted])

  const handleSoldOut = () => {
    setSoldOut(true)
    setQueuePosition(null)
    toast.error('All units were claimed before your turn.', { duration: 6000 })
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
        Loading...
      </div>
    )
  }

  if (!sale) return null

  const available = sale.available_quantity ??
    (sale.total_quantity - (sale.reserved_quantity || 0) - (sale.sold_quantity || 0))
  const discount = Math.round((1 - sale.sale_price / sale.original_price) * 100)

  return (
    <div className="page">
      <div className="container">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 380px', gap: 32, alignItems: 'start' }}>

          {/* Left — sale info */}
          <div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 16 }}>
              <span className={`badge badge-${sale.status}`}>
                {sale.status === 'active' && <span className="live-dot" style={{ width: 6, height: 6 }} />}
                {sale.status === 'active' ? 'Live' :
                 sale.status === 'scheduled' ? 'Upcoming' :
                 sale.status === 'completed' ? 'Ended' : sale.status}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                {sale.product_name}
              </span>
            </div>

            <h1 style={{ fontSize: 'clamp(36px, 5vw, 72px)', marginBottom: 24, lineHeight: 1 }}>
              {sale.title}
            </h1>

            {/* Price */}
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 32 }}>
              <span style={{ fontFamily: 'var(--font-display)', fontSize: 64, color: 'var(--accent)', lineHeight: 1 }}>
                ${Number(sale.sale_price).toFixed(2)}
              </span>
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14, color: 'var(--text-muted)', textDecoration: 'line-through' }}>
                  ${Number(sale.original_price).toFixed(2)}
                </div>
                <div style={{ background: 'var(--accent-hot)', color: '#fff', fontFamily: 'var(--font-display)', fontSize: 20, padding: '1px 8px', borderRadius: 2, marginTop: 2 }}>
                  SAVE {discount}%
                </div>
              </div>
            </div>

            <div style={{ marginBottom: 32 }}>
              <InventoryBar total={sale.total_quantity} available={available} reserved={sale.reserved_quantity || 0} />
            </div>

            <div style={{ marginBottom: 32 }}>
              {sale.status === 'active' && new Date(sale.ends_at) > new Date() &&
                <CountdownTimer targetDate={sale.ends_at} label="Sale ends in" size="lg" />}
              {sale.status === 'scheduled' && new Date(sale.starts_at) > new Date() &&
                <CountdownTimer targetDate={sale.starts_at} label="Sale starts in" size="lg" />}
            </div>
          </div>

          {/* Right — action panel */}
          <div style={{ position: 'sticky', top: 80 }}>
            <div className="card" style={{ padding: 28 }}>

              {/* ── State 1: Reserved ── */}
              {reservation && (
                <div style={{ textAlign: 'center', padding: '20px 0' }}>
                  <div style={{ fontSize: 48, marginBottom: 12 }}>✅</div>
                  <div style={{ fontFamily: 'var(--font-display)', fontSize: 32, color: 'var(--accent-green)', marginBottom: 8 }}>Reserved!</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)', marginBottom: 16 }}>
                    {reservation.quantity} × {sale.product_name}
                  </div>
                  <div style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 4, padding: 12, marginBottom: 16 }}>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>RESERVATION ID</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)', wordBreak: 'break-all' }}>{reservation.id}</div>
                  </div>
                  <CountdownTimer targetDate={reservation.expires_at} label="Expires in" size="sm" />
                </div>
              )}

              {/* ── State 2: In Queue → WaitingRoom ── */}
              {!reservation && queuePosition && !admitted && (
                <WaitingRoom
                  saleId={id}
                  initialPosition={queuePosition}
                  initialQueueDepth={queueDepth}
                  totalInventory={sale.total_quantity}
                  onAdmitted={handleAdmitted}
                  onSoldOut={handleSoldOut}
                />
              )}

              {/* ── State 3: Admitted — reserve now ── */}
              {!reservation && admitted && (
                <div>
                  <div style={{
                    background: '#00FF8710',
                    border: '1px solid #00FF8733',
                    borderRadius: 4,
                    padding: '10px 14px',
                    marginBottom: 20,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                  }}>
                    <span className="live-dot" />
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--accent-green)', fontWeight: 600 }}>
                      {admissionCountdown > 0 ? `Your turn — ${admissionCountdown}s remaining` : "Reserve now!"}
                    </span>
                  </div>
                  {renderReserveForm()}
                </div>
              )}

              {/* ── State 4: Pre-registered, waiting for sale to start ── */}
              {!reservation && !queuePosition && !admitted && preregistered && sale.status === 'scheduled' && new Date(sale.starts_at) > new Date() && (
                <div style={{ textAlign: 'center', padding: '20px 0' }}>
                  <div style={{ fontSize: 40, marginBottom: 12 }}>🔔</div>
                  <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, marginBottom: 8 }}>Pre-Registered</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)', marginBottom: 16 }}>
                    You will be admitted when the sale starts.
                  </div>
                  <CountdownTimer targetDate={sale.starts_at} label="Sale starts in" size="sm" />
                </div>
              )}

              {/* ── State 4.5: Gap — starts_at passed but not yet active ── */}
              {!reservation && !queuePosition && !admitted && sale.status === 'scheduled' && new Date(sale.starts_at) <= new Date() && (
                <div style={{ textAlign: 'center', padding: '20px 0' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginBottom: 16 }}>
                    <span className="live-dot" style={{ background: 'var(--accent-gold)' }} />
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--accent-gold)', textTransform: 'uppercase' }}>
                      Sale Starting...
                    </span>
                  </div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>
                    Please wait a moment
                  </div>
                </div>
              )}

              {/* ── State 5: Normal flow ── */}
              {!reservation && !queuePosition && !admitted && 
               !(preregistered && sale.status !== 'active') && 
               !(sale.status === 'scheduled' && new Date(sale.starts_at) <= new Date()) &&
               !soldOut && renderNormalFlow()
              }

              {/* ── State 6: Sold out while in queue ── */}
              {soldOut && !reservation && (
                <div style={{ textAlign: 'center', padding: '20px 0' }}>
                  <div style={{ fontSize: 48, marginBottom: 12 }}>😔</div>
                  <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, color: 'var(--accent-hot)', marginBottom: 8 }}>Sold Out</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>
                    All units were claimed before your turn.
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )

  // ── Reserve Form ────────────────────────────────────────────────────────────
  function renderReserveForm() {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div className="form-group">
          <label className="form-label">Quantity</label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button className="btn btn-ghost btn-sm" onClick={() => setQuantity(q => Math.max(1, q - 1))}>−</button>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: 36, color: 'var(--accent)', minWidth: 40, textAlign: 'center', lineHeight: 1 }}>{quantity}</span>
            <button className="btn btn-ghost btn-sm" onClick={() => setQuantity(q => Math.min(10, q + 1))}>+</button>
          </div>
        </div>

        <div style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 4, padding: '12px 16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Unit price</span>
            <span style={{ fontFamily: 'var(--font-mono)' }}>${Number(sale.sale_price).toFixed(2)}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontWeight: 700 }}>Total</span>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: 24, color: 'var(--accent)', lineHeight: 1 }}>
              ${(Number(sale.sale_price) * quantity).toFixed(2)}
            </span>
          </div>
        </div>

        <button
          className="btn btn-primary btn-full btn-lg animate-pulse-glow"
          onClick={handleReserve}
          disabled={reserving || available === 0}
          style={{ fontSize: 18 }}
        >
          {reserving ? 'Reserving...' : available === 0 ? 'Sold Out' : '⚡ Reserve Now'}
        </button>
      </div>
    )
  }

  // ── Normal Flow ─────────────────────────────────────────────────────────────
  function renderNormalFlow() {
    if (!user) {
      return (
        <div style={{ textAlign: 'center' }}>
          <div style={{
            background: 'var(--accent-dim)',
            border: '1px solid var(--border-glow)',
            borderRadius: 4,
            padding: '20px 16px',
            marginBottom: 16,
          }}>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 26, marginBottom: 8 }}>Login to Reserve</div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 20, lineHeight: 1.6 }}>
              Create a free account to participate in flash sales and secure your item.
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button className="btn btn-primary btn-full btn-lg" onClick={() => navigate('/login', { state: { from: location.pathname } })}>
                → Sign In
              </button>
              <button className="btn btn-outline btn-full" onClick={() => navigate('/register', { state: { from: location.pathname } })}>
                Create Account
              </button>
            </div>
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
            Free to join · No credit card required
          </div>
        </div>
      )
    }

    if (sale.status === 'active') return renderReserveForm()

    if (sale.status === 'scheduled') {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <CountdownTimer targetDate={sale.starts_at} label="Sale starts in" size="md" />
          <button className="btn btn-outline btn-full" onClick={handlePreregister} disabled={preregistering}>
            {preregistering ? 'Registering...' : '🔔 Pre-Register for Early Access'}
          </button>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', textAlign: 'center', fontFamily: 'var(--font-mono)' }}>
            Pre-registered users are admitted first in FIFO order
          </div>
        </div>
      )
    }

    return (
      <div className="empty-state" style={{ padding: 20 }}>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 24, color: 'var(--text-muted)' }}>
          {sale.status === 'completed' ? 'Sale Ended' : 'Sale Paused'}
        </div>
      </div>
    )
  }
}