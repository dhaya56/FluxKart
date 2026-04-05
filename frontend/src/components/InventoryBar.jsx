export default function InventoryBar({ total, available, reserved }) {
  const soldOrReserved = total - available
  const pctAvailable = Math.max(0, (available / total) * 100)

  let colorClass = 'progress-green'
  if (pctAvailable < 30) colorClass = 'progress-red'
  else if (pctAvailable < 60) colorClass = 'progress-yellow'

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Stock
        </span>
        <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: pctAvailable < 30 ? 'var(--accent-hot)' : 'var(--text-secondary)' }}>
          {available} / {total} left
          {pctAvailable < 20 && ' 🔥'}
        </span>
      </div>
      <div className="progress-track">
        <div
          className={`progress-fill ${colorClass}`}
          style={{ width: `${pctAvailable}%` }}
        />
      </div>
      {pctAvailable < 15 && (
        <div style={{
          marginTop: 6,
          fontSize: 11,
          color: 'var(--accent-hot)',
          fontFamily: 'var(--font-mono)',
          fontWeight: 600,
          animation: 'pulse-glow 1s ease-in-out infinite',
        }}>
          ⚡ Almost gone — {available} remaining
        </div>
      )}
    </div>
  )
}