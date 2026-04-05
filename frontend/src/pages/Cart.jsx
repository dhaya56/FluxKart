import { useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { getCart, payOrder, cancelOrder } from '../api/client'
import CountdownTimer from '../components/CountdownTimer'

// ── Formatters ────────────────────────────────────────────────────────────────
const formatCardNumber = (val) => val.replace(/\D/g, '').slice(0, 16).replace(/(.{4})/g, '$1 ').trim()
const formatExpiry     = (val) => {
  const d = val.replace(/\D/g, '').slice(0, 4)
  return d.length >= 3 ? `${d.slice(0, 2)}/${d.slice(2)}` : d
}

// ── UPI Bank Detection ────────────────────────────────────────────────────────
const UPI_HANDLES = {
  '@okaxis':      { bank: 'Axis Bank',     color: '#800000', emoji: '🏦' },
  '@oksbi':       { bank: 'State Bank',    color: '#2d6a4f', emoji: '🏛' },
  '@okhdfcbank':  { bank: 'HDFC Bank',     color: '#004c8c', emoji: '🏦' },
  '@okicici':     { bank: 'ICICI Bank',    color: '#f37021', emoji: '🏦' },
  '@ybl':         { bank: 'PhonePe',       color: '#5f259f', emoji: '📱' },
  '@ibl':         { bank: 'ICICI Bank',    color: '#f37021', emoji: '🏦' },
  '@axl':         { bank: 'Axis Bank',     color: '#800000', emoji: '🏦' },
  '@paytm':       { bank: 'Paytm',         color: '#00b9f1', emoji: '💰' },
  '@gpay':        { bank: 'Google Pay',    color: '#4285f4', emoji: '🔵' },
  '@upi':         { bank: 'UPI',           color: '#ff9900', emoji: '💳' },
  '@kotak':       { bank: 'Kotak Bank',    color: '#ed1c24', emoji: '🏦' },
  '@indus':       { bank: 'IndusInd',      color: '#1a237e', emoji: '🏦' },
  '@pnb':         { bank: 'Punjab National', color: '#ff6600', emoji: '🏦' },
  '@boi':         { bank: 'Bank of India', color: '#003366', emoji: '🏦' },
  '@mahb':        { bank: 'Bank of Maharashtra', color: '#003087', emoji: '🏦' },
}

const detectBank = (upiId) => {
  if (!upiId.includes('@')) return null
  const handle = '@' + upiId.split('@')[1]?.toLowerCase()
  return UPI_HANDLES[handle] || { bank: handle.replace('@', '').toUpperCase(), color: 'var(--accent)', emoji: '💳' }
}

// ── QR Code Generator (Canvas) ────────────────────────────────────────────────
function QRCanvas({ value, size = 160 }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx   = canvas.getContext('2d')
    const cells = 25
    const cell  = size / cells

    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, size, size)
    ctx.fillStyle = '#000000'

    // Deterministic pattern from value string
    const seed = value.split('').reduce((a, c) => a + c.charCodeAt(0), 0)
    const rand = (i) => ((seed * 9301 + i * 49297) % 233280) / 233280

    // Draw cells
    for (let r = 0; r < cells; r++) {
      for (let c = 0; c < cells; c++) {
        // Position detection squares (corners)
        const inCorner = (
          (r < 7 && c < 7) ||
          (r < 7 && c >= cells - 7) ||
          (r >= cells - 7 && c < 7)
        )
        if (inCorner) {
          // Draw corner pattern
          const isOuter = r === 0 || r === 6 || c === 0 || c === 6 ||
                          r === cells-1 || r === cells-7 || c === cells-1 || c === cells-7 ||
                          (r >= cells-7 && c < 7 && (r === cells-7 || r === cells-1 || c === 0 || c === 6))
          const isInner = (r >= 2 && r <= 4 && c >= 2 && c <= 4) ||
                          (r >= 2 && r <= 4 && c >= cells-5 && c <= cells-3) ||
                          (r >= cells-5 && r <= cells-3 && c >= 2 && c <= 4)
          if (isOuter || isInner) {
            ctx.fillRect(c * cell, r * cell, cell, cell)
          } else {
            ctx.clearRect(c * cell, r * cell, cell, cell)
          }
          continue
        }
        // Data cells
        if (rand(r * cells + c) > 0.5) {
          ctx.fillRect(c * cell, r * cell, cell - 0.5, cell - 0.5)
        }
      }
    }

    // FluxKart center logo
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(size/2 - 18, size/2 - 18, 36, 36)
    ctx.fillStyle = '#00E5FF'
    ctx.font      = `bold ${10}px monospace`
    ctx.textAlign = 'center'
    ctx.fillText('FK', size/2, size/2 + 4)
  }, [value, size])

  return <canvas ref={canvasRef} width={size} height={size} style={{ display: 'block' }} />
}

// ── UPI App Button ────────────────────────────────────────────────────────────
const UPI_APPS = [
  { id: 'gpay',     name: 'GPay',     bg: 'linear-gradient(135deg, #4285f4, #34a853)', emoji: 'G',  handle: '@gpay' },
  { id: 'phonepe',  name: 'PhonePe',  bg: 'linear-gradient(135deg, #5f259f, #7b2ff7)', emoji: 'P',  handle: '@ybl' },
  { id: 'paytm',    name: 'Paytm',    bg: 'linear-gradient(135deg, #00b9f1, #0057a3)', emoji: '₹',  handle: '@paytm' },
  { id: 'amazonpay',name: 'Amazon',   bg: 'linear-gradient(135deg, #ff9900, #e47911)', emoji: 'a',  handle: '@apl' },
  { id: 'bhim',     name: 'BHIM',     bg: 'linear-gradient(135deg, #003366, #1a237e)', emoji: 'B',  handle: '@upi' },
  { id: 'cred',     name: 'CRED',     bg: 'linear-gradient(135deg, #1a1a1a, #333)',    emoji: 'C',  handle: '@axl' },
]

// ── Payment Modal ─────────────────────────────────────────────────────────────
function PaymentModal({ items, onClose, onSuccess, isPayAll = false }) {
  const [method, setMethod] = useState('card')  // card | upi
  const [step, setStep]     = useState('form')  // form | processing | success
  const [paying, setPaying] = useState(false)

  // Card state
  const [card, setCard] = useState({ card_number: '', expiry: '', cvv: '', name_on_card: '' })

  // UPI state
  const [upiMode, setUpiMode]     = useState('qr')   // qr | app | id
  const [upiId, setUpiId]         = useState('')
  const [selectedApp, setSelectedApp] = useState(null)
  const [qrUnlocked, setQrUnlocked]   = useState(false)
  const [qrTimer, setQrTimer]         = useState(120)
  const [qrSeed, setQrSeed]           = useState(Date.now().toString())
  const qrTimerRef = useRef(null)

  const item        = items[0] // primary item for display
  const totalAmount = items.reduce((s, i) => s + Number(i.total_price), 0)
  const earliestExpiry = items.reduce((min, i) =>
    new Date(i.expires_at) < new Date(min) ? i.expires_at : min, items[0].expires_at)

  // ── QR Timer ───────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!qrUnlocked) return
    qrTimerRef.current = setInterval(() => {
      setQrTimer(t => {
        if (t <= 1) {
          setQrUnlocked(false)
          setQrSeed(Date.now().toString())
          clearInterval(qrTimerRef.current)
          return 120
        }
        return t - 1
      })
    }, 1000)
    return () => clearInterval(qrTimerRef.current)
  }, [qrUnlocked])

  const unlockQR = () => {
    setQrUnlocked(true)
    setQrTimer(120)
  }

  const cardBrand = () => {
    const d = card.card_number.replace(/\s/g, '')
    if (d.startsWith('4'))  return { label: 'Visa',       color: '#1a1f71' }
    if (d.startsWith('5'))  return { label: 'Mastercard', color: '#eb001b' }
    if (d.startsWith('37')) return { label: 'Amex',       color: '#007bc1' }
    if (d.startsWith('6'))  return { label: 'RuPay',      color: '#ff6600' }
    return null
  }

  const bankInfo = detectBank(upiId)

  // ── Pay handler ────────────────────────────────────────────────────────────
  const handlePay = async () => {
    // Validate based on method
    if (method === 'card') {
      if (!card.name_on_card.trim())                        { toast.error('Enter name on card'); return }
      if (card.card_number.replace(/\s/g, '').length < 15) { toast.error('Invalid card number'); return }
      if (card.expiry.length < 5)                          { toast.error('Invalid expiry'); return }
      if (card.cvv.length < 3)                             { toast.error('Invalid CVV'); return }
    }
    if (method === 'upi') {
      if (upiMode === 'id' && !upiId.includes('@')) { toast.error('Enter a valid UPI ID (e.g. name@gpay)'); return }
      if (upiMode === 'app' && !selectedApp)        { toast.error('Select a UPI app'); return }
    }

    setPaying(true)
    setStep('processing')

    try {
      // Pay each item sequentially
      for (const cartItem of items) {
        const paymentData = method === 'card'
          ? {
              card_number:  card.card_number.replace(/\s/g, ''),
              expiry:       card.expiry,
              cvv:          card.cvv,
              name_on_card: card.name_on_card,
            }
          : {
              // UPI — simulate with dummy card data backend expects
              card_number:  '4111111111111111',
              expiry:       '12/30',
              cvv:          '000',
              name_on_card: upiMode === 'id' ? upiId : (selectedApp?.name || 'UPI Payment'),
            }

        await payOrder(cartItem.order_id, paymentData)
      }

      setStep('success')
      setTimeout(() => onSuccess(), 2500)
    } catch (err) {
      setStep('form')
      toast.error(err.response?.data?.detail || 'Payment failed')
    } finally {
      setPaying(false)
    }
  }

  const brand = cardBrand()

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.9)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24,
    }}
      onClick={(e) => e.target === e.currentTarget && !paying && onClose()}
    >
      <div style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 12,
        width: '100%', maxWidth: 520,
        maxHeight: '92vh', overflowY: 'auto',
        padding: 32,
      }}>

        {/* Processing */}
        {step === 'processing' && (
          <div style={{ textAlign: 'center', padding: '48px 0' }}>
            <div style={{ fontSize: 56, marginBottom: 20 }}>⏳</div>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 32, marginBottom: 8 }}>
              Processing Payment
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)', marginBottom: 24 }}>
              Please do not close this window...
            </div>
            {isPayAll && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 4, padding: '8px 16px', display: 'inline-block' }}>
                Paying {items.length} items · ${totalAmount.toFixed(2)} total
              </div>
            )}
          </div>
        )}

        {/* Success */}
        {step === 'success' && (
          <div style={{ textAlign: 'center', padding: '48px 0' }}>
            <div style={{ fontSize: 72, marginBottom: 20 }}>✅</div>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 36, color: 'var(--accent-green)', marginBottom: 12 }}>
              Payment Successful!
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14, color: 'var(--text-secondary)', marginBottom: 8 }}>
              {isPayAll ? `${items.length} items paid` : item.product_name}
            </div>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, color: 'var(--accent)' }}>
              ${totalAmount.toFixed(2)}
            </div>
          </div>
        )}

        {/* Form */}
        {step === 'form' && (
          <>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
              <div>
                <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 36, marginBottom: 4 }}>CHECKOUT</h2>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                  Secure payment · 256-bit encryption
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, color: 'var(--accent)', lineHeight: 1 }}>
                  ${totalAmount.toFixed(2)}
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                  {isPayAll ? `${items.length} items` : `×${item.quantity}`}
                </div>
              </div>
            </div>

            {/* Reservation timer */}
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              background: '#FF3D5A10', border: '1px solid #FF3D5A33',
              borderRadius: 6, padding: '10px 14px', marginBottom: 24,
            }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent-hot)' }}>
                ⚠ Reservation expires in
              </span>
              <CountdownTimer targetDate={earliestExpiry} label="" size="sm" />
            </div>

            {/* Order lines */}
            <div style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 6, padding: '12px 16px', marginBottom: 24 }}>
              {items.map((i, idx) => (
                <div key={i.reservation_id} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: idx < items.length - 1 ? 8 : 0, fontSize: 13 }}>
                  <span style={{ color: 'var(--text-secondary)' }}>{i.product_name} ×{i.quantity}</span>
                  <span style={{ fontFamily: 'var(--font-mono)' }}>${Number(i.total_price).toFixed(2)}</span>
                </div>
              ))}
              <div style={{ borderTop: '1px solid var(--border)', marginTop: 10, paddingTop: 10, display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontWeight: 700 }}>Total</span>
                <span style={{ fontFamily: 'var(--font-display)', fontSize: 22, color: 'var(--accent)', lineHeight: 1 }}>
                  ${totalAmount.toFixed(2)}
                </span>
              </div>
            </div>

            {/* Payment Method Tabs */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
              {[
                { key: 'card', label: '💳 Card' },
                { key: 'upi',  label: '📱 UPI' },
              ].map(m => (
                <button
                  key={m.key}
                  onClick={() => setMethod(m.key)}
                  style={{
                    flex: 1, padding: '10px 0',
                    background: method === m.key ? 'var(--accent)' : 'var(--bg-elevated)',
                    color: method === m.key ? '#000' : 'var(--text-secondary)',
                    border: `1px solid ${method === m.key ? 'var(--accent)' : 'var(--border)'}`,
                    borderRadius: 6, cursor: 'pointer',
                    fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600,
                    transition: 'all 0.2s',
                  }}
                >
                  {m.label}
                </button>
              ))}
            </div>

            {/* ── CARD FORM ── */}
            {method === 'card' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div className="form-group">
                  <label className="form-label">Name on Card</label>
                  <input className="form-input" placeholder="John Doe"
                    value={card.name_on_card}
                    onChange={e => setCard(c => ({ ...c, name_on_card: e.target.value }))}
                    autoComplete="cc-name"
                  />
                </div>

                <div className="form-group">
                  <label className="form-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                    Card Number
                    {brand && (
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: brand.color, fontWeight: 700 }}>
                        {brand.label}
                      </span>
                    )}
                  </label>
                  <input className="form-input"
                    placeholder="1234 5678 9012 3456"
                    value={card.card_number}
                    onChange={e => setCard(c => ({ ...c, card_number: formatCardNumber(e.target.value) }))}
                    autoComplete="cc-number" inputMode="numeric"
                    style={{ fontFamily: 'var(--font-mono)', letterSpacing: '0.12em' }}
                  />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <div className="form-group">
                    <label className="form-label">Expiry (MM/YY)</label>
                    <input className="form-input" placeholder="12/27"
                      value={card.expiry}
                      onChange={e => setCard(c => ({ ...c, expiry: formatExpiry(e.target.value) }))}
                      autoComplete="cc-exp" inputMode="numeric"
                      style={{ fontFamily: 'var(--font-mono)' }}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">CVV</label>
                    <input className="form-input" placeholder="•••"
                      value={card.cvv}
                      onChange={e => setCard(c => ({ ...c, cvv: e.target.value.replace(/\D/g, '').slice(0, 4) }))}
                      autoComplete="cc-csc" inputMode="numeric" type="password"
                      style={{ fontFamily: 'var(--font-mono)' }}
                    />
                  </div>
                </div>

                {/* Supported cards */}
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  {[
                    { label: 'VISA',  bg: '#1a1f71', color: '#fff' },
                    { label: 'MC',    bg: '#eb001b', color: '#fff' },
                    { label: 'AMEX',  bg: '#007bc1', color: '#fff' },
                    { label: 'RUPAY', bg: '#ff6600', color: '#fff' },
                  ].map(c => (
                    <div key={c.label} style={{
                      background: c.bg, color: c.color,
                      padding: '2px 6px', borderRadius: 3,
                      fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 700,
                    }}>
                      {c.label}
                    </div>
                  ))}
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginLeft: 4 }}>
                    accepted
                  </span>
                </div>
              </div>
            )}

            {/* ── UPI FORM ── */}
            {method === 'upi' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>

{/* UPI sub-tabs */}
                <div style={{ display: 'flex', gap: 6, marginBottom: 20 }}>
                  {[
                    { key: 'qr',  label: '📷 QR Code' },
                    { key: 'app', label: '📱 UPI Apps' },
                  ].map(m => (
                    <button key={m.key} onClick={() => setUpiMode(m.key)}
                      style={{
                        flex: 1, padding: '8px 0',
                        background: upiMode === m.key ? 'var(--bg-elevated)' : 'transparent',
                        color: upiMode === m.key ? 'var(--accent)' : 'var(--text-muted)',
                        border: `1px solid ${upiMode === m.key ? 'var(--accent)' : 'var(--border)'}`,
                        borderRadius: 4, cursor: 'pointer',
                        fontFamily: 'var(--font-mono)', fontSize: 11,
                        transition: 'all 0.15s',
                      }}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>

                {/* QR Code */}
                {upiMode === 'qr' && (
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
                    <div style={{
                      position: 'relative', width: 180, height: 180,
                      borderRadius: 8, overflow: 'hidden', border: '2px solid var(--border)',
                    }}>
                      <QRCanvas
                        value={`upi://pay?pa=fluxkart@okaxis&pn=FluxKart&am=${totalAmount.toFixed(2)}&tn=FluxKart+Payment+${qrSeed}`}
                        size={180}
                      />
                      {!qrUnlocked && (
                        <div style={{
                          position: 'absolute', inset: 0,
                          background: 'rgba(8,10,15,0.85)', backdropFilter: 'blur(6px)',
                          display: 'flex', flexDirection: 'column',
                          alignItems: 'center', justifyContent: 'center', gap: 8, cursor: 'pointer',
                        }} onClick={unlockQR}>
                          <div style={{ fontSize: 32 }}>🔒</div>
                          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent)', textAlign: 'center', lineHeight: 1.5 }}>
                            Click to reveal<br />QR Code
                          </div>
                        </div>
                      )}
                    </div>

                    {qrUnlocked ? (
                      <div style={{ textAlign: 'center' }}>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>QR expires in</div>
                        <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, color: qrTimer <= 30 ? 'var(--accent-hot)' : 'var(--accent-green)', lineHeight: 1 }}>
                          {Math.floor(qrTimer / 60)}:{String(qrTimer % 60).padStart(2, '0')}
                        </div>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                          New QR generated after expiry
                        </div>
                      </div>
                    ) : (
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', textAlign: 'center', lineHeight: 1.6 }}>
                        Scan with any UPI app<br />
                        <span style={{ color: 'var(--accent)', fontSize: 10 }}>GPay · PhonePe · Paytm · BHIM</span>
                      </div>
                    )}
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 4, padding: '6px 12px' }}>
                      UPI ID: fluxkart@okaxis
                    </div>
                  </div>
                )}

                {/* UPI Apps + ID input */}
                {upiMode === 'app' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                      {UPI_APPS.map(app => (
                        <button key={app.id} onClick={() => { setSelectedApp(app); setUpiId('') }}
                          style={{
                            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8,
                            padding: '14px 8px',
                            background: selectedApp?.id === app.id ? 'var(--bg-elevated)' : 'transparent',
                            border: `1px solid ${selectedApp?.id === app.id ? 'var(--accent)' : 'var(--border)'}`,
                            borderRadius: 8, cursor: 'pointer', transition: 'all 0.15s',
                          }}
                        >
                          <div style={{
                            width: 44, height: 44, borderRadius: '50%', background: app.bg,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            fontFamily: 'var(--font-display)', fontSize: 20, color: '#fff', fontWeight: 700,
                            boxShadow: selectedApp?.id === app.id ? '0 0 12px var(--accent)' : 'none',
                          }}>
                            {app.emoji}
                          </div>
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: selectedApp?.id === app.id ? 'var(--accent)' : 'var(--text-secondary)' }}>
                            {app.name}
                          </span>
                        </button>
                      ))}
                    </div>

                    {/* UPI ID input — appears after selecting an app */}
                    {selectedApp && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                          Enter your {selectedApp.name} UPI ID
                        </div>
                        <div className="form-group" style={{ margin: 0 }}>
                          <div style={{ position: 'relative' }}>
                            {bankInfo && (
                              <div style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', fontSize: 16, zIndex: 1 }}>
                                {bankInfo.emoji}
                              </div>
                            )}
                            <input
                              className="form-input"
                              placeholder={`yourname${selectedApp.handle}`}
                              value={upiId}
                              onChange={e => setUpiId(e.target.value.toLowerCase())}
                              style={{
                                fontFamily: 'var(--font-mono)',
                                paddingLeft: bankInfo ? 40 : 14,
                                borderColor: bankInfo ? bankInfo.color : undefined,
                              }}
                            />
                          </div>
                        </div>

                        {bankInfo && upiId.includes('@') && (
                          <div style={{
                            display: 'flex', alignItems: 'center', gap: 10,
                            background: 'var(--bg-elevated)', border: `1px solid ${bankInfo.color}`,
                            borderRadius: 6, padding: '10px 14px',
                          }}>
                            <div style={{ width: 32, height: 32, borderRadius: '50%', background: bankInfo.color, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16 }}>
                              {bankInfo.emoji}
                            </div>
                            <div>
                              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)' }}>{bankInfo.bank}</div>
                              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>{upiId}</div>
                            </div>
                            <div style={{ marginLeft: 'auto', fontSize: 16 }}>✅</div>
                          </div>
                        )}

                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>
                          e.g. yourname{selectedApp.handle}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Security row */}
            <div style={{ display: 'flex', justifyContent: 'center', gap: 16, margin: '20px 0 16px', flexWrap: 'wrap' }}>
              {['🔒 SSL', '✅ PCI DSS', '🛡 2FA'].map(t => (
                <span key={t} style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>{t}</span>
              ))}
            </div>

            {/* Pay button */}
            <button
              className="btn btn-primary btn-full btn-lg"
              onClick={handlePay}
              disabled={paying}
              style={{ fontSize: 16, marginBottom: 10 }}
            >
              {paying ? 'Processing...' : `Pay $${totalAmount.toFixed(2)} ${isPayAll && items.length > 1 ? `(${items.length} items)` : ''}`}
            </button>

            <button className="btn btn-ghost btn-full" onClick={onClose} disabled={paying}>
              Cancel
            </button>
          </>
        )}
      </div>
    </div>
  )
}

// ── Cart Item Card ─────────────────────────────────────────────────────────────
function CartItem({ item, onPay, onCancel }) {
  const [cancelling, setCancelling] = useState(false)

  const handleCancel = async () => {
    if (!window.confirm('Cancel this reservation? Your held inventory will be released.')) return
    setCancelling(true)
    try {
      await cancelOrder(item.order_id)
      toast.success('Reservation cancelled — inventory released')
      onCancel()
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Cancel failed')
    } finally {
      setCancelling(false)
    }
  }

  const discount    = Math.round((1 - item.sale_price / item.original_price) * 100)
  const minutesLeft = Math.floor((new Date(item.expires_at) - new Date()) / 60000)
  const isUrgent    = minutesLeft <= 3

  return (
    <div className="card" style={{
      padding: 24,
      border: isUrgent ? '1px solid var(--accent-hot)' : '1px solid var(--border)',
      position: 'relative', overflow: 'hidden',
    }}>
      {isUrgent && (
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: 'var(--accent-hot)', animation: 'pulse 1s infinite' }} />
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 24, alignItems: 'start' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span className="badge badge-active">
              <span className="live-dot" style={{ width: 6, height: 6 }} />
              Reserved
            </span>
            {isUrgent && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--accent-hot)', textTransform: 'uppercase' }}>
                ⚠ Expiring soon!
              </span>
            )}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 4 }}>
            {item.product_name}
          </div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 22, marginBottom: 12, lineHeight: 1.2 }}>
            {item.title}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 8 }}>
            <span style={{ fontFamily: 'var(--font-display)', fontSize: 32, color: 'var(--accent)', lineHeight: 1 }}>
              ${Number(item.total_price).toFixed(2)}
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)', textDecoration: 'line-through' }}>
              ${(Number(item.original_price) * item.quantity).toFixed(2)}
            </span>
            <span style={{ background: 'var(--accent-hot)', color: '#fff', fontFamily: 'var(--font-display)', fontSize: 14, padding: '1px 6px', borderRadius: 2 }}>
              -{discount}%
            </span>
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>
            {item.quantity} × ${Number(item.sale_price).toFixed(2)} per unit
          </div>
        </div>

        <div style={{ minWidth: 160, textAlign: 'right' }}>
          <div style={{
            background: isUrgent ? '#FF3D5A10' : 'var(--bg-elevated)',
            border: `1px solid ${isUrgent ? 'var(--accent-hot)' : 'var(--border)'}`,
            borderRadius: 6, padding: '12px 16px', marginBottom: 12, textAlign: 'center',
          }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 6 }}>
              Complete in
            </div>
            <CountdownTimer targetDate={item.expires_at} label="" size="md" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <button className="btn btn-primary btn-full animate-pulse-glow" onClick={() => onPay([item])} style={{ fontSize: 13 }}>
              💳 Pay Now
            </button>
            <button className="btn btn-ghost btn-full btn-sm" onClick={handleCancel} disabled={cancelling} style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {cancelling ? 'Cancelling...' : 'Remove'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main Cart Page ─────────────────────────────────────────────────────────────
export default function Cart() {
  const [items, setItems]         = useState([])
  const [loading, setLoading]     = useState(true)
  const [payingItems, setPayingItems] = useState(null) // null | array of items
  const navigate = useNavigate()

  const fetchCart = useCallback(async () => {
    try {
      const { data } = await getCart()
      setItems(data)
    } catch {}
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchCart()
    const interval = setInterval(fetchCart, 10000)
    return () => clearInterval(interval)
  }, [fetchCart])

  const handlePaySuccess = () => {
    setPayingItems(null)
    toast.success('🎉 Payment confirmed! Check your order history.')
    fetchCart()
    setTimeout(() => navigate('/orders'), 2500)
  }

  const totalAmount   = items.reduce((s, i) => s + Number(i.total_price), 0)
  const hasMultiple   = items.length > 1

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
      Loading cart...
    </div>
  )

  return (
    <div className="page">
      <div className="container">

        <div style={{ marginBottom: 40 }}>
          <h1 style={{ fontSize: 64, marginBottom: 8 }}>MY CART</h1>
          <p style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
            {items.length} {items.length === 1 ? 'item' : 'items'} reserved · Complete payment before timer expires
          </p>
        </div>

        {items.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">🛒</div>
            <div className="empty-state-title">Your cart is empty</div>
            <p style={{ marginBottom: 20 }}>Reserve a flash sale item to start checkout.</p>
            <button className="btn btn-primary" onClick={() => navigate('/sales')}>Browse Flash Sales</button>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 32, alignItems: 'start' }}>

            {/* Cart items */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {items.map(item => (
                <CartItem
                  key={item.reservation_id}
                  item={item}
                  onPay={(itemArr) => setPayingItems(itemArr)}
                  onCancel={fetchCart}
                />
              ))}
            </div>

            {/* Sidebar */}
            <div style={{ position: 'sticky', top: 80 }}>
              <div className="card" style={{ padding: 24 }}>
                <div style={{ fontFamily: 'var(--font-display)', fontSize: 24, marginBottom: 20 }}>ORDER SUMMARY</div>

                {items.map(item => (
                  <div key={item.reservation_id} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10, fontSize: 13 }}>
                    <span style={{ color: 'var(--text-secondary)' }}>{item.product_name} ×{item.quantity}</span>
                    <span style={{ fontFamily: 'var(--font-mono)' }}>${Number(item.total_price).toFixed(2)}</span>
                  </div>
                ))}

                <div style={{ borderTop: '1px solid var(--border)', marginTop: 12, paddingTop: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 20 }}>
                  <span style={{ fontWeight: 700 }}>Total</span>
                  <span style={{ fontFamily: 'var(--font-display)', fontSize: 32, color: 'var(--accent)', lineHeight: 1 }}>
                    ${totalAmount.toFixed(2)}
                  </span>
                </div>

                {/* Pay All button — only when multiple items */}
                {hasMultiple ? (
                  <button
                    className="btn btn-primary btn-full btn-lg animate-pulse-glow"
                    onClick={() => setPayingItems(items)}
                    style={{ marginBottom: 8, fontSize: 15 }}
                  >
                    ⚡ Pay All · ${totalAmount.toFixed(2)}
                  </button>
                ) : (
                  <button
                    className="btn btn-primary btn-full"
                    onClick={() => setPayingItems(items)}
                    style={{ marginBottom: 8 }}
                  >
                    💳 Pay ${totalAmount.toFixed(2)}
                  </button>
                )}

                {/* Security */}
                <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {['🔒 256-bit SSL encryption', '✅ Price locked at reservation', '♻️ Cancel anytime before payment', '🛡 PCI DSS compliant'].map(text => (
                    <div key={text} style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>
                      {text}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {payingItems && (
        <PaymentModal
          items={payingItems}
          isPayAll={payingItems.length > 1}
          onClose={() => setPayingItems(null)}
          onSuccess={handlePaySuccess}
        />
      )}
    </div>
  )
}