import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { sb } from '../lib/supabase'
import { Mail, Lock, AlertCircle, CheckCircle, ArrowRight} from 'lucide-react'

export default function LoginPage() {
  const navigate = useNavigate()
  const [isSignUp, setIsSignUp] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    // onAuthStateChange handles both pre-existing sessions and OAuth redirects
    // (SIGNED_IN fires when Supabase processes the #access_token hash after redirect)
    const { data: { subscription } } = sb.auth.onAuthStateChange((_event, session) => {
      if (session) navigate('/stocks')
    })
    return () => subscription.unsubscribe()
  }, [navigate])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(''); setSuccess('')
    if (!email || !password) { setError('Please fill in all fields.'); return }
    if (isSignUp && password !== confirm) { setError('Passwords do not match.'); return }
    setLoading(true)
    try {
      if (isSignUp) {
        const { error } = await sb.auth.signUp({ email, password })
        if (error) throw error
        setSuccess('Account created. Check your email to confirm, then log in.')
      } else {
        const { error } = await sb.auth.signInWithPassword({ email, password })
        if (error) throw error
      }
    } catch (err: any) {
      setError(err.message || 'Authentication failed.')
    } finally {
      setLoading(false)
    }
  }

  async function handleOAuth(provider: 'google' | 'github') {
    const { error } = await sb.auth.signInWithOAuth({
      provider,
      options: { redirectTo: window.location.origin + '/' }
    })
    if (error) setError(error.message)
  }

  return (
    <main
      className="flex min-h-screen w-full flex-col"
      style={{ background: 'var(--cream)', fontFamily: 'var(--font-body, "DM Sans", sans-serif)' }}
    >
      {/* Header */}
      <header
        className="w-full px-8 py-5 border-b"
        style={{ borderColor: 'var(--border)', background: 'rgba(249,247,245,0.92)', backdropFilter: 'blur(16px)' }}
      >
        <span
          className="font-display text-2xl tracking-tight"
          style={{ fontFamily: '"Cormorant Garamond", Georgia, serif', color: 'var(--ink)', fontWeight: 400 }}
        >
          Boardroom
        </span>
      </header>

      {/* Center content */}
      <div className="flex flex-1 items-center justify-center px-6 py-16">
        <section
          className="glass-card w-full max-w-md fade-up"
          style={{ padding: '44px 40px', borderRadius: '20px' }}
        >
          {/* Title */}
          <div style={{ marginBottom: '8px' }}>
            <p
              style={{
                fontSize: '0.62rem',
                fontWeight: 500,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                color: 'var(--mist)',
                marginBottom: '10px',
              }}
            >
              {isSignUp ? 'New account' : 'Welcome back'}
            </p>
            <h1
              style={{
                fontFamily: '"Cormorant Garamond", Georgia, serif',
                fontSize: '2.6rem',
                fontWeight: 300,
                color: 'var(--ink)',
                lineHeight: 1.1,
                letterSpacing: '-0.02em',
                margin: 0,
              }}
            >
              {isSignUp ? 'Create account' : 'Sign in'}
            </h1>
          </div>

          <p style={{ fontSize: '0.8rem', color: 'var(--mist)', marginBottom: '32px', marginTop: '8px', lineHeight: 1.6 }}>
            {isSignUp
              ? 'Save your watchlist and analyses across sessions.'
              : 'Access your watchlist and AI-powered analysis.'}
          </p>

          {/* Alerts */}
          {error && (
            <div
              className="fade-in"
              style={{
                display: 'flex', alignItems: 'flex-start', gap: '10px',
                background: 'rgba(139,58,60,0.07)',
                border: '1px solid rgba(139,58,60,0.22)',
                borderRadius: '10px', padding: '12px 14px',
                marginBottom: '20px',
              }}
            >
              <AlertCircle size={15} style={{ color: 'var(--no)', flexShrink: 0, marginTop: '1px' }} />
              <span style={{ fontSize: '0.78rem', color: 'var(--no)', lineHeight: 1.5 }}>{error}</span>
            </div>
          )}
          {success && (
            <div
              className="fade-in"
              style={{
                display: 'flex', alignItems: 'flex-start', gap: '10px',
                background: 'rgba(74,124,89,0.07)',
                border: '1px solid rgba(74,124,89,0.22)',
                borderRadius: '10px', padding: '12px 14px',
                marginBottom: '20px',
              }}
            >
              <CheckCircle size={15} style={{ color: 'var(--ok)', flexShrink: 0, marginTop: '1px' }} />
              <span style={{ fontSize: '0.78rem', color: 'var(--ok)', lineHeight: 1.5 }}>{success}</span>
            </div>
          )}

          {/* OAuth */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '28px' }}>
            <button
              onClick={() => handleOAuth('google')}
              className="btn btn-secondary"
              style={{ width: '100%', padding: '12px 18px', justifyContent: 'center', gap: '10px', fontSize: '0.82rem' }}
            >
              {/* Google SVG kept as-is since it's a brand mark, not a UI icon */}
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
              </svg>
              Continue with Google
            </button>
          </div>

          {/* Divider */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '28px' }}>
            <span style={{ flex: 1, borderTop: '1px solid var(--border)' }} />
            <span style={{ fontSize: '0.68rem', color: 'var(--mist)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>or</span>
            <span style={{ flex: 1, borderTop: '1px solid var(--border)' }} />
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
            <label style={{ display: 'block' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                <Mail size={13} style={{ color: 'var(--mist)' }} />
                <span style={{ fontSize: '0.7rem', fontWeight: 500, letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--stone-mid)' }}>
                  Email
                </span>
              </span>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
                className="input-field"
              />
            </label>

            <label style={{ display: 'block' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                <Lock size={13} style={{ color: 'var(--mist)' }} />
                <span style={{ fontSize: '0.7rem', fontWeight: 500, letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--stone-mid)' }}>
                  Password
                </span>
              </span>
              <input
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete={isSignUp ? 'new-password' : 'current-password'}
                className="input-field"
              />
            </label>

            {isSignUp && (
              <label style={{ display: 'block' }} className="fade-in">
                <span style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  <Lock size={13} style={{ color: 'var(--mist)' }} />
                  <span style={{ fontSize: '0.7rem', fontWeight: 500, letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--stone-mid)' }}>
                    Confirm Password
                  </span>
                </span>
                <input
                  type="password"
                  value={confirm}
                  onChange={e => setConfirm(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="new-password"
                  className="input-field"
                />
              </label>
            )}

            <button
              type="submit"
              disabled={loading}
              className="btn btn-primary"
              style={{ width: '100%', padding: '13px 22px', marginTop: '4px', fontSize: '0.84rem', justifyContent: 'center' }}
            >
              {loading ? (
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span className="spinner" />
                  {isSignUp ? 'Creating account…' : 'Signing in…'}
                </span>
              ) : (
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {isSignUp ? 'Create Account' : 'Sign In'}
                  <ArrowRight size={15} />
                </span>
              )}
            </button>
          </form>

          {/* Toggle */}
          <p style={{ marginTop: '28px', textAlign: 'center', fontSize: '0.78rem', color: 'var(--mist)' }}>
            {isSignUp ? 'Already have an account?' : "Don't have an account?"}
            {' '}
            <button
              onClick={() => { setIsSignUp(v => !v); setError(''); setSuccess('') }}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: '0.78rem', fontWeight: 500, color: 'var(--accent)',
                padding: 0, textDecoration: 'underline', textUnderlineOffset: '3px',
              }}
            >
              {isSignUp ? 'Sign in' : 'Sign up'}
            </button>
          </p>
        </section>
      </div>
    </main>
  )
}