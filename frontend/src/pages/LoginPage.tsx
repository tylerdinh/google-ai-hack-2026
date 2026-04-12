import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { sb } from '../lib/supabase'

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
    sb.auth.getSession().then(({ data: { session } }) => {
      if (session) navigate('/stocks')
    })
    const { data: { subscription } } = sb.auth.onAuthStateChange((_event, session) => {
      if (session) navigate('/stocks')
    })
    return () => subscription.unsubscribe()
  }, [navigate])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(''); setSuccess('')
    if (!email || !password) { setError('Please fill in all fields.'); return }
    setLoading(true)
    try {
      if (isSignUp) {
        if (password !== confirm) { setError('Passwords do not match.'); return }
        const { error } = await sb.auth.signUp({ email, password })
        if (error) throw error
        setSuccess('Account created! Check your email to confirm, then log in.')
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
      options: { redirectTo: window.location.origin + '/stocks' }
    })
    if (error) setError(error.message)
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-6 pb-10 pt-0">
      <header className="relative left-1/2 mb-6 w-screen -translate-x-1/2 rounded-b-xl border-b border-panelBorder/25 bg-[#23182f]/95 px-6 py-4 shadow-[0_8px_24px_rgba(0,0,0,0.18)] sm:px-8">
        <h1 className="font-display text-4xl text-lavender sm:text-5xl">Consilium</h1>
      </header>

      <div className="flex flex-1 items-center justify-center">
        <section className="glass-card mx-auto w-full max-w-2xl rounded-3xl p-8 sm:p-10">
          <h2 className="mt-3 font-display text-4xl text-lavender sm:text-5xl">
            {isSignUp ? 'Sign Up' : 'Login'}
          </h2>
          <p className="mt-2 text-sm text-zinc-400">
            {isSignUp
              ? 'Create an account to save your watchlist and analyses.'
              : 'Sign in to access your watchlist and AI analysis.'}
          </p>

          {error   && <div className="mt-4 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">{error}</div>}
          {success && <div className="mt-4 rounded-xl border border-success/40 bg-success/10 px-4 py-3 text-sm text-success">{success}</div>}

          <div className="mt-8 space-y-3">
            <button onClick={() => handleOAuth('google')}
              className="flex w-full items-center justify-center gap-3 rounded-xl border border-panelBorder/60 bg-canvas/50 px-5 py-3 text-sm font-semibold text-zinc-200 transition hover:border-lavender/50 hover:bg-canvas/70">
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
              </svg>
              Continue with Google
            </button>
            <button onClick={() => handleOAuth('github')}
              className="flex w-full items-center justify-center gap-3 rounded-xl border border-panelBorder/60 bg-canvas/50 px-5 py-3 text-sm font-semibold text-zinc-200 transition hover:border-lavender/50 hover:bg-canvas/70">
              <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 0C5.37 0 0 5.37 0 12c0 5.3 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.73.083-.73 1.205.085 1.84 1.236 1.84 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.418-1.305.762-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.605-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 21.795 24 17.295 24 12c0-6.63-5.37-12-12-12z"/>
              </svg>
              Continue with GitHub
            </button>
          </div>

          <div className="my-6 flex items-center gap-3 text-xs text-zinc-500">
            <span className="flex-1 border-t border-panelBorder/35" />
            or
            <span className="flex-1 border-t border-panelBorder/35" />
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <label className="block">
              <span className="mb-2 block text-sm font-semibold text-lavender/90">Email</span>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com" autoComplete="email"
                className="w-full rounded-xl border border-panelBorder/60 bg-canvas/80 px-4 py-3 text-sm outline-none transition focus:border-lavender" />
            </label>
            <label className="block">
              <span className="mb-2 block text-sm font-semibold text-lavender/90">Password</span>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                placeholder="••••••••" autoComplete={isSignUp ? 'new-password' : 'current-password'}
                className="w-full rounded-xl border border-panelBorder/60 bg-canvas/80 px-4 py-3 text-sm outline-none transition focus:border-lavender" />
            </label>
            {isSignUp && (
              <label className="block">
                <span className="mb-2 block text-sm font-semibold text-lavender/90">Confirm Password</span>
                <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)}
                  placeholder="••••••••" autoComplete="new-password"
                  className="w-full rounded-xl border border-panelBorder/60 bg-canvas/80 px-4 py-3 text-sm outline-none transition focus:border-lavender" />
              </label>
            )}
            <button type="submit" disabled={loading}
              className="w-full rounded-xl border border-lavender/60 bg-lavender/20 px-5 py-3 text-base font-semibold text-lavender transition hover:bg-lavender/30 disabled:opacity-50">
              {loading ? (isSignUp ? 'Creating account…' : 'Logging in…') : (isSignUp ? 'Create Account' : 'Log In')}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-zinc-500">
            {isSignUp ? 'Already have an account?' : "Don't have an account?"}
            <button onClick={() => { setIsSignUp(v => !v); setError(''); setSuccess('') }}
              className="ml-1 font-semibold text-lavender transition hover:text-lavender/80">
              {isSignUp ? 'Log in' : 'Sign up'}
            </button>
          </p>
        </section>
      </div>
    </main>
  )
}