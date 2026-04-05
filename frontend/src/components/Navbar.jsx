import { useState, useRef, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { Shield, ChevronDown, Package, User, LogOut, Zap, LayoutDashboard, ShoppingCart } from 'lucide-react'

export default function Navbar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef(null)

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleLogout = () => {
    logout()
    setDropdownOpen(false)
    navigate('/')
  }

  return (
    <nav className="navbar">
      <Link to="/" className="navbar-logo">
        FLUX<span>KART</span>
      </Link>

      <div className="navbar-links">
        <Link to="/sales" className="btn btn-ghost btn-sm">
          <Zap size={13} /> Flash Sales
        </Link>

        {user ? (
          <>
            {user.is_admin && (
              <Link to="/admin" className="btn btn-ghost btn-sm hide-mobile">
                <Shield size={13} /> Admin
              </Link>
            )}

            {/* Cart link */}
            <Link to="/cart" className="btn btn-ghost btn-sm hide-mobile">
              <ShoppingCart size={13} /> Cart
            </Link>

            {/* Account Dropdown */}
            <div ref={dropdownRef} style={{ position: 'relative' }}>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => setDropdownOpen(o => !o)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  background: dropdownOpen ? 'var(--bg-elevated)' : undefined,
                  borderColor: dropdownOpen ? 'var(--accent)' : undefined,
                }}
              >
                {/* Avatar */}
                <div style={{
                  width: 26, height: 26,
                  borderRadius: '50%',
                  background: 'var(--accent-dim)',
                  border: '1px solid var(--accent)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontFamily: 'var(--font-display)',
                  fontSize: 14,
                  color: 'var(--accent)',
                }}>
                  {(user.full_name || user.email)[0].toUpperCase()}
                </div>
                <span style={{ fontSize: 13, maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {user.full_name?.split(' ')[0] || user.email.split('@')[0]}
                </span>
                <ChevronDown size={12} style={{ transition: 'transform 0.2s', transform: dropdownOpen ? 'rotate(180deg)' : 'none' }} />
              </button>

              {/* Dropdown Menu */}
              {dropdownOpen && (
                <div style={{
                  position: 'absolute', top: 'calc(100% + 8px)', right: 0,
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  minWidth: 220,
                  boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
                  zIndex: 200,
                  overflow: 'hidden',
                }}>
                  {/* User info header */}
                  <div style={{
                    padding: '14px 16px',
                    borderBottom: '1px solid var(--border)',
                    background: 'var(--bg-elevated)',
                  }}>
                    <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 2 }}>
                      {user.full_name || 'User'}
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                      {user.email}
                    </div>
                  </div>

                  {/* Menu items */}
                  {[
                    { icon: <LayoutDashboard size={14} />, label: 'My Dashboard', to: '/account' },
                    { icon: <ShoppingCart size={14} />,    label: 'My Cart',      to: '/cart' },
                    { icon: <Package size={14} />,         label: 'My Orders',    to: '/orders' },
                    { icon: <User size={14} />,            label: 'Profile',      to: '/account/profile' },
                  ].map(({ icon, label, to }) => (
                    <Link
                      key={to}
                      to={to}
                      onClick={() => setDropdownOpen(false)}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 10,
                        padding: '11px 16px',
                        color: 'var(--text-secondary)',
                        textDecoration: 'none',
                        fontSize: 14,
                        transition: 'all 0.15s',
                        borderBottom: '1px solid var(--border)',
                      }}
                      onMouseEnter={e => {
                        e.currentTarget.style.background = 'var(--bg-elevated)'
                        e.currentTarget.style.color = 'var(--accent)'
                      }}
                      onMouseLeave={e => {
                        e.currentTarget.style.background = 'transparent'
                        e.currentTarget.style.color = 'var(--text-secondary)'
                      }}
                    >
                      <span style={{ color: 'var(--accent)' }}>{icon}</span>
                      {label}
                    </Link>
                  ))}

                  <button
                    onClick={handleLogout}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '11px 16px',
                      color: 'var(--accent-hot)',
                      background: 'transparent',
                      border: 'none',
                      width: '100%',
                      fontSize: 14,
                      cursor: 'pointer',
                      transition: 'background 0.15s',
                      fontFamily: 'var(--font-body)',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-elevated)'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  >
                    <LogOut size={14} />
                    Sign Out
                  </button>
                </div>
              )}
            </div>
          </>
        ) : (
          <>
            <Link to="/login" className="btn btn-ghost btn-sm">Login</Link>
            <Link to="/register" className="btn btn-primary btn-sm">Sign Up</Link>
          </>
        )}
      </div>
    </nav>
  )
}