import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { sb } from '../lib/supabase'
import type { Session } from '@supabase/supabase-js'

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
  today:     { label: 'Today',     interval: '5min',  outputsize: 78 },
  lastWeek:  { label: 'Last week', interval: '1hour', outputsize: 28 },
  lastMonth: { label: 'Last month',interval: '1day',  outputsize: 30 },
  lastYear:  { label: 'Last year', interval: '1week', outputsize: 52 },
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function toNumber(v: unknown): number { const n = Number(v); return Number.isFinite(n) ? n : 0 }
function toCurrency(v: unknown) { return `$${toNumber(v).toFixed(2)}` }
function signedValue(v: unknown) { return `$${Math.abs(toNumber(v)).toFixed(2)}` }
function signedPercent(v: unknown) { return `${Math.abs(toNumber(v)).toFixed(2)}%` }

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

  let gridSvg = '', yLabelSvg = ''
  for (let i = 0; i <= 5; i++) {
    const price = pMin + (pRange * i / 5)
    const y = py(price)
    gridSvg   += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" stroke="rgba(174,125,183,0.12)" stroke-width="1" stroke-dasharray="4 4"/>`
    yLabelSvg += `<text x="${(padL - 7).toFixed(1)}" y="${(y + 5).toFixed(1)}" text-anchor="end" font-size="19" fill="rgba(161,161,170,0.65)" font-family="Lexend,sans-serif">${fmtP(price)}</text>`
  }

  const axisLine = `<line x1="${padL}" y1="${axisY}" x2="${W - padR}" y2="${axisY}" stroke="rgba(174,125,183,0.22)" stroke-width="1"/>`
  let xTickSvg = '', xLabelSvg = ''
  const N_DATES = Math.min(5, candles.length)
  for (let i = 0; i < N_DATES; i++) {
    const idx = Math.round(i * (candles.length - 1) / Math.max(1, N_DATES - 1))
    const label = formatChartDate(candles[idx].datetime, range, i === 0)
    let x = px(idx)
    x = Math.max(padL, Math.min(W - padR, x))
    xTickSvg += `<line x1="${x.toFixed(1)}" y1="${axisY}" x2="${x.toFixed(1)}" y2="${(axisY + 7).toFixed(1)}" stroke="rgba(174,125,183,0.45)" stroke-width="1.5"/>`
    const anchor = i === 0 ? 'start' : i === N_DATES - 1 ? 'end' : 'middle'
    let tx = x
    if (anchor === 'start') tx = Math.max(padL, x)
    if (anchor === 'end')   tx = Math.min(W - padR, x)
    xLabelSvg += `<text x="${tx.toFixed(1)}" y="${(H - 6).toFixed(1)}" text-anchor="${anchor}" font-size="18" fill="rgba(161,161,170,0.72)" font-family="Lexend,sans-serif">${label}</text>`
  }

  const candleSvg = candles.map((c, i) => {
    const x   = px(i)
    const top = Math.min(py(c.open), py(c.close))
    const bh  = Math.max(3, Math.abs(py(c.close) - py(c.open)))
    const col = c.close >= c.open ? '#4fc329' : '#e35658'
    return `<line x1="${x.toFixed(2)}" y1="${py(c.high).toFixed(2)}" x2="${x.toFixed(2)}" y2="${py(c.low).toFixed(2)}" stroke="${col}" stroke-width="2"/>
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
  if (n.includes('analyst'))  return '#ae7db7'
  if (n.includes('diplomat')) return '#74b9ff'
  if (n.includes('sentinel')) return '#e35658'
  if (n.includes('explorer')) return '#4fc329'
  return '#ae7db7'
}

function extractBullets(snippet?: string, pageText?: string): string[] {
  const src = [snippet, pageText].filter(Boolean).join(' ')
  const sentences = src.match(/[^.!?]+[.!?]+/g) || [src]
  return sentences.slice(0, 2).map(s => s.trim())
}

// ── SSE event types ───────────────────────────────────────────────────────────
interface SSEEvent {
  type: string
  [key: string]: any
}

// ── Analysis Output (SSE renderer) ───────────────────────────────────────────
function AnalysisOutput({ events }: { events: SSEEvent[] }) {
  // We render directly from the accumulated events list
  // Each event type maps to a section of the output
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

  // Build brave result map (rank → latest data)
  const braveMap = new Map<number, SSEEvent>()
  for (const e of braveEvents) {
    if (e.type === 'brave_result') braveMap.set(e.rank, e)
    else if (!braveMap.has(e.rank)) braveMap.set(e.rank, e)
  }
  const braveItems = Array.from(braveMap.values())

  // Build agent segments
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
      {intentEvt && (
        <div className={`intent-badge fade-up ${intentEvt.is_binary ? 'binary' : 'open'}`}>
          {intentEvt.is_binary ? '🗳️ Decision question — council will debate' : '📊 Open analysis — council not needed'}
        </div>
      )}

      {/* Brave research phase */}
      {bravePhase && (
        <>
          <div className={`phase-row fade-up ${agentPhase || agentDone ? 'done' : ''}`}>
            {agentPhase || agentDone
              ? <><span className="check">✓</span><span>Web Research Complete</span></>
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
                    {isResult ? <a href={e.url} target="_blank" rel="noreferrer">{e.title || 'Untitled'}</a> : (e.title || 'Loading…')}
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
              ? <><span className="check">✓</span><span>AI Analysis Complete</span></>
              : <><div className="spinner" /><span>AI Analysis</span></>
            }
          </div>
          <div className="space-y-px mb-3">
            {toolEvents.map((e, i) => (
              <div key={i} className="agent-step done fade-up">
                <span className="step-check">✓</span>
                <span>{e.message || e.label}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Agent done: bullets + full analysis */}
      {agentDone && (
        <>
          <div className="phase-row done fade-up">
            <span className="check">✓</span><span>Research Summary</span>
          </div>
          {(agentDone.bullets || []).length > 0 && (
            <div className="bullet-card fade-up">
              {(agentDone.bullets as string[]).map((b, i) => (
                <div key={i} className="bullet-item">{b}</div>
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
              <div className="analysis-toggle" onClick={() => setShowFull(v => !v)}>
                {showFull || hasImages || !(agentDone.bullets?.length) ? '▾ Hide full analysis' : '▸ View full analysis'}
              </div>
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

      {/* Council phase */}
      {councilPhase && (
        <>
          <div className={`phase-row fade-up ${councilDone ? 'done' : ''}`}>
            {councilDone
              ? <><span className="check">✓</span><span>Council Complete</span></>
              : <><div className="spinner" /><span>Council Deliberation</span></>
            }
          </div>
          <div className="mt-2">
            {councilEvents.map((e, i) => {
              if (e.type === 'council_phase') {
                return <div key={i} className="text-xs text-lavender/50 mt-3 mb-1 font-semibold uppercase tracking-wider">{e.message}</div>
              }
              if (e.type === 'council_thinking') {
                const color = agentColor(e.agent)
                return (
                  <div key={i} className="council-bubble fade-up" style={{ borderLeft: `3px solid ${color}` }}>
                    <div className="cb-header">
                      <div className="cb-avatar" style={{ background: color }}>{e.agent[0].toUpperCase()}</div>
                      <div className="cb-name" style={{ color }}>{e.agent}</div>
                    </div>
                    <div className="cb-content">{e.content}</div>
                  </div>
                )
              }
              if (e.type === 'council_vote') {
                const color = agentColor(e.agent)
                return (
                  <div key={i} className="vote-box fade-up" style={{ borderLeft: `3px solid ${color}` }}>
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
                    <div className={`verdict-decision ${e.decision}`}>{(e.decision || '').toUpperCase()}</div>
                    <div className="verdict-tally">{e.approve} approve / {e.reject} reject</div>
                  </div>
                )
              }
              return null
            })}
          </div>
        </>
      )}

      {doneEvt?.analysis_id && (
        <div className="saved-badge fade-up">✔ Analysis saved to your history</div>
      )}
      {errorEvt && (
        <div className="mt-3 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger fade-up">
          {errorEvt.detail || 'An error occurred.'}
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

  // ── Auth
  useEffect(() => {
    sb.auth.getSession().then(({ data: { session } }) => {
      if (!session) { navigate('/'); return }
      setSession(session)
      loadHistory(session)
    })
    const { data: { subscription } } = sb.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT') { navigate('/'); return }
      setSession(session)
    })
    return () => subscription.unsubscribe()
  }, [navigate])

  // ── Close timeframe menu on outside click
  useEffect(() => {
    const handler = () => setMenuOpen(false)
    document.addEventListener('click', handler)
    return () => document.removeEventListener('click', handler)
  }, [])

  // ── Initial data load
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
          delta: `${isUp ? '▲' : '▼'} $${Math.abs(change).toFixed(2)} ${isUp ? '▲' : '▼'} ${Math.abs(percent).toFixed(2)}%`,
          isUp
        })
        const candles: Candle[] = values.map((e: any) => ({
          open: toNumber(e.open), high: toNumber(e.high), low: toNumber(e.low), close: toNumber(e.close),
          datetime: e.timestamp || e.datetime || e.date || ''
        }))
        setChartSvg(buildCandleSvg(candles, range))
      } catch {
        setSummary({ name: symbol, price: 'Data unavailable', delta: 'Check backend server.', isUp: false })
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

  // ── Audio
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
      src.buffer = decoded
      src.connect(ctx.destination)
      onStart?.()
      src.onended = () => { onEnd?.(); ctx.close(); drainAudio() }
      src.start()
    } catch { onEnd?.(); drainAudio() }
  }

  // ── Analyze submit
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
      if (!res.ok) {
        setSseEvents([{ type: 'error', detail: `Server error ${res.status}` }])
        return
      }

      const reader  = res.body!.getReader()
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

  const trendCls = summary?.isUp ? 'text-success' : 'text-danger'

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-6 pb-4 pt-0 font-body text-white sm:pb-5">
      <header className="relative left-1/2 mb-3 w-screen -translate-x-1/2 flex items-center justify-between gap-4 rounded-b-xl border-b border-panelBorder/25 bg-[#23182f]/95 px-6 py-4 shadow-[0_8px_24px_rgba(0,0,0,0.18)] sm:px-8">
        <h1 className="font-display text-3xl leading-tight text-lavender sm:text-4xl">Consilium</h1>
        <div className="flex items-center gap-3">
          {session?.user?.email && (
            <span className="hidden text-xs text-zinc-400 sm:block">{session.user.email}</span>
          )}
          <button onClick={async () => { await sb.auth.signOut(); navigate('/') }}
            className="rounded-full border border-panelBorder/70 bg-white/5 px-4 py-2 text-sm font-semibold text-lavender transition hover:border-lavender/80">
            Log out
          </button>
        </div>
      </header>

      <Link to="/stocks" className="glass-card mb-2 inline-flex w-fit self-start rounded-lg px-3 py-2 text-xs text-lavender transition hover:border-lavender/80 sm:text-sm">
        ← Back to watchlist
      </Link>

      {/* Summary */}
      {summary && (
        <section className="glass-card mb-2 grid grid-cols-1 items-center gap-2 rounded-2xl p-3 sm:grid-cols-[1.5fr_1fr_1fr] sm:gap-3 sm:p-4">
          <p className="font-display text-2xl text-zinc-100 sm:text-4xl">{summary.name}</p>
          <p className={`text-3xl font-semibold sm:text-4xl ${trendCls}`}>{summary.price}</p>
          <p className={`whitespace-nowrap text-2xl font-semibold sm:text-3xl ${trendCls}`}>{summary.delta}</p>
        </section>
      )}

      {/* Chart */}
      <section className="glass-card mb-2 flex-1 rounded-2xl p-0">
        <div className="relative ml-0 inline-flex">
          <button onClick={e => { e.stopPropagation(); setMenuOpen(v => !v) }} aria-haspopup="menu"
            className="inline-flex items-center gap-2 rounded-br-2xl rounded-tl-2xl border-b border-r border-lavender/30 bg-white/5 px-3 py-2 text-xl font-semibold text-lavender/85 outline-none transition hover:bg-white/8 sm:px-5 sm:py-3 sm:text-2xl">
            {TIMEFRAME_CONFIG[range].label}
            <span className="text-lg leading-none opacity-80">▾</span>
          </button>
          {menuOpen && (
            <div className="timeframe-menu absolute left-0 top-full z-20 mt-2 min-w-[12rem] overflow-hidden rounded-2xl">
              {(Object.keys(TIMEFRAME_CONFIG) as TimeframeKey[]).map(key => (
                <button key={key} onClick={() => { setMenuOpen(false); loadChart(key) }}
                  className="block w-full px-4 py-3 text-left text-xl text-zinc-100 transition hover:bg-white/10 sm:text-2xl">
                  {TIMEFRAME_CONFIG[key].label}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="h-[240px] rounded-b-2xl border-t border-lavender/25 p-3 sm:h-[300px] sm:p-4">
          <div className="grid-fade flex h-full w-full items-center justify-center rounded-xl border border-dashed border-lavender/45 bg-canvas/25 text-center text-sm text-zinc-300"
            dangerouslySetInnerHTML={{ __html: chartSvg }} />
        </div>
      </section>

      {/* Analysis form */}
      <section className="glass-card rounded-2xl p-3 sm:p-4">
        <form onSubmit={handleAnalyze}>
          <div className="flex items-center gap-2 sm:gap-3">
            <textarea value={query} onChange={e => setQuery(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit() } }}
              rows={1} placeholder="What do you want me to analyze?"
              className="min-h-[4.5rem] w-full resize-none overflow-hidden bg-transparent px-2 py-4 font-display text-2xl leading-[1.35] text-zinc-100 placeholder-lavender/100 outline-none sm:min-h-[5.25rem] sm:py-5 sm:text-4xl" />
            <button type="submit" disabled={isAnalyzing}
              className="shrink-0 rounded-xl border border-panelBorder/70 bg-white/8 px-4 py-2 text-sm font-semibold text-lavender transition hover:border-lavender/80 hover:bg-white/12 disabled:opacity-50 sm:px-5 sm:py-3 sm:text-base">
              →
            </button>
          </div>
        </form>
      </section>

      {/* History */}
      {history.length > 0 && (
        <section className="mt-3">
          <div className="glass-card rounded-2xl p-4 sm:p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-display text-lg text-lavender sm:text-xl">Past Analyses</h2>
              <span className="text-xs text-zinc-500">{history.length} saved</span>
            </div>
            <div className="space-y-2">
              {history.map((a, i) => {
                const verdict = (a.council_verdict || '').toLowerCase()
                const vClass  = verdict === 'approved' ? 'approved' : verdict === 'rejected' ? 'rejected' : 'none'
                const expanded = expandedHistory.has(i)
                return (
                  <div key={i} className={`history-card ${expanded ? 'expanded' : ''}`}
                    onClick={() => setExpandedHistory(prev => {
                      const next = new Set(prev)
                      expanded ? next.delete(i) : next.add(i)
                      return next
                    })}>
                    <div className="history-meta">
                      <span className="history-date">{formatDate(a.created_at)}</span>
                      <span className={`history-verdict ${vClass}`}>{verdict || 'no vote'}</span>
                      <span className="history-expand-icon">{expanded ? '▾' : '▸'}</span>
                    </div>
                    <div className="history-prompt">{a.prompt || a.intent || ''}</div>
                    <div className="history-advice">{a.advice || a.analysis_text || ''}</div>
                  </div>
                )
              })}
            </div>
          </div>
        </section>
      )}

      {/* Analysis output */}
      {showOutput && (
        <section ref={outputRef} className="analysis-shell mt-3 min-h-[68vh] rounded-2xl p-4 sm:p-6">
          <AnalysisOutput events={sseEvents} />
        </section>
      )}
    </main>
  )
}