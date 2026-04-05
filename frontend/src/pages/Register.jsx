import { useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import toast from 'react-hot-toast'
import { register as apiRegister, login as apiLogin, getMe } from '../api/client'
import { useAuth } from '../context/AuthContext'

export default function Register() {
  const [form, setForm] = useState({ full_name: '', email: '', password: '' })
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    try {
      await apiRegister(form)
      const { data } = await apiLogin(form.email, form.password)
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      const { data: userData } = await getMe()
      login(data.access_token, data.refresh_token, userData)
      toast.success(`Welcome to FluxKart, ${userData.full_name?.split(' ')[0]}!`)
      const from = location.state?.from || '/account'
      navigate(from)
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: 'calc(100vh - 60px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
      position: 'relative',
    }}>
      <div style={{
        position: 'fixed', inset: 0,
        backgroundImage: `linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)`,
        backgroundSize: '40px 40px',
        opacity: 0.15,
        pointerEvents: 'none',
      }} />

      <div style={{ width: '100%', maxWidth: 400, position: 'relative' }}>
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 42, color: 'var(--accent)', letterSpacing: '0.05em' }}>
            FLUX<span style={{ color: 'var(--text-primary)' }}>KART</span>
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.12em', marginTop: 4 }}>
            Create your account
          </div>
        </div>

        <div className="card" style={{ padding: 32 }}>
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <div className="form-group">
              <label className="form-label">Full Name</label>
              <input className="form-input" type="text" placeholder="Alice Kumar" value={form.full_name} onChange={set('full_name')} required autoFocus />
            </div>
            <div className="form-group">
              <label className="form-label">Email</label>
              <input className="form-input" type="email" placeholder="alice@example.com" value={form.email} onChange={set('email')} required />
            </div>
            <div className="form-group">
              <label className="form-label">Password</label>
              <input className="form-input" type="password" placeholder="Min 8 characters" value={form.password} onChange={set('password')} required minLength={8} />
            </div>

            <button type="submit" className="btn btn-primary btn-full" style={{ marginTop: 4, height: 44 }} disabled={loading}>
              {loading ? 'Creating account...' : '→ Create Account'}
            </button>
          </form>

          <hr className="divider" />

          <div style={{ textAlign: 'center', fontSize: 13, color: 'var(--text-secondary)' }}>
            Already have an account?{' '}
            <Link to="/login" style={{ color: 'var(--accent)', textDecoration: 'none', fontWeight: 600 }}>Sign in</Link>
          </div>
        </div>
      </div>
    </div>
  )
}