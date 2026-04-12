from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict
from datetime import datetime
import asyncio
import json
import uuid
from pathlib import Path
import requests
from time import time

from dotenv import load_dotenv

from council_orchestrator import CouncilOrchestrator
from agents import get_all_agents_info, AGENTS

app = FastAPI()

ROOT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ROOT_ENV_PATH, override=True)

SYMBOL_NAME_MAP: Dict[str, str] = {
    "AAPL": "Apple Inc.",
    "GOOG": "Alphabet Inc.",
    "AMZN": "Amazon.com, Inc.",
    "RBLX": "Roblox Corporation"
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active discussions
active_discussions: Dict[str, CouncilOrchestrator] = {}

# Data Models
class IdeaSubmission(BaseModel):
    idea: str


def fetch_yahoo_quote_for_symbol(symbol: str):
    """Fetch a normalized quote for one symbol from Yahoo chart endpoint."""

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    response = requests.get(
        url,
        timeout=12,
        params={
            "interval": "1d",
            "range": "5d"
        },
        headers={
            "Accept": "application/json",
            "User-Agent": "google-ai-hack-2026-backend/1.0"
        }
    )

    if not response.ok:
        raise HTTPException(status_code=502, detail=f"Yahoo quote error {response.status_code}")

    payload = response.json()
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise HTTPException(status_code=502, detail="Yahoo quote payload returned no result")

    meta = result.get("meta") or {}
    quote = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}

    close_series = [value for value in (quote.get("close") or []) if value is not None]
    open_series = [value for value in (quote.get("open") or []) if value is not None]
    high_series = [value for value in (quote.get("high") or []) if value is not None]
    low_series = [value for value in (quote.get("low") or []) if value is not None]

    current = float(meta.get("regularMarketPrice") or (close_series[-1] if close_series else 0))
    history_prev = close_series[-2] if len(close_series) > 1 else (close_series[-1] if close_series else 0)
    previous_close = float(meta.get("previousClose") or meta.get("chartPreviousClose") or history_prev or 0)
    open_price = float((open_series[-1] if open_series else 0) or 0)
    high = float((high_series[-1] if high_series else 0) or 0)
    low = float((low_series[-1] if low_series else 0) or 0)

    if previous_close:
        change = current - previous_close
        percent_change = (change / previous_close) * 100
    else:
        change = 0.0
        percent_change = 0.0

    name = meta.get("longName") or meta.get("shortName") or SYMBOL_NAME_MAP.get(symbol, symbol)

    return {
        "symbol": symbol,
        "name": name,
        "close": f"{current:.5f}",
        "open": f"{open_price:.5f}",
        "high": f"{high:.5f}",
        "low": f"{low:.5f}",
        "previous_close": f"{previous_close:.5f}",
        "change": f"{change:.10f}",
        "percent_change": f"{percent_change:.10f}"
    }


def search_yahoo_symbols(query: str):
    """Search Yahoo Finance for symbols and company names."""

    response = requests.get(
        "https://query1.finance.yahoo.com/v1/finance/search",
        timeout=12,
        params={
            "q": query,
            "quotesCount": 8,
            "newsCount": 0,
            "enableFuzzyQuery": "true"
        },
        headers={
            "Accept": "application/json",
            "User-Agent": "google-ai-hack-2026-backend/1.0"
        }
    )

    if not response.ok:
        raise HTTPException(status_code=502, detail=f"Yahoo search error {response.status_code}")

    payload = response.json()
    results = payload.get("quotes") or []

    normalized = []
    for item in results:
        symbol = (item.get("symbol") or "").upper()
        if not symbol:
            continue

        normalized.append(
            {
                "symbol": symbol,
                "name": item.get("longname") or item.get("shortname") or item.get("name") or symbol,
                "type": item.get("quoteType") or "EQUITY",
                "exchange": item.get("exchange") or "",
                "region": item.get("region") or "",
            }
        )

    return normalized[:8]


def fetch_yahoo_candles(symbol: str, interval: str, outputsize: int):
    """Fetch OHLC candles from Yahoo Finance public chart endpoint."""

    yahoo_interval = "1d"
    yahoo_range = "6mo"
    if interval == "5min":
        yahoo_interval = "5m"
        yahoo_range = "1d"
    elif interval == "1hour":
        yahoo_interval = "60m"
        yahoo_range = "1mo"
    elif interval == "1week":
        yahoo_interval = "1wk"
        yahoo_range = "2y"

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    response = requests.get(
        url,
        timeout=12,
        params={
            "interval": yahoo_interval,
            "range": yahoo_range
        },
        headers={
            "Accept": "application/json",
            "User-Agent": "google-ai-hack-2026-backend/1.0"
        }
    )

    if not response.ok:
        raise HTTPException(status_code=502, detail=f"Yahoo fallback error {response.status_code}")

    payload = response.json()
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise HTTPException(status_code=502, detail="Yahoo fallback returned no result")

    timestamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []

    count = min(len(timestamps), len(opens), len(highs), len(lows), len(closes))
    values = []

    for idx in range(count):
        o = opens[idx]
        h = highs[idx]
        l = lows[idx]
        c = closes[idx]
        ts = timestamps[idx]

        if None in (o, h, l, c, ts):
            continue

        candle_time = datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
        values.append(
            {
                "datetime": candle_time,
                "open": f"{float(o):.5f}",
                "high": f"{float(h):.5f}",
                "low": f"{float(l):.5f}",
                "close": f"{float(c):.5f}"
            }
        )

    if not values:
        raise HTTPException(status_code=502, detail="Yahoo fallback returned empty candle list")

    trimmed = values[-outputsize:]
    return list(reversed(trimmed))

# Endpoints
@app.get("/api/council/agents")
async def get_agents():
    """Get the list of available agents."""
    return {"agents": get_all_agents_info()}


@app.get("/api/stocks/quotes")
async def get_stock_quotes(symbols: str):
    """Return normalized quote data for comma-separated symbols via Yahoo."""

    cleaned_symbols = [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()]
    if not cleaned_symbols:
        raise HTTPException(status_code=400, detail="Query parameter 'symbols' is required")

    quote_map: Dict[str, Dict[str, str]] = {symbol: {
        "symbol": symbol,
        "name": SYMBOL_NAME_MAP.get(symbol, symbol),
        "close": "0.00000",
        "open": "0.00000",
        "high": "0.00000",
        "low": "0.00000",
        "previous_close": "0.00000",
        "change": "0.0000000000",
        "percent_change": "0.0000000000"
    } for symbol in cleaned_symbols}

    for symbol in cleaned_symbols:
        try:
            quote_map[symbol] = fetch_yahoo_quote_for_symbol(symbol)
        except HTTPException:
            # Keep safe defaults for any symbol that fails, but continue others.
            continue

    if len(cleaned_symbols) == 1:
        return quote_map[cleaned_symbols[0]]

    return quote_map


@app.get("/api/stocks/search")
async def search_stocks(query: str):
    """Autocomplete stocks by ticker or company name."""

    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    return search_yahoo_symbols(cleaned_query)


@app.get("/api/stocks/time-series")
async def get_stock_time_series(symbol: str, interval: str = "1day", outputsize: int = 24):
    """Return OHLC time series payload using Yahoo Finance data."""

    cleaned_symbol = symbol.strip().upper()
    if not cleaned_symbol:
        raise HTTPException(status_code=400, detail="Query parameter 'symbol' is required")

    allowed_intervals = {"5min", "1hour", "1day", "1week"}
    if interval not in allowed_intervals:
        raise HTTPException(status_code=400, detail="interval must be one of: 5min, 1hour, 1day, 1week")

    safe_outputsize = min(max(outputsize, 2), 390)

    values = fetch_yahoo_candles(cleaned_symbol, interval, safe_outputsize)

    return {
        "symbol": cleaned_symbol,
        "interval": interval,
        "values": values
    }


@app.post("/api/council/discuss")
async def start_discussion(submission: IdeaSubmission):
    """Start a new council discussion."""
    
    discussion_id = str(uuid.uuid4())
    
    orchestrator = CouncilOrchestrator(discussion_id, submission.idea)
    active_discussions[discussion_id] = orchestrator
    
    # Start debate (in background)
    asyncio.create_task(orchestrator.run_debate())
    
    return {
        "discussion_id": discussion_id,
        "idea": submission.idea,
        "agents": list(AGENTS.keys())
    }

@app.get("/api/council/discussion/{discussion_id}/stream")
async def stream_discussion(discussion_id: str):
    """SSE for real-time debate updates for a given discussion."""
    
    if discussion_id not in active_discussions:
        raise HTTPException(status_code=404, detail="Discussion not found")
    
    orchestrator = active_discussions[discussion_id]
    
    async def event_generator():
        try:
            while True:
                event = await orchestrator.sse_queue.get()
                
                yield f"data: {json.dumps(event)}\n\n"
                
                if event["type"] == "complete":
                    break
        
        except asyncio.CancelledError:
            pass
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

@app.get("/api/council/discussion/{discussion_id}")
async def get_discussion(discussion_id: str):
    """Get a complete discussion history."""
    
    if discussion_id not in active_discussions:
        raise HTTPException(status_code=404, detail="Discussion not found")
    
    orchestrator = active_discussions[discussion_id]
    
    return {
        "discussion_id": discussion_id,
        "idea": orchestrator.idea,
        "status": "complete" if orchestrator.debate_complete else "active",
        "votes": [
            {
                "agent": v.agent,
                "vote": v.vote,
                "reasoning": v.reasoning
            }
            for v in orchestrator.votes.values()
        ] if orchestrator.votes else []
    }