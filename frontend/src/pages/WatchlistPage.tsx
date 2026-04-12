import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { sb } from '../lib/supabase'
import type { Session } from '@supabase/supabase-js'
import { Plus, X, Search, LogOut, TrendingUp, TrendingDown, ChevronRight } from 'lucide-react'

const API_BASE_URL = (window as any).STOCK_API_BASE_URL || ''

// ── Types ─────────────────────────────────────────────────────────────────────
interface StockQuote {
  name?: string
  close?: number
  previous_close?: number
  change?: number
  percent_change?: number
}
interface SeriesItem {
  close: string | number
  timestamp?: string
  datetime?: string
  date?: string
}
interface SearchResult {
  symbol: string
  name?: string
  exchange?: string
}
interface StockData {
  symbol: string
  name: string
  price: string
  delta: string
  isUp: boolean
  closes: number[]
  dates: string[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function toNumber(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}
function toCurrency(v: unknown) { return `$${toNumber(v).toFixed(2)}` }
function signedValue(v: unknown) { return `$${Math.abs(toNumber(v)).toFixed(2)}` }
function signedPercent(v: unknown) { return `${Math.abs(toNumber(v)).toFixed(2)}%` }
function formatDelta(change: number, percent: number, isUp: boolean) {
  return `${signedValue(change)}  ${signedPercent(percent)}`
}
function fmtSparkDate(dt: string): string {
  if (!dt) return ''
  const d = new Date(dt.replace(' ', 'T'))
  if (isNaN(d.getTime())) return ''
  return d.toLocaleDateString('en-US', { weekday: 'short', day: 'numeric' })
}
function getSeriesChange(closes: number[]) {
  if (closes.length < 2) return null
  const first = closes[0], last = closes[closes.length - 1]
  const change = last - first
  const percent = first ? (change / first) * 100 : 0
  return { lastClose: last, change, percent, isUp: change >= 0 }
}

function renderSparklineSvg(closes: number[], dates: string[], isUp: boolean): string {
  if (closes.length < 2) return ''
  const lW = 48, bH = 22, w = 160, h = 64
  const totalW = w + lW, totalH = h + bH
  const axisY = h
  const min = Math.min(...closes), max = Math.max(...closes), range = max - min || 1
  const fmtSpark = (v: number) => v >= 1000 ? `$${v.toFixed(0)}` : v >= 100 ? `$${v.toFixed(1)}` : `$${v.toFixed(2)}`
  const dataY = (c: number) => h - 4 - ((c - min) / range) * (h - 16)
  const pts = closes.map((c, i) => {
    const x = lW + (i / (closes.length - 1)) * w
    return `${x.toFixed(2)},${dataY(c).toFixed(2)}`
  }).join(' ')
  const stroke = isUp ? '#4a7c59' : '#8b3a3c'
  const lc = 'rgba(122,112,104,0.55)'
  const tc = 'rgba(139,115,85,0.3)'
  const TICKS = [0, Math.floor((closes.length - 1) / 2), closes.length - 1]
  let tickSvg = '', dateLabelSvg = ''
  TICKS.forEach((dataIdx, ti) => {
    const x = lW + (dataIdx / (closes.length - 1)) * w
    const label = fmtSparkDate((dates || [])[dataIdx] || '')
    const anchor = ti === 0 ? 'start' : ti === TICKS.length - 1 ? 'end' : 'middle'
    let tx = x
    if (anchor === 'start') tx = Math.max(lW, x)
    if (anchor === 'end')   tx = Math.min(lW + w, x)
    tickSvg      += `<line x1="${x.toFixed(1)}" y1="${axisY}" x2="${x.toFixed(1)}" y2="${(axisY + 5).toFixed(1)}" stroke="${tc}" stroke-width="1.5"/>`
    dateLabelSvg += `<text x="${tx.toFixed(1)}" y="${(totalH - 2).toFixed(1)}" text-anchor="${anchor}" font-size="11" fill="${lc}" font-family="DM Sans,sans-serif">${label}</text>`
  })
  return `<svg viewBox="0 0 ${totalW} ${totalH}" preserveAspectRatio="none" class="h-full w-full">
    <text x="0" y="13" font-size="12" fill="${lc}" font-family="DM Sans,sans-serif">${fmtSpark(max)}</text>
    <text x="0" y="${axisY - 2}" font-size="12" fill="${lc}" font-family="DM Sans,sans-serif">${fmtSpark(min)}</text>
    <line x1="${lW}" y1="2" x2="${lW}" y2="${axisY}" stroke="rgba(122,112,104,0.15)" stroke-width="1"/>
    <polyline fill="none" stroke="${stroke}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" points="${pts}" />
    <line x1="${lW}" y1="${axisY}" x2="${lW + w}" y2="${axisY}" stroke="${tc}" stroke-width="1"/>
    ${tickSvg}${dateLabelSvg}
  </svg>`
}

// ── Stock Card ────────────────────────────────────────────────────────────────
function StockCard({ symbol, onRemove }: { symbol: string; onRemove: (s: string) => void }) {
  const navigate = useNavigate()
  const [data, setData] = useState<StockData | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    async function hydrate() {
      try {
        const [quoteRes, seriesRes] = await Promise.all([
          fetch(`${API_BASE_URL}/api/stocks/quotes?symbols=${encodeURIComponent(symbol)}`),
          fetch(`${API_BASE_URL}/api/stocks/time-series?symbol=${encodeURIComponent(symbol)}&interval=1hour&outputsize=28`)
        ])
        const quoteJson: Record<string, StockQuote> = await quoteRes.json()
        const quote = quoteJson[symbol] || quoteJson
        const seriesJson = await seriesRes.json()
        const values: SeriesItem[] = Array.isArray(seriesJson.values) ? seriesJson.values : []
        const closes = values.map(i => toNumber(i.close)).filter(Number.isFinite)
        const dates  = values.map(i => i.timestamp || i.datetime || i.date || '')
        const sc = getSeriesChange(closes)
        const isUp = sc ? sc.isUp : toNumber(quote.change) >= 0
        setData({
          symbol,
          name: quote.name ? `${quote.name} (${symbol})` : symbol,
          price: sc ? toCurrency(sc.lastClose) : toCurrency(quote.close || quote.previous_close || 0),
          delta: sc
            ? formatDelta(sc.change, sc.percent, isUp)
            : formatDelta(toNumber(quote.change), toNumber(quote.percent_change), isUp),
          isUp,
          closes,
          dates,
        })
      } catch {
        setError(true)
      }
    }
    hydrate()
  }, [symbol])

  const isUp = data?.isUp ?? true

  return (
    <div
      onClick={() => navigate(`/stock?symbol=${encodeURIComponent(symbol)}`)}
      className="glass-card fade-up"
      style={{
        position: 'relative',
        display: 'grid',
        gridTemplateColumns: '1fr',
        gap: '14px',
        padding: '20px 22px',
        borderRadius: '14px',
        cursor: 'pointer',
        transition: 'box-shadow 0.18s, border-color 0.18s, transform 0.18s',
      }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLElement).style.transform = 'translateY(-1px)'
        ;(e.currentTarget as HTMLElement).style.boxShadow = 'var(--shadow-lg)'
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLElement).style.transform = ''
        ;(e.currentTarget as HTMLElement).style.boxShadow = ''
      }}
    >
      {/* Desktop layout via inline grid */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '16px' }}>
        {/* Name */}
        <div style={{ flex: '1 1 180px', minWidth: 0 }}>
          <p
            style={{
              fontFamily: '"Cormorant Garamond", Georgia, serif',
              fontSize: '1.5rem',
              fontWeight: 400,
              color: 'var(--ink)',
              margin: 0,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {data?.name ?? symbol}
          </p>
        </div>

        {/* Price */}
        <div style={{ flex: '0 0 auto' }}>
          <p
            style={{
              fontFamily: '"Cormorant Garamond", Georgia, serif',
              fontSize: '1.8rem',
              fontWeight: 400,
              color: isUp ? 'var(--ok)' : 'var(--no)',
              margin: 0,
              letterSpacing: '-0.01em',
            }}
          >
            {data?.price ?? '$--.--'}
          </p>
        </div>

        {/* Delta */}
        <div style={{ flex: '0 0 auto', display: 'flex', alignItems: 'center', gap: '5px' }}>
          {isUp
            ? <TrendingUp size={14} style={{ color: 'var(--ok)', flexShrink: 0 }} />
            : <TrendingDown size={14} style={{ color: 'var(--no)', flexShrink: 0 }} />
          }
          <span style={{ fontSize: '0.82rem', fontWeight: 400, color: isUp ? 'var(--ok)' : 'var(--no)', whiteSpace: 'nowrap' }}>
            {error ? 'Data unavailable' : (data?.delta ?? 'Loading…')}
          </span>
        </div>

        {/* Sparkline */}
        <div
          className="glass-slot"
          style={{ flex: '0 0 180px', height: '64px', borderRadius: '8px', overflow: 'hidden' }}
          dangerouslySetInnerHTML={{
            __html: data && data.closes.length > 1
              ? renderSparklineSvg(data.closes, data.dates, data.isUp)
              : ''
          }}
        />

        {/* Navigate hint */}
        <ChevronRight size={16} style={{ color: 'var(--mist)', flexShrink: 0 }} />
      </div>

      {/* Remove button */}
      <button
        onClick={e => { e.stopPropagation(); onRemove(symbol) }}
        className="btn-icon"
        aria-label={`Remove ${symbol}`}
        style={{
          position: 'absolute', top: '14px', right: '14px',
          width: '28px', height: '28px', borderRadius: '50%',
          background: 'transparent',
          border: '1px solid var(--border)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'pointer',
          color: 'var(--mist)',
          transition: 'background 0.15s, color 0.15s, border-color 0.15s',
        }}
        onMouseEnter={e => {
          const el = e.currentTarget
          el.style.background = 'rgba(139,58,60,0.10)'
          el.style.color = 'var(--no)'
          el.style.borderColor = 'rgba(139,58,60,0.3)'
        }}
        onMouseLeave={e => {
          const el = e.currentTarget
          el.style.background = 'transparent'
          el.style.color = 'var(--mist)'
          el.style.borderColor = 'var(--border)'
        }}
      >
        <X size={13} />
      </button>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function WatchlistPage() {
  const navigate = useNavigate()
  const [session, setSession] = useState<Session | null>(null)
  const [stocks, setStocks] = useState<string[]>([])
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<SearchResult[]>([])
  const [searchStatus, setSearchStatus] = useState('')
  const [activeIdx, setActiveIdx] = useState(-1)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const searchPanelRef = useRef<HTMLDivElement>(null)
  const searchBtnRef = useRef<HTMLButtonElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    sb.auth.getSession().then(({ data: { session } }) => {
      if (!session) { navigate('/'); return }
      setSession(session)
      loadWatchlist(session)
    })
    const { data: { subscription } } = sb.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT') { navigate('/'); return }
      setSession(session)
    })
    return () => subscription.unsubscribe()
  }, [navigate])

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (
        searchPanelRef.current && !searchPanelRef.current.contains(e.target as Node) &&
        searchBtnRef.current  && !searchBtnRef.current.contains(e.target as Node)
      ) setSearchOpen(false)
    }
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [])

  async function apiFetch(path: string, options: RequestInit = {}) {
    const { data } = await sb.auth.getSession()
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    }
    if (data.session?.access_token) headers['Authorization'] = 'Bearer ' + data.session.access_token
    return fetch(API_BASE_URL + path, { ...options, headers })
  }

  async function loadWatchlist(sess: Session) {
    try {
      const res = await fetch(API_BASE_URL + '/stocks', {
        headers: { 'Authorization': 'Bearer ' + sess.access_token, 'Content-Type': 'application/json' }
      })
      if (!res.ok) return
      const data = await res.json()
      const list: { ticker_name: string }[] = Array.isArray(data) ? data : (data.stocks || [])
      setStocks(list.map(s => s.ticker_name.toUpperCase()))
    } catch {}
  }

  function addStock(symbol: string) {
    const normalized = symbol.trim().toUpperCase()
    if (!normalized || stocks.includes(normalized)) return
    setStocks(prev => [...prev, normalized])
    apiFetch('/stocks', { method: 'POST', body: JSON.stringify({ ticker_name: normalized }) }).catch(() => {})
  }

  function removeStock(symbol: string) {
    setStocks(prev => prev.filter(s => s !== symbol))
    apiFetch(`/stocks/${encodeURIComponent(symbol)}`, { method: 'DELETE' }).catch(() => {})
  }

  const searchStocks = useCallback(async (q: string) => {
    const cleaned = q.trim()
    if (!cleaned) { setSuggestions([]); setSearchStatus(''); return }
    setSearchStatus('Searching…')
    try {
      const res = await fetch(`${API_BASE_URL}/api/stocks/search?query=${encodeURIComponent(cleaned)}`)
      if (!res.ok) throw new Error()
      const results: SearchResult[] = await res.json()
      setSuggestions(results)
      setSearchStatus(results.length ? '' : 'No results.')
      setActiveIdx(results.length ? 0 : -1)
    } catch {
      setSuggestions([])
      setSearchStatus('Search unavailable.')
    }
  }, [])

  function handleSearchInput(e: React.ChangeEvent<HTMLInputElement>) {
    setQuery(e.target.value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => searchStocks(e.target.value), 250)
  }

  function selectSuggestion(symbol: string) {
    addStock(symbol)
    setQuery(''); setSuggestions([]); setSearchStatus(''); setSearchOpen(false)
  }

  function handleSearchKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActiveIdx(i => Math.min(i + 1, suggestions.length - 1)) }
    if (e.key === 'ArrowUp')   { e.preventDefault(); setActiveIdx(i => Math.max(i - 1, 0)) }
    if (e.key === 'Enter') {
      e.preventDefault()
      const sel = suggestions[activeIdx] || suggestions[0]
      if (sel) selectSuggestion(sel.symbol)
    }
  }

  return (
    <main
      style={{
        minHeight: '100vh',
        background: 'var(--cream)',
        fontFamily: '"DM Sans", system-ui, sans-serif',
        color: 'var(--ink-soft)',
      }}
    >
      {/* Header */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '18px 32px',
          borderBottom: '1px solid var(--border)',
          background: 'rgba(249,247,245,0.94)',
          backdropFilter: 'blur(16px)',
          position: 'sticky',
          top: 0,
          zIndex: 30,
        }}
      >
        <span
          style={{
            fontFamily: '"Cormorant Garamond", Georgia, serif',
            fontSize: '1.6rem',
            fontWeight: 400,
            color: 'var(--ink)',
            letterSpacing: '-0.01em',
          }}
        >
          Consilium
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          {session?.user?.email && (
            <span style={{ fontSize: '0.72rem', color: 'var(--mist)', display: 'none' }} className="sm:block">
              {session.user.email}
            </span>
          )}
          <button
            onClick={async () => { await sb.auth.signOut(); navigate('/') }}
            className="btn btn-secondary"
            style={{ padding: '8px 16px', gap: '7px', fontSize: '0.78rem' }}
          >
            <LogOut size={13} />
            Sign out
          </button>
        </div>
      </header>

      {/* Page body */}
      <div style={{ maxWidth: '820px', margin: '0 auto', padding: '32px 24px 64px' }}>

        {/* Page title + action bar */}
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: '28px' }}>
          <div>
            <p className="section-label">Portfolio</p>
            <h1
              style={{
                fontFamily: '"Cormorant Garamond", Georgia, serif',
                fontSize: '2.2rem',
                fontWeight: 300,
                color: 'var(--ink)',
                margin: 0,
                letterSpacing: '-0.02em',
              }}
            >
              Watchlist
            </h1>
          </div>

          {/* Add stock */}
          <div style={{ position: 'relative' }}>
            <button
              ref={searchBtnRef}
              onClick={() => { setSearchOpen(v => !v); setTimeout(() => inputRef.current?.focus(), 50) }}
              className="btn btn-primary"
              style={{ gap: '7px', padding: '10px 18px', fontSize: '0.8rem' }}
            >
              <Plus size={15} />
              Add stock
            </button>

            {searchOpen && (
              <div
                ref={searchPanelRef}
                className="timeframe-menu fade-up"
                style={{
                  position: 'absolute',
                  right: 0,
                  top: 'calc(100% + 10px)',
                  width: 'min(92vw, 22rem)',
                  borderRadius: '14px',
                  padding: '18px',
                  zIndex: 40,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                  <Search size={14} style={{ color: 'var(--mist)' }} />
                  <span className="section-label" style={{ marginBottom: 0 }}>Search stocks</span>
                </div>
                <input
                  ref={inputRef}
                  type="text"
                  value={query}
                  onChange={handleSearchInput}
                  onKeyDown={handleSearchKeyDown}
                  placeholder="Ticker or company name"
                  autoComplete="off"
                  className="input-field"
                  style={{ marginBottom: '10px' }}
                />
                {searchStatus && (
                  <p style={{ fontSize: '0.72rem', color: 'var(--mist)', marginBottom: '8px' }}>{searchStatus}</p>
                )}
                <div style={{ maxHeight: '280px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  {suggestions.length === 0 && query.trim() && !searchStatus.includes('Searching') && (
                    <p style={{ fontSize: '0.76rem', color: 'var(--mist)', padding: '8px 0' }}>No matches found.</p>
                  )}
                  {suggestions.map((item, i) => (
                    <button
                      key={item.symbol}
                      onClick={() => selectSuggestion(item.symbol)}
                      style={{
                        width: '100%',
                        background: i === activeIdx ? 'rgba(139,115,85,0.08)' : 'transparent',
                        border: `1px solid ${i === activeIdx ? 'rgba(139,115,85,0.3)' : 'var(--border)'}`,
                        borderRadius: '10px',
                        padding: '10px 12px',
                        textAlign: 'left',
                        cursor: 'pointer',
                        transition: 'background 0.12s, border-color 0.12s',
                      }}
                    >
                      <div style={{ fontSize: '0.82rem', fontWeight: 500, color: 'var(--ink)' }}>{item.symbol}</div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--mist)', marginTop: '2px' }}>
                        {[item.name, item.exchange].filter(Boolean).join(' · ')}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Stock list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {stocks.length === 0 ? (
            <div
              className="glass-slot fade-up"
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: '16px',
                padding: '64px 32px',
                textAlign: 'center',
                minHeight: '260px',
              }}
            >
              <Plus size={28} style={{ color: 'var(--mist)', marginBottom: '16px', opacity: 0.6 }} />
              <p
                style={{
                  fontFamily: '"Cormorant Garamond", Georgia, serif',
                  fontSize: '1.4rem',
                  fontWeight: 300,
                  color: 'var(--stone)',
                  margin: 0,
                }}
              >
                Add a stock to begin
              </p>
              <p style={{ fontSize: '0.78rem', color: 'var(--mist)', marginTop: '8px' }}>
                Use the button above to search and add stocks to your watchlist.
              </p>
            </div>
          ) : (
            stocks.map(symbol => (
              <StockCard key={symbol} symbol={symbol} onRemove={removeStock} />
            ))
          )}
        </div>
      </div>
    </main>
  )
}