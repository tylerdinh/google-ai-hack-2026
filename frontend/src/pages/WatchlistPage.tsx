import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { sb } from '../lib/supabase'
import type { Session } from '@supabase/supabase-js'

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
  return `${isUp ? '▲' : '▼'} ${signedValue(change)} ${isUp ? '▲' : '▼'} ${signedPercent(percent)}`
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
  const stroke = isUp ? '#4fc329' : '#e35658'
  const lc = 'rgba(161,161,170,0.6)'
  const tc = 'rgba(174,125,183,0.38)'
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
    dateLabelSvg += `<text x="${tx.toFixed(1)}" y="${(totalH - 2).toFixed(1)}" text-anchor="${anchor}" font-size="11" fill="${lc}" font-family="Lexend,sans-serif">${label}</text>`
  })
  return `<svg viewBox="0 0 ${totalW} ${totalH}" preserveAspectRatio="none" class="h-full w-full">
    <text x="0" y="13" font-size="12" fill="${lc}" font-family="Lexend,sans-serif">${fmtSpark(max)}</text>
    <text x="0" y="${axisY - 2}" font-size="12" fill="${lc}" font-family="Lexend,sans-serif">${fmtSpark(min)}</text>
    <line x1="${lW}" y1="2" x2="${lW}" y2="${axisY}" stroke="rgba(122,90,137,0.18)" stroke-width="1"/>
    <polyline fill="none" stroke="${stroke}" stroke-width="2.6" points="${pts}" />
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
          dates
        })
      } catch {
        setError(true)
      }
    }
    hydrate()
  }, [symbol])

  const trendCls = data ? (data.isUp ? 'text-success' : 'text-danger') : 'text-success'

  return (
    <div
      onClick={() => navigate(`/stock?symbol=${encodeURIComponent(symbol)}`)}
      className="glass-card relative grid w-full cursor-pointer grid-cols-1 items-center gap-2 rounded-2xl px-4 py-4 transition hover:-translate-y-px hover:border-lavender/80 sm:grid-cols-[1.4fr_1fr_1fr_190px] sm:gap-3 sm:px-5 sm:py-4"
    >
      <span className="font-display text-2xl text-zinc-100 sm:text-3xl">{data?.name ?? symbol}</span>
      <span className={`text-3xl font-semibold sm:text-4xl ${trendCls}`}>
        {data?.price ?? '$--.--'}
      </span>
      <span className={`whitespace-nowrap text-lg font-semibold sm:text-2xl ${trendCls}`}>
        {error ? 'Data unavailable' : (data?.delta ?? 'Loading…')}
      </span>
      <span
        className="glass-slot h-20 w-full rounded-lg"
        dangerouslySetInnerHTML={{
          __html: data && data.closes.length > 1
            ? renderSparklineSvg(data.closes, data.dates, data.isUp)
            : ''
        }}
      />
      <button
        onClick={e => { e.stopPropagation(); onRemove(symbol) }}
        className="absolute right-3 top-3 flex h-6 w-6 items-center justify-center rounded-full bg-white/5 text-xs text-zinc-500 transition hover:bg-danger/20 hover:text-danger sm:right-4 sm:top-4"
      >✕</button>
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

  // ── Auth
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

  // ── Close search on outside click
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
    const headers: Record<string, string> = { 'Content-Type': 'application/json', ...(options.headers as Record<string, string>) }
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
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-6 pb-10 pt-0 font-body text-white sm:pb-12">
      <header className="relative left-1/2 mb-3 w-screen -translate-x-1/2 flex items-center justify-between gap-4 rounded-b-xl border-b border-panelBorder/25 bg-[#23182f]/95 px-6 py-4 shadow-[0_8px_24px_rgba(0,0,0,0.18)] sm:px-8">
        <h1 className="font-display text-4xl leading-tight text-lavender sm:text-5xl">Consilium</h1>
        <div className="flex items-center gap-3">
          {session?.user?.email && (
            <span className="hidden text-xs text-zinc-400 sm:block">{session.user.email}</span>
          )}
          <button
            onClick={async () => { await sb.auth.signOut(); navigate('/') }}
            className="rounded-full border border-panelBorder/70 bg-white/5 px-4 py-2 text-sm font-semibold text-lavender transition hover:border-lavender/80"
          >Log out</button>
        </div>
      </header>

      {/* Search button + panel */}
      <div className="mb-6 flex justify-end">
        <div className="relative">
          <button ref={searchBtnRef} onClick={() => { setSearchOpen(v => !v); setTimeout(() => inputRef.current?.focus(), 50) }}
            className="glass-card flex h-12 w-12 items-center justify-center rounded-full text-3xl leading-none text-lavender transition hover:border-lavender/80">
            <span className="-translate-y-[3px]">+</span>
          </button>

          {searchOpen && (
            <div ref={searchPanelRef} className="absolute right-0 top-14 z-20 w-[min(92vw,22rem)] rounded-2xl border border-panelBorder/70 bg-panel/95 p-3 shadow-glow backdrop-blur">
              <label className="mb-2 block text-sm font-semibold text-lavender/90">Search a stock</label>
              <input ref={inputRef} type="text" value={query} onChange={handleSearchInput}
                onKeyDown={handleSearchKeyDown} placeholder="Ticker or company name" autoComplete="off"
                className="w-full rounded-xl border border-panelBorder/70 bg-canvas/80 px-4 py-3 text-sm text-zinc-100 outline-none placeholder:text-zinc-400 focus:border-lavender" />
              {searchStatus && <div className="mt-2 text-xs text-zinc-400">{searchStatus}</div>}
              <div className="mt-2 max-h-72 overflow-auto space-y-2">
                {suggestions.length === 0 && query.trim() && !searchStatus.includes('Searching') && (
                  <div className="rounded-xl border border-dashed border-lavender/30 px-3 py-2 text-sm text-zinc-400">No matches found.</div>
                )}
                {suggestions.map((item, i) => (
                  <button key={item.symbol} onClick={() => selectSuggestion(item.symbol)}
                    className={`w-full rounded-xl border px-3 py-2 text-left transition ${i === activeIdx ? 'border-lavender bg-white/10 ring-1 ring-lavender/60' : 'border-panelBorder/70 bg-canvas/70 hover:border-lavender hover:bg-white/5'}`}>
                    <div className="text-sm font-semibold text-zinc-100">{item.symbol}</div>
                    <div className="text-xs text-zinc-400">{[item.name, item.exchange].filter(Boolean).join(' • ')}</div>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Stocks list */}
      <section className="flex flex-1 flex-col space-y-3">
        {stocks.length === 0 ? (
          <div className="glass-card flex flex-1 flex-col items-center justify-center rounded-2xl border border-dashed border-lavender/40 px-6 py-8 text-center text-zinc-300">
            <p className="font-display text-3xl text-lavender/90 sm:text-4xl">Click the + button to add a stock.</p>
          </div>
        ) : (
          stocks.map(symbol => (
            <StockCard key={symbol} symbol={symbol} onRemove={removeStock} />
          ))
        )}
      </section>
    </main>
  )
}