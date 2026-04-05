import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import { AuthProvider, useAuth } from './context/AuthContext'
import Navbar from './components/Navbar'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Register from './pages/Register'
import Sales from './pages/Sales'
import SaleDetail from './pages/SaleDetail'
import Orders from './pages/Orders'
import Cart from './pages/Cart'
import Account from './pages/Account'
import Profile from './pages/Profile'
import Admin from './pages/Admin'

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return null
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />
  return children
}

function AppRoutes() {
  return (
    <>
      <Navbar />
      <Routes>
        {/* Public */}
        <Route path="/"          element={<Landing />} />
        <Route path="/login"     element={<Login />} />
        <Route path="/register"  element={<Register />} />
        <Route path="/sales"     element={<Sales />} />
        <Route path="/sales/:id" element={<SaleDetail />} />

        {/* Protected */}
        <Route path="/account" element={
          <ProtectedRoute><Account /></ProtectedRoute>
        } />
        <Route path="/account/profile" element={
          <ProtectedRoute><Profile /></ProtectedRoute>
        } />
        <Route path="/orders" element={
          <ProtectedRoute><Orders /></ProtectedRoute>
        } />
        <Route path="/cart" element={
          <ProtectedRoute><Cart /></ProtectedRoute>
        } />
        <Route path="/admin" element={
          <ProtectedRoute><Admin /></ProtectedRoute>
        } />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
        <Toaster
          position="bottom-right"
          toastOptions={{
            style: {
              background: 'var(--bg-elevated)',
              color: 'var(--text-primary)',
              border: '1px solid var(--border)',
              fontFamily: 'var(--font-body)',
              fontSize: 14,
            },
          }}
        />
      </AuthProvider>
    </BrowserRouter>
  )
}