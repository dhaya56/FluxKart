import { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import toast from 'react-hot-toast'
import { User, Mail, Shield, Calendar } from 'lucide-react'
import { format } from 'date-fns'

export default function Profile() {
  const { user } = useAuth()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(user?.full_name || '')

  const handleSave = () => {
    // In production this would call PATCH /auth/me
    toast.success('Profile updated')
    setEditing(false)
  }

  return (
    <div className="page">
      <div className="container" style={{ maxWidth: 640 }}>
        <h1 style={{ fontSize: 56, marginBottom: 8 }}>PROFILE</h1>
        <p style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: 13, marginBottom: 40 }}>
          Manage your account details
        </p>

        {/* Avatar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 20, marginBottom: 40 }}>
          <div style={{
            width: 80, height: 80, borderRadius: '50%',
            background: 'var(--accent-dim)',
            border: '2px solid var(--accent)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'var(--font-display)', fontSize: 42, color: 'var(--accent)',
          }}>
            {(user?.full_name || user?.email || 'U')[0].toUpperCase()}
          </div>
          <div>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 28 }}>{user?.full_name}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>{user?.email}</div>
          </div>
        </div>

        {/* Details Card */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 0, padding: 0, overflow: 'hidden' }}>
          {[
            {
              icon: <User size={15} />,
              label: 'Full Name',
              value: editing
                ? <input className="form-input" value={name} onChange={e => setName(e.target.value)} style={{ padding: '4px 10px', fontSize: 14 }} />
                : user?.full_name,
            },
            { icon: <Mail size={15} />,     label: 'Email',          value: user?.email },
            { icon: <Shield size={15} />,   label: 'Account Status', value: <span className="badge badge-active">Active</span> },
            { icon: <Calendar size={15} />, label: 'Member Since',   value: user?.created_at ? format(new Date(user.created_at), 'MMMM d, yyyy') : '—' },
          ].map(({ icon, label, value }) => (
            <div key={label} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '16px 24px',
              borderBottom: '1px solid var(--border)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-muted)' }}>
                <span style={{ color: 'var(--accent)' }}>{icon}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
              </div>
              <div style={{ fontSize: 14, fontWeight: 500 }}>{value}</div>
            </div>
          ))}
        </div>

        {/* Edit button */}
        <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
          {editing ? (
            <>
              <button className="btn btn-primary" onClick={handleSave}>Save Changes</button>
              <button className="btn btn-ghost" onClick={() => setEditing(false)}>Cancel</button>
            </>
          ) : (
            <button className="btn btn-outline" onClick={() => setEditing(true)}>Edit Profile</button>
          )}
        </div>
      </div>
    </div>
  )
}