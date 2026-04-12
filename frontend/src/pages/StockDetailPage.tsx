import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { sb } from '../lib/supabase'
import type { Session } from '@supabase/supabase-js'
import {
  ArrowLeft,
  LogOut,
  TrendingUp,
  TrendingDown,
  ChevronDown,
  Check,
  Loader2,
  ArrowRight,
  BookOpen,
  BarChart2,
  Users,
  Save,
  ChevronUp,
  AlertCircle,
} from 'lucide-react'

const API_BASE_URL = (window as any).STOCK_API_BASE_URL || ''

// ── Types ─────────────────────────────────────────────────────────────────────
interface Candle { open: number; high: number; low: number; close: number; datetime: string }
interface Quote  { name?: string; close?: number; previous_close?: number; change?: number; percent_change?: number }
interface Analysis {
  created_at: string
  council_verdict?: string
  prompt?: string
  intent?: string
  advice?: string
  analysis_text?: string
  ticker_name?: string
}
type TimeframeKey = 'today' | 'lastWeek' | 'lastMonth' | 'lastYear'
const TIMEFRAME_CONFIG: Record<TimeframeKey, { label: string; interval: string; outputsize: number }> = {
  today:     { label: 'Today',      interval: '5min',  outputsize: 78 },
  lastWeek:  { label: 'Last week',  interval: '1hour', outputsize: 28 },
  lastMonth: { label: 'Last month', interval: '1day',  outputsize: 30 },
  lastYear:  { label: 'Last year',  interval: '1week', outputsize: 52 },
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function toNumber(v: unknown): number { const n = Number(v); return Number.isFinite(n) ? n : 0 }
function toCurrency(v: unknown) { return `$${toNumber(v).toFixed(2)}` }

function getSeriesChange(values: Array<{ close: unknown }>) {
  if (!Array.isArray(values) || values.length < 2) return null
  const closes = values.map(e => toNumber(e.close)).filter(Number.isFinite)
  if (closes.length < 2) return null
  const first = closes[0], last = closes[closes.length - 1]
  const change = last - first, percent = first ? (change / first) * 100 : 0
  return { lastClose: last, change, percent, isUp: change >= 0 }
}

function formatChartDate(dt: string, range: TimeframeKey, isFirstLabel: boolean): string {
  if (!dt) return ''
  const d = new Date(dt.replace(' ', 'T'))
  if (isNaN(d.getTime())) return ''
  const yr2 = String(d.getFullYear()).slice(2)
  switch (range) {
    case 'today':     return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
    case 'lastWeek':  return d.toLocaleDateString('en-US', { weekday: 'short', day: 'numeric' })
    case 'lastMonth': return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    case 'lastYear': {
      const mon = d.toLocaleDateString('en-US', { month: 'short' })
      return (d.getMonth() === 0 || isFirstLabel) ? `${mon} '${yr2}` : mon
    }
    default: return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }
}

function buildCandleSvg(candles: Candle[], range: TimeframeKey): string {
  if (!candles.length) return ''
  const W = 1200, H = 400
  const padL = 82, padR = 16, padT = 14, padB = 38
  const cW = W - padL - padR, cH = H - padT - padB
  const minLow  = Math.min(...candles.map(c => c.low))
  const maxHigh = Math.max(...candles.map(c => c.high))
  const priceRange = maxHigh - minLow || 1
  const margin = priceRange * 0.06
  const pMin = minLow - margin, pMax = maxHigh + margin, pRange = pMax - pMin
  const step = cW / candles.length
  const cw   = Math.max(4, step * 0.62)
  const px   = (i: number) => padL + step * i + step / 2
  const py   = (p: number) => padT + cH - ((p - pMin) / pRange) * cH
  const fmtP = (p: number) => p >= 1000 ? `$${p.toFixed(0)}` : p >= 100 ? `$${p.toFixed(1)}` : `$${p.toFixed(2)}`
  const axisY = padT + cH
  const lc = 'rgba(122,112,104,0.55)'
  const gc = 'rgba(122,112,104,0.10)'
  const ac = 'rgba(139,115,85,0.22)'

  let gridSvg = '', yLabelSvg = ''
  for (let i = 0; i <= 5; i++) {
    const price = pMin + (pRange * i / 5)
    const y = py(price)
    gridSvg   += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" stroke="${gc}" stroke-width="1" stroke-dasharray="4 4"/>`
    yLabelSvg += `<text x="${(padL - 7).toFixed(1)}" y="${(y + 5).toFixed(1)}" text-anchor="end" font-size="19" fill="${lc}" font-family="DM Sans,sans-serif">${fmtP(price)}</text>`
  }

  const axisLine = `<line x1="${padL}" y1="${axisY}" x2="${W - padR}" y2="${axisY}" stroke="${ac}" stroke-width="1"/>`
  let xTickSvg = '', xLabelSvg = ''
  const N_DATES = Math.min(5, candles.length)
  for (let i = 0; i < N_DATES; i++) {
    const idx = Math.round(i * (candles.length - 1) / Math.max(1, N_DATES - 1))
    const label = formatChartDate(candles[idx].datetime, range, i === 0)
    let x = px(idx)
    x = Math.max(padL, Math.min(W - padR, x))
    xTickSvg += `<line x1="${x.toFixed(1)}" y1="${axisY}" x2="${x.toFixed(1)}" y2="${(axisY + 7).toFixed(1)}" stroke="${ac}" stroke-width="1.5"/>`
    const anchor = i === 0 ? 'start' : i === N_DATES - 1 ? 'end' : 'middle'
    let tx = x
    if (anchor === 'start') tx = Math.max(padL, x)
    if (anchor === 'end')   tx = Math.min(W - padR, x)
    xLabelSvg += `<text x="${tx.toFixed(1)}" y="${(H - 6).toFixed(1)}" text-anchor="${anchor}" font-size="18" fill="${lc}" font-family="DM Sans,sans-serif">${label}</text>`
  }

  const candleSvg = candles.map((c, i) => {
    const x   = px(i)
    const top = Math.min(py(c.open), py(c.close))
    const bh  = Math.max(3, Math.abs(py(c.close) - py(c.open)))
    const col = c.close >= c.open ? '#4a7c59' : '#8b3a3c'
    return `<line x1="${x.toFixed(2)}" y1="${py(c.high).toFixed(2)}" x2="${x.toFixed(2)}" y2="${py(c.low).toFixed(2)}" stroke="${col}" stroke-width="1.5"/>
            <rect x="${(x - cw / 2).toFixed(2)}" y="${top.toFixed(2)}" width="${cw.toFixed(2)}" height="${bh.toFixed(2)}" fill="${col}" rx="1"/>`
  }).join('')

  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" class="h-full w-full">
    ${gridSvg}${axisLine}${candleSvg}${yLabelSvg}${xTickSvg}${xLabelSvg}
  </svg>`
}

function formatDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) +
         ' · ' + d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
}

function agentColor(name: string): string {
  const n = name.toLowerCase()
  if (n.includes('analyst'))  return 'var(--accent)'
  if (n.includes('diplomat')) return '#5a8a9f'
  if (n.includes('sentinel')) return 'var(--no)'
  if (n.includes('explorer')) return 'var(--ok)'
  return 'var(--accent)'
}

function extractBullets(snippet?: string, pageText?: string): string[] {
  const src = [snippet, pageText].filter(Boolean).join(' ')
  const sentences = src.match(/[^.!?]+[.!?]+/g) || [src]
  return sentences.slice(0, 2).map(s => s.trim())
}

interface SSEEvent { type: string; [key: string]: any }

// ── Analysis Output ───────────────────────────────────────────────────────────
function AnalysisOutput({ events }: { events: SSEEvent[] }) {
  const braveEvents   = events.filter(e => e.type === 'brave_fetching' || e.type === 'brave_result')
  const toolEvents    = events.filter(e => e.type === 'tool_call' || e.type === 'agent_status')
  const councilEvents = events.filter(e => ['council_thinking', 'council_vote', 'council_verdict', 'council_phase'].includes(e.type))
  const agentDone     = events.find(e => e.type === 'agent_done')
  const councilDone   = events.find(e => e.type === 'council_done')
  const intentEvt     = events.find(e => e.type === 'intent_classified')
  const doneEvt       = events.find(e => e.type === 'done')
  const errorEvt      = events.find(e => e.type === 'error')
  const phaseEvents   = events.filter(e => e.type === 'phase')
  const bravePhase    = phaseEvents.find(e => e.phase === 'brave')
  const agentPhase    = phaseEvents.find(e => e.phase === 'agent')
  const councilPhase  = phaseEvents.find(e => e.phase === 'council')

  const [showFull, setShowFull] = useState(false)

  const braveMap = new Map<number, SSEEvent>()
  for (const e of braveEvents) {
    if (e.type === 'brave_result') braveMap.set(e.rank, e)
    else if (!braveMap.has(e.rank)) braveMap.set(e.rank, e)
  }
  const braveItems = Array.from(braveMap.values())

  const chartTools = new Set(['get_price_chart', 'get_technical_chart'])
  const segments: Array<{ type: 'text'; content: string } | { type: 'image'; data: string }> = []
  if (agentDone) {
    const imgQueue = [...(agentDone.images || [])]
    for (const msg of (agentDone.message_history || [])) {
      if (msg.kind !== 'response') continue
      const text = (msg.parts || []).filter((p: any) => p.part_kind === 'text' && p.content?.trim()).map((p: any) => p.content.trim()).join('\n\n')
      if (text) segments.push({ type: 'text', content: text })
      for (const p of (msg.parts || [])) {
        if (p.part_kind === 'tool-call' && chartTools.has(p.tool_name) && imgQueue.length) {
          segments.push({ type: 'image', data: imgQueue.shift().data })
        }
      }
    }
  }
  const hasImages = segments.some(s => s.type === 'image')

  return (
    <div>
      {/* Intent badge */}
      {intentEvt && (
        <div
          className={`intent-badge fade-up ${intentEvt.is_binary ? 'binary' : 'open'}`}
          style={{ marginBottom: '20px' }}
        >
          {intentEvt.is_binary
            ? <><Users size={12} /> Decision — council will deliberate</>
            : <><BarChart2 size={12} /> Open analysis</>
          }
        </div>
      )}

      {/* Brave research */}
      {bravePhase && (
        <>
          <div className={`phase-row fade-up ${agentPhase || agentDone ? 'done' : ''}`}>
            {agentPhase || agentDone
              ? <><Check size={13} className="icon-check" /><span>Web Research Complete</span></>
              : <><div className="spinner" /><span>Web Research</span></>
            }
          </div>
          <div className="brave-grid">
            {braveItems.map(e => {
              const isResult = e.type === 'brave_result'
              const bullets = isResult ? extractBullets(e.snippet, e.page_text) : []
              return (
                <div key={e.rank} className={`site-box fade-up ${isResult ? '' : 'loading'}`}>
                  <div className="site-rank">#{e.rank}</div>
                  <div className="site-title">
                    {isResult
                      ? <a href={e.url} target="_blank" rel="noreferrer">{e.title || 'Untitled'}</a>
                      : (e.title || 'Loading…')}
                  </div>
                  <div className="site-url">{e.url}</div>
                  {isResult && (
                    <ul className="site-bullets">
                      {bullets.map((b, i) => <li key={i}>{b}</li>)}
                    </ul>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}

      {/* Agent phase */}
      {agentPhase && (
        <>
          <div className={`phase-row fade-up ${agentDone ? 'done' : ''}`}>
            {agentDone
              ? <><Check size={13} className="icon-check" /><span>AI Analysis Complete</span></>
              : <><div className="spinner" /><span>AI Analysis</span></>
            }
          </div>
          <div style={{ marginBottom: '12px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
            {toolEvents.map((e, i) => (
              <div key={i} className="agent-step done fade-up">
                <span className="step-check"><Check size={12} /></span>
                <span>{e.message || e.label}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Agent done */}
      {agentDone && (
        <>
          <div className="phase-row done fade-up">
            <Check size={13} className="icon-check" />
            <span>Research Summary</span>
          </div>
          {(agentDone.bullets || []).length > 0 && (
            <div className="bullet-card fade-up">
              {(agentDone.bullets as string[]).map((b, i) => (
                <div key={i} className="bullet-item">
                  <span className="bullet-dash"><BookOpen size={12} style={{ color: 'var(--accent)' }} /></span>
                  {b}
                </div>
              ))}
              {!agentDone.is_binary && agentDone.direct_answer && (
                <>
                  <hr className="direct-answer-divider" />
                  <div className="direct-answer">{agentDone.direct_answer}</div>
                </>
              )}
            </div>
          )}
          {(segments.length > 0 || agentDone.analysis_text) && (
            <>
              <button
                className="analysis-toggle"
                onClick={() => setShowFull(v => !v)}
              >
                {showFull || hasImages || !agentDone.bullets?.length
                  ? <><ChevronUp size={13} /> Hide full analysis</>
                  : <><ChevronDown size={13} /> View full analysis</>
                }
              </button>
              <div className={`full-analysis ${showFull || hasImages || !agentDone.bullets?.length ? '' : 'hidden'}`}>
                {segments.length > 0
                  ? segments.map((seg, i) =>
                      seg.type === 'text'
                        ? <div key={i} className="analysis-para">{seg.content}</div>
                        : <img key={i} className="inline-chart" src={`data:image/png;base64,${seg.data}`} alt="chart" />
                    )
                  : <span>{agentDone.analysis_text}</span>
                }
              </div>
            </>
          )}
        </>
      )}

      {/* Council */}
      {councilPhase && (
        <>
          <div className={`phase-row fade-up ${councilDone ? 'done' : ''}`}>
            {councilDone
              ? <><Check size={13} className="icon-check" /><span>Council Complete</span></>
              : <><div className="spinner" /><span>Council Deliberation</span></>
            }
          </div>
          <div style={{ marginTop: '8px' }}>
            {councilEvents.map((e, i) => {
              if (e.type === 'council_phase') {
                return (
                  <p
                    key={i}
                    style={{
                      fontSize: '0.62rem', fontWeight: 500, letterSpacing: '0.1em',
                      textTransform: 'uppercase', color: 'var(--mist)',
                      margin: '18px 0 8px',
                    }}
                  >
                    {e.message}
                  </p>
                )
              }
              if (e.type === 'council_thinking') {
                const color = agentColor(e.agent)
                return (
                  <div key={i} className="council-bubble fade-up" style={{ borderLeft: `2px solid ${color}` }}>
                    <div className="cb-header">
                      <div className="cb-avatar" style={{ background: color, color: 'var(--cream)' }}>
                        {e.agent[0].toUpperCase()}
                      </div>
                      <div className="cb-name" style={{ color }}>{e.agent}</div>
                    </div>
                    <div className="cb-content">{e.content}</div>
                  </div>
                )
              }
              if (e.type === 'council_vote') {
                const color = agentColor(e.agent)
                return (
                  <div key={i} className="vote-box fade-up" style={{ borderLeft: `2px solid ${color}` }}>
                    <div className={`vote-badge ${e.vote}`}>{e.vote}</div>
                    <div>
                      <div className="vote-agent" style={{ color }}>{e.agent}</div>
                      <div className="vote-reasoning">{e.reasoning}</div>
                    </div>
                  </div>
                )
              }
              if (e.type === 'council_verdict') {
                return (
                  <div key={i} className={`verdict-card ${e.decision} fade-up`}>
                    <div className="verdict-label">Council Verdict</div>
                    <div className={`verdict-decision ${e.decision}`}>
                      {(e.decision || '').charAt(0).toUpperCase() + (e.decision || '').slice(1)}
                    </div>
                    <div className="verdict-tally">{e.approve} approve · {e.reject} reject</div>
                  </div>
                )
              }
              return null
            })}
          </div>
        </>
      )}

      {doneEvt?.analysis_id && (
        <div className="saved-badge fade-up">
          <Save size={12} />
          Analysis saved to history
        </div>
      )}

      {errorEvt && (
        <div
          className="fade-up"
          style={{
            display: 'flex', alignItems: 'flex-start', gap: '10px',
            background: 'rgba(139,58,60,0.07)', border: '1px solid rgba(139,58,60,0.22)',
            borderRadius: '10px', padding: '14px 16px', marginTop: '12px',
          }}
        >
          <AlertCircle size={15} style={{ color: 'var(--no)', flexShrink: 0, marginTop: '1px' }} />
          <span style={{ fontSize: '0.78rem', color: 'var(--no)', lineHeight: 1.5 }}>
            {errorEvt.detail || 'An error occurred.'}
          </span>
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function StockDetailPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const symbol = (searchParams.get('symbol') || 'AAPL').toUpperCase()

  const [session, setSession] = useState<Session | null>(null)
  const [summary, setSummary] = useState<{ name: string; price: string; delta: string; isUp: boolean } | null>(null)
  const [chartSvg, setChartSvg] = useState('Loading chart…')
  const [range, setRange] = useState<TimeframeKey>('lastWeek')
  const [menuOpen, setMenuOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [sseEvents, setSseEvents] = useState<SSEEvent[]>([])
  const [showOutput, setShowOutput] = useState(false)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [history, setHistory] = useState<Analysis[]>([])
  const [expandedHistory, setExpandedHistory] = useState<Set<number>>(new Set())
  const outputRef = useRef<HTMLElement>(null)
  const audioQueueRef = useRef<Array<{ b64: string; onStart?: () => void; onEnd?: () => void }>>([])
  const audioPlayingRef = useRef(false)

  useEffect(() => {
    const { data: { subscription } } = sb.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT') { navigate('/'); return }
      if (session) {
        setSession(session)
        if (event === 'INITIAL_SESSION' || event === 'SIGNED_IN') {
          loadHistory(session)
        }
      } else if (event === 'INITIAL_SESSION') {
        navigate('/')
      }
    })
    return () => subscription.unsubscribe()
  }, [navigate])

  useEffect(() => {
    const handler = () => setMenuOpen(false)
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [])

  useEffect(() => {
    async function load() {
      try {
        const quoteRes = await fetch(`${API_BASE_URL}/api/stocks/quotes?symbols=${encodeURIComponent(symbol)}`)
        const quoteJson = await quoteRes.json()
        const quote: Quote = quoteJson[symbol] || quoteJson
        const cfg = TIMEFRAME_CONFIG[range]
        const seriesRes = await fetch(`${API_BASE_URL}/api/stocks/time-series?symbol=${encodeURIComponent(symbol)}&interval=${cfg.interval}&outputsize=${cfg.outputsize}`)
        const seriesJson = await seriesRes.json()
        const values = Array.isArray(seriesJson.values) ? seriesJson.values : []
        const sc = getSeriesChange(values)
        const isUp = sc ? sc.isUp : toNumber(quote.change) >= 0
        const change = sc ? sc.change : toNumber(quote.change)
        const percent = sc ? sc.percent : toNumber(quote.percent_change)
        setSummary({
          name: quote.name ? `${quote.name} (${symbol})` : symbol,
          price: toCurrency(sc ? sc.lastClose : quote.close || quote.previous_close || 0),
          delta: `$${Math.abs(change).toFixed(2)}  ${Math.abs(percent).toFixed(2)}%`,
          isUp,
        })
        const candles: Candle[] = values.map((e: any) => ({
          open: toNumber(e.open), high: toNumber(e.high), low: toNumber(e.low), close: toNumber(e.close),
          datetime: e.timestamp || e.datetime || e.date || ''
        }))
        setChartSvg(buildCandleSvg(candles, range))
      } catch {
        setSummary({ name: symbol, price: 'Unavailable', delta: 'Check backend.', isUp: false })
        setChartSvg('Unable to load chart data.')
      }
    }
    load()
  }, [symbol])

  async function loadChart(rangeKey: TimeframeKey) {
    setRange(rangeKey)
    setChartSvg('Loading chart…')
    try {
      const cfg = TIMEFRAME_CONFIG[rangeKey]
      const res = await fetch(`${API_BASE_URL}/api/stocks/time-series?symbol=${encodeURIComponent(symbol)}&interval=${cfg.interval}&outputsize=${cfg.outputsize}`)
      const data = await res.json()
      const values = Array.isArray(data.values) ? data.values : []
      const candles: Candle[] = values.map((e: any) => ({
        open: toNumber(e.open), high: toNumber(e.high), low: toNumber(e.low), close: toNumber(e.close),
        datetime: e.timestamp || e.datetime || e.date || ''
      }))
      setChartSvg(buildCandleSvg(candles, rangeKey))
    } catch {
      setChartSvg('Unable to load chart.')
    }
  }

  async function loadHistory(sess: Session) {
    try {
      const res = await fetch(API_BASE_URL + '/analyses', {
        headers: { 'Authorization': 'Bearer ' + sess.access_token, 'Content-Type': 'application/json' }
      })
      if (!res.ok) return
      const data = await res.json()
      const all: Analysis[] = Array.isArray(data) ? data : (data.analyses || [])
      setHistory(all.filter(a => (a.ticker_name || '').toUpperCase() === symbol))
    } catch {}
  }

  function enqueueAudio(b64: string, onStart?: () => void, onEnd?: () => void) {
    if (!b64) return
    audioQueueRef.current.push({ b64, onStart, onEnd })
    if (!audioPlayingRef.current) drainAudio()
  }
  async function drainAudio() {
    if (!audioQueueRef.current.length) { audioPlayingRef.current = false; return }
    audioPlayingRef.current = true
    const { b64, onStart, onEnd } = audioQueueRef.current.shift()!
    try {
      const ctx = new (window.AudioContext || (window as any).webkitAudioContext)()
      const raw = atob(b64)
      const buf = new Uint8Array(raw.length)
      for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i)
      const decoded = await ctx.decodeAudioData(buf.buffer)
      const src = ctx.createBufferSource()
      src.buffer = decoded; src.connect(ctx.destination)
      onStart?.()
      src.onended = () => { onEnd?.(); ctx.close(); drainAudio() }
      src.start()
    } catch { onEnd?.(); drainAudio() }
  }

  async function handleAnalyze(e: React.FormEvent) {
    e.preventDefault()
    if (isAnalyzing || !query.trim()) return
    setIsAnalyzing(true)
    setSseEvents([])
    setShowOutput(true)
    audioQueueRef.current = []
    audioPlayingRef.current = false
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (session?.access_token) headers['Authorization'] = 'Bearer ' + session.access_token
      const res = await fetch(API_BASE_URL + '/research/analyze', {
        method: 'POST', headers,
        body: JSON.stringify({ ticker: symbol, intent: query })
      })
      if (!res.ok) { setSseEvents([{ type: 'error', detail: `Server error ${res.status}` }]); return }
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()!
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const d: SSEEvent = JSON.parse(line.slice(6))
            setSseEvents(prev => [...prev, d])
            if (d.type === 'done' && d.analysis_id && session) loadHistory(session)
            if (['council_thinking', 'council_vote', 'council_verdict'].includes(d.type) && d.audio_b64) {
              enqueueAudio(d.audio_b64)
            }
          } catch {}
        }
      }
    } catch (err: any) {
      setSseEvents(prev => [...prev, { type: 'error', detail: err.message }])
    } finally {
      setIsAnalyzing(false)
    }
  }

  const isUp = summary?.isUp ?? true

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
            <span style={{ fontSize: '0.72rem', color: 'var(--mist)' }}>{session.user.email}</span>
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

      <div style={{ maxWidth: '820px', margin: '0 auto', padding: '28px 24px 64px' }}>

        {/* Back link */}
        <Link
          to="/stocks"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '0.76rem',
            color: 'var(--stone)',
            textDecoration: 'none',
            marginBottom: '24px',
            transition: 'color 0.15s',
          }}
          onMouseEnter={e => (e.currentTarget.style.color = 'var(--accent)')}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--stone)')}
        >
          <ArrowLeft size={14} />
          Back to watchlist
        </Link>

        {/* Summary */}
        {summary && (
          <section className="glass-card fade-up" style={{ padding: '24px 28px', marginBottom: '16px', borderRadius: '16px' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: '20px' }}>
              <div style={{ flex: '1 1 200px' }}>
                <p className="section-label" style={{ marginBottom: '6px' }}>{symbol}</p>
                <h2
                  style={{
                    fontFamily: '"Cormorant Garamond", Georgia, serif',
                    fontSize: '1.8rem',
                    fontWeight: 300,
                    color: 'var(--ink)',
                    margin: 0,
                    letterSpacing: '-0.015em',
                  }}
                >
                  {summary.name}
                </h2>
              </div>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: '20px', flexWrap: 'wrap' }}>
                <p
                  style={{
                    fontFamily: '"Cormorant Garamond", Georgia, serif',
                    fontSize: '2.4rem',
                    fontWeight: 400,
                    color: isUp ? 'var(--ok)' : 'var(--no)',
                    margin: 0,
                    letterSpacing: '-0.02em',
                    lineHeight: 1,
                  }}
                >
                  {summary.price}
                </p>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', paddingBottom: '4px' }}>
                  {isUp
                    ? <TrendingUp size={15} style={{ color: 'var(--ok)' }} />
                    : <TrendingDown size={15} style={{ color: 'var(--no)' }} />
                  }
                  <span style={{ fontSize: '0.88rem', color: isUp ? 'var(--ok)' : 'var(--no)', fontWeight: 400 }}>
                    {summary.delta}
                  </span>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Chart */}
        <section className="glass-card fade-up" style={{ marginBottom: '16px', borderRadius: '16px', overflow: 'hidden' }}>
          {/* Timeframe selector */}
          <div style={{ padding: '0', position: 'relative', display: 'inline-block' }}>
            <button
              onClick={e => { e.stopPropagation(); setMenuOpen(v => !v) }}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
                padding: '14px 20px',
                background: 'transparent',
                border: 'none',
                borderBottom: '1px solid var(--border)',
                borderRight: '1px solid var(--border)',
                cursor: 'pointer',
                fontSize: '0.78rem',
                fontWeight: 500,
                color: 'var(--stone-mid)',
                letterSpacing: '0.03em',
                transition: 'color 0.15s',
              }}
            >
              {TIMEFRAME_CONFIG[range].label}
              <ChevronDown size={13} style={{ color: 'var(--mist)' }} />
            </button>
            {menuOpen && (
              <div
                className="timeframe-menu fade-up"
                style={{
                  position: 'absolute',
                  left: 0,
                  top: '100%',
                  zIndex: 20,
                  borderRadius: '12px',
                  minWidth: '160px',
                  overflow: 'hidden',
                }}
              >
                {(Object.keys(TIMEFRAME_CONFIG) as TimeframeKey[]).map(key => (
                  <button
                    key={key}
                    onClick={() => { setMenuOpen(false); loadChart(key) }}
                    style={{
                      display: 'block',
                      width: '100%',
                      padding: '12px 18px',
                      textAlign: 'left',
                      background: key === range ? 'rgba(139,115,85,0.08)' : 'transparent',
                      border: 'none',
                      color: key === range ? 'var(--accent)' : 'var(--stone)',
                      fontSize: '0.8rem',
                      fontWeight: key === range ? 500 : 400,
                      cursor: 'pointer',
                      transition: 'background 0.12s',
                    }}
                    onMouseEnter={e => { if (key !== range) (e.currentTarget as HTMLElement).style.background = 'rgba(26,23,20,0.04)' }}
                    onMouseLeave={e => { if (key !== range) (e.currentTarget as HTMLElement).style.background = 'transparent' }}
                  >
                    {TIMEFRAME_CONFIG[key].label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Chart area */}
          <div
            style={{ height: '280px', padding: '16px' }}
            dangerouslySetInnerHTML={{ __html: chartSvg }}
          />
        </section>

        {/* Analysis form */}
        <section
          className="glass-card fade-up"
          style={{ padding: '20px 24px', marginBottom: '16px', borderRadius: '16px' }}
        >
          <p className="section-label" style={{ marginBottom: '14px' }}>Ask the council</p>
          <form onSubmit={handleAnalyze}>
            <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
              <textarea
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    e.currentTarget.form?.requestSubmit()
                  }
                }}
                rows={2}
                placeholder="What would you like analyzed?"
                className="input-field"
                style={{ flex: 1, resize: 'none', minHeight: '64px' }}
              />
              <button
                type="submit"
                disabled={isAnalyzing}
                className="btn btn-primary"
                style={{ flexShrink: 0, padding: '14px 20px', alignSelf: 'stretch' }}
              >
                {isAnalyzing
                  ? <Loader2 size={16} style={{ animation: 'spin 0.9s linear infinite' }} />
                  : <ArrowRight size={16} />
                }
              </button>
            </div>
          </form>
        </section>

        {/* History */}
        {history.length > 0 && (
          <section className="glass-card fade-up" style={{ padding: '20px 24px', marginBottom: '16px', borderRadius: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <p className="section-label" style={{ marginBottom: 0 }}>Past Analyses</p>
              <span style={{ fontSize: '0.68rem', color: 'var(--mist)' }}>{history.length} saved</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {history.map((a, i) => {
                const verdict = (a.council_verdict || '').toLowerCase()
                const vClass  = verdict === 'approved' ? 'approved' : verdict === 'rejected' ? 'rejected' : 'none'
                const expanded = expandedHistory.has(i)
                return (
                  <div
                    key={i}
                    className={`history-card ${expanded ? 'expanded' : ''}`}
                    onClick={() => setExpandedHistory(prev => {
                      const next = new Set(prev)
                      expanded ? next.delete(i) : next.add(i)
                      return next
                    })}
                  >
                    <div className="history-meta">
                      <span className="history-date">{formatDate(a.created_at)}</span>
                      {verdict && <span className={`history-verdict ${vClass}`}>{verdict || 'no vote'}</span>}
                      <span className="history-expand-icon">
                        {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                      </span>
                    </div>
                    <div className="history-prompt">{a.prompt || a.intent || ''}</div>
                    <div className="history-advice">{a.advice || a.analysis_text || ''}</div>
                  </div>
                )
              })}
            </div>
          </section>
        )}

        {/* Analysis output */}
        {showOutput && (
          <section
            ref={outputRef}
            className="analysis-shell fade-up"
            style={{ borderRadius: '16px', padding: '24px 28px', minHeight: '200px' }}
          >
            <AnalysisOutput events={sseEvents} />
          </section>
        )}
      </div>
    </main>
  )
}