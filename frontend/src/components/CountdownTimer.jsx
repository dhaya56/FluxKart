import { useCountdown } from '../hooks/useCountdown'

export default function CountdownTimer({ targetDate, label = 'Ends in', size = 'md' }) {
  const { days, hours, minutes, seconds, expired } = useCountdown(targetDate)

  if (expired) {
    return (
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>
        Sale ended
      </div>
    )
  }

  const numSize = size === 'lg' ? 36 : size === 'sm' ? 16 : 22
  const padSize = size === 'lg' ? '10px 14px' : size === 'sm' ? '4px 8px' : '6px 10px'

  return (
    <div>
      {label && (
        <div style={{
          fontSize: 10,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          fontFamily: 'var(--font-mono)',
          marginBottom: 6,
        }}>
          {label}
        </div>
      )}
      <div className="countdown">
        {days > 0 && (
          <>
            <div className="countdown-unit">
              <span className="countdown-num" style={{ fontSize: numSize, padding: padSize }}>
                {String(days).padStart(2, '0')}
              </span>
              <span className="countdown-label">days</span>
            </div>
            <span className="countdown-sep">:</span>
          </>
        )}
        <div className="countdown-unit">
          <span className="countdown-num" style={{ fontSize: numSize, padding: padSize }}>
            {String(hours).padStart(2, '0')}
          </span>
          <span className="countdown-label">hrs</span>
        </div>
        <span className="countdown-sep">:</span>
        <div className="countdown-unit">
          <span className="countdown-num" style={{ fontSize: numSize, padding: padSize }}>
            {String(minutes).padStart(2, '0')}
          </span>
          <span className="countdown-label">min</span>
        </div>
        <span className="countdown-sep">:</span>
        <div className="countdown-unit">
          <span className="countdown-num" style={{ fontSize: numSize, padding: padSize, color: seconds < 30 ? 'var(--accent-hot)' : undefined }}>
            {String(seconds).padStart(2, '0')}
          </span>
          <span className="countdown-label">sec</span>
        </div>
      </div>
    </div>
  )
}