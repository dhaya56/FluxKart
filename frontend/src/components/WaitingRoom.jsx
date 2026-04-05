/**
 * WaitingRoom — IPL/BookMyShow style virtual waiting room.
 *
 * EWT Calculation:
 *   - Admission rate: 50 users per 100ms = 500 users/second
 *   - Each admitted user gets 30s window (matches queue_service.py ex=30)
 *   - EWT = (position / admission_rate) + (position * 0.6 * 30s / batch_size)
 *   - Recalculates on every SSE update as position drops
 *   - Counts down every second between updates
 *
 * Chance of Getting Item:
 *   - High   → position <= inventory
 *   - Medium → position <= inventory * 1.5
 *   - Low    → position > inventory * 1.5
 */

import { useEffect, useRef, useState } from 'react'

const ADMIT_BATCH_SIZE   = 50     // users admitted per batch
const ADMIT_INTERVAL_MS  = 100   // ms between batches
const ADMISSION_WINDOW_S = 30    // seconds each user gets after admission
const ADMISSION_RATE     = ADMIT_BATCH_SIZE / (ADMIT_INTERVAL_MS / 1000) // 500/sec

const calculateEWT = (pos) => {
  if (!pos || pos <= 0) return 0
  const admitWaitS    = pos / ADMISSION_RATE
  const windowBufferS = pos * (ADMISSION_WINDOW_S * 0.6) / ADMIT_BATCH_SIZE
  return Math.ceil(admitWaitS + windowBufferS)
}

export default function WaitingRoom({
  saleId,
  initialPosition,
  initialQueueDepth,
  totalInventory,
  onAdmitted,
  onSoldOut,
}) {
  const [state, setState]         = useState('connecting')
  const [position, setPosition]   = useState(initialPosition || null)
  const [totalQueue, setTotalQueue] = useState(initialQueueDepth || 0)
  const [inventory, setInventory]   = useState(totalInventory || 0)
  const [ewtSeconds, setEwtSeconds] = useState(() => calculateEWT(initialPosition))
  const eventSourceRef = useRef(null)
  const ewtTimerRef    = useRef(null)

  // ── SSE Connection ──────────────────────────────────────────────────────────
  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (!token) return

    const url = `/api/reservations/queue-stream?sale_id=${saleId}&token=${token}`
    const es  = new EventSource(url)
    eventSourceRef.current = es

    es.onopen = () => setState('waiting')

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        if (data.sold_out || data.inventory <= 0) {
          setState('sold_out')
          es.close()
          onSoldOut?.()
          return
        }

        if (data.admitted) {
          setState('admitted')
          es.close()
          onAdmitted?.()
          return
        }

        // Only update if values are valid — never overwrite with null
        if (data.position != null)       setPosition(data.position)
        if (data.total_in_queue != null) setTotalQueue(data.total_in_queue)
        if (data.inventory != null)      setInventory(data.inventory)

        // Recalculate EWT on every position update
        if (data.position != null) setEwtSeconds(calculateEWT(data.position))

        setState('waiting')
      } catch {}
    }

    es.onerror = () => {
      setState(s => s === 'connecting' ? 'waiting' : s)
    }

    return () => es.close()
  }, [saleId])

  // ── EWT Countdown — ticks down every second between SSE updates ──────────────
  useEffect(() => {
    ewtTimerRef.current = setInterval(() => {
      setEwtSeconds(prev => Math.max(0, prev - 1))
    }, 1000)
    return () => clearInterval(ewtTimerRef.current)
  }, [])

  // ── Heartbeat — keep queue position alive every 15 seconds ───────────────────
  useEffect(() => {
    if (!saleId) return
    const ping = async () => {
      try {
        await fetch(`/api/reservations/queue-heartbeat?sale_id=${saleId}`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` }
        })
      } catch {}
    }
    ping()
    const interval = setInterval(ping, 15000)
    return () => clearInterval(interval)
  }, [saleId])

  // ── Derived values ────────────────────────────────────────────────────────────
  const progressPct  = position && totalQueue
    ? Math.max(5, Math.round((1 - (position - 1) / totalQueue) * 100))
    : 0

  const inventoryPct = totalInventory
    ? Math.round((inventory / totalInventory) * 100)
    : 100

  const getChance = () => {
    if (!position || !inventory) return null
    if (position <= inventory)        return { label: 'High',   color: 'var(--accent-green)' }
    if (position <= inventory * 1.5)  return { label: 'Medium', color: 'var(--accent-gold)' }
    return                                   { label: 'Low',    color: 'var(--accent-hot)' }
  }
  const chance = getChance()

  const fmtTime = (s) => {
    if (!s || s <= 0) return '< 1s'
    if (s < 60)       return `${s}s`
    if (s < 3600)     return `${Math.floor(s / 60)}m ${s % 60}s`
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
  }

  // ── Sold Out ──────────────────────────────────────────────────────────────────
  if (state === 'sold_out') {
    return (
      <div style={{ textAlign: 'center', padding: '24px 0' }}>
        <div style={{ fontSize: 48, marginBottom: 12 }}>😔</div>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 32, color: 'var(--accent-hot)', marginBottom: 8 }}>
          SOLD OUT
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>
          All {totalInventory} units were claimed<br />before your position was reached.
        </div>
      </div>
    )
  }

  // ── Admitted ──────────────────────────────────────────────────────────────────
  if (state === 'admitted') {
    return (
      <div style={{ textAlign: 'center', padding: '16px 0' }}>
        <div style={{
          background: '#00FF8710', border: '1px solid #00FF8755',
          borderRadius: 6, padding: '16px', marginBottom: 16,
        }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>🎉</div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, color: 'var(--accent-green)', marginBottom: 4 }}>
            YOUR TURN!
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent-green)' }}>
            Complete your reservation now
          </div>
        </div>
      </div>
    )
  }

  // ── Waiting ───────────────────────────────────────────────────────────────────
  return (
    <div style={{ padding: '8px 0' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
        <span className="live-dot" />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>
          Virtual Waiting Room
        </span>
      </div>

      {/* Queue Position */}
      <div style={{ textAlign: 'center', marginBottom: 20 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.15em', marginBottom: 4 }}>
          Your Queue Number
        </div>
        <div style={{
          fontFamily: 'var(--font-display)', fontSize: 96, lineHeight: 1,
          color: 'var(--accent)', textShadow: '0 0 40px var(--accent)',
        }}>
          #{position ?? '...'}
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
          {position > 1
            ? `${position - 1} ${position - 1 === 1 ? 'person' : 'people'} ahead of you`
            : position === 1 ? 'You are next!' : 'Calculating position...'}
        </div>
      </div>

      {/* Queue Progress Bar */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
            Queue Progress
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--accent)' }}>
            {totalQueue} waiting
          </span>
        </div>
        <div style={{ height: 8, background: 'var(--bg-elevated)', borderRadius: 4, overflow: 'hidden', border: '1px solid var(--border)' }}>
          <div style={{
            height: '100%', width: `${progressPct}%`,
            background: 'linear-gradient(90deg, var(--accent) 0%, #00FF87 100%)',
            borderRadius: 4, transition: 'width 1s ease',
            boxShadow: '0 0 8px var(--accent)',
          }} />
        </div>
      </div>

      {/* Stock Remaining Bar */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
            Stock Remaining
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: inventoryPct < 20 ? 'var(--accent-hot)' : inventoryPct < 50 ? 'var(--accent-gold)' : 'var(--accent-green)' }}>
            {inventory} / {totalInventory}
          </span>
        </div>
        <div style={{ height: 4, background: 'var(--bg-elevated)', borderRadius: 4, overflow: 'hidden', border: '1px solid var(--border)' }}>
          <div style={{
            height: '100%', width: `${inventoryPct}%`,
            background: inventoryPct < 20 ? 'var(--accent-hot)' : inventoryPct < 50 ? 'var(--accent-gold)' : 'var(--accent-green)',
            borderRadius: 4, transition: 'width 1s ease',
          }} />
        </div>
      </div>

      {/* Stats Row — EWT + Chance */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 16 }}>
        <div style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 4, padding: '10px 12px', textAlign: 'center' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 4 }}>
            Est. Wait Time
          </div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 22, color: 'var(--accent-gold)', lineHeight: 1 }}>
            {fmtTime(ewtSeconds)}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)', marginTop: 3 }}>
            updates dynamically
          </div>
        </div>
        <div style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 4, padding: '10px 12px', textAlign: 'center' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 4 }}>
            Chance of Getting
          </div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 22, lineHeight: 1, color: chance?.color ?? 'var(--text-muted)' }}>
            {chance?.label ?? '—'}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)', marginTop: 3 }}>
            based on stock vs position
          </div>
        </div>
      </div>

      {/* Info note */}
      <div style={{
        display: 'flex', alignItems: 'flex-start', gap: 8,
        padding: '10px 12px',
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border)',
        borderRadius: 4,
      }}>
        <span style={{ fontSize: 14, marginTop: 1 }}>ℹ️</span>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6 }}>
          Keep this tab open. You will be automatically admitted when it is your turn.
          Wait time updates as people ahead of you complete their purchase.
        </div>
      </div>
    </div>
  )
}