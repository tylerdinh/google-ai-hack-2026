from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic_ai import BinaryContent

load_dotenv()

from app.agent import StockDeps, run_agent_stream              # noqa: E402
from app.brave import gather_brave_context, compile_context_text, router as brave_router  # noqa: E402
from app.council import CouncilOrchestrator                         # noqa: E402
from app.database import (  # noqa: E402
    save_analysis, get_user_analyses, get_analysis_by_id,
    upsert_stock, get_user_stocks, delete_stock,
)
from app.models import AnalyzeRequest                               # noqa: E402
from auth import get_current_user, get_optional_user                # noqa: E402
from supabase_client import validate_supabase_config                # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if not os.getenv("GEMINI_API_KEY"):
        logger.warning("GEMINI_API_KEY is not set — agent calls will fail")
    try:
        validate_supabase_config()
        logger.info("Supabase configured ✓")
    except ValueError as e:
        logger.warning("Supabase not fully configured: %s", e)
    logger.info("Stock Research API ready")
    yield
    logger.info("Stock Research API shut down")


_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
]

app = FastAPI(
    title="Stock Research API",
    description=(
        "AI-powered deep equity research. Brave web search feeds context into a "
        "PydanticAI agent, then a council of AI agents debates the findings."
    ),
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(brave_router)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_prompt(ticker: str, request: AnalyzeRequest, brave_context: str) -> str | list:
    image_parts: list[BinaryContent] = []
    extra_text_lines: list[str] = []

    for item in request.context:
        if item.type == "text":
            extra_text_lines.append(item.data)
        elif item.type == "image":
            try:
                img_bytes = base64.b64decode(item.data)
            except Exception:
                raise HTTPException(
                    status_code=422,
                    detail="Invalid base64 encoding in a context image item.",
                )
            image_parts.append(BinaryContent(data=img_bytes, media_type=item.media_type))

    user_intent = request.intent or "Provide a comprehensive stock analysis."

    intro = (
        f"Stock to analyze: {ticker}\n"
        f"User's question / intent: \"{user_intent}\"\n\n"
        "Follow the workflow in your instructions exactly: write your introduction first, "
        "then call each tool one at a time and write your analysis of its result before "
        "calling the next tool, then close with a conclusion that directly answers the "
        "user's question above. Choose chart periods and other parameters to best serve "
        "the user's specific intent."
    )

    if brave_context:
        intro += f"\n\nReal-time web research context (use this as background, not a substitute for tool calls):\n\n{brave_context}"

    if extra_text_lines:
        intro += "\n\nAdditional context from the user:\n" + "\n".join(extra_text_lines)

    if image_parts:
        return [intro, *image_parts]
    return intro


def _build_council_proposal(ticker: str, intent: str, analysis_text: str) -> str:
    return (
        f"STOCK: {ticker}\n"
        f"USER INTENT: {intent}\n\n"
        f"RESEARCH ANALYSIS:\n{analysis_text}\n\n"
        f"Based on the above research, should the user proceed with their intent: \"{intent}\"?"
    )


def _extract_all_text(message_history: list[dict]) -> str:
    """Collect text from every response message in order and join them.

    The agent produces multiple response messages — one for the intro, one after
    each tool call (per-tool analysis paragraph), and one for the conclusion.
    Concatenating them reconstructs the full report.
    """
    chunks = []
    for msg in message_history:
        if msg.get("kind") == "response" and msg.get("parts"):
            for part in msg["parts"]:
                if part.get("part_kind") == "text" and part.get("content"):
                    text = part["content"].strip()
                    if text:
                        chunks.append(text)
    return "\n\n".join(chunks)


# ---------------------------------------------------------------------------
# Binary-intent detection
# ---------------------------------------------------------------------------

# Strict fallback regex — only strong yes/no patterns
_BINARY_FALLBACK_RE = re.compile(
    r"\b("
    r"should\s+(i|we|they)\s+(buy|sell|hold|invest|short)\b|"
    r"(is|are)\s+(this|it|they|these)\s+a?\s*(good|bad|safe|worth|risky)\s*(investment|buy|stock|pick|idea)?\b|"
    r"(good|bad)\s+(long.?term|short.?term|investment|buy|idea)\b|"
    r"\b(recommend|advise)\b|"
    r"worth\s+(buying|investing)\b|"
    r"(buy|hold)\s+or\s+(sell|hold|buy)\b"
    r")",
    re.IGNORECASE,
)


async def _classify_binary_intent(intent: str) -> bool:
    """Return True when the user's question expects a yes/no decision.

    Uses Gemini flash-lite for accuracy; falls back to regex on error.
    """
    from google import genai

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    prompt = (
        'Does the following question expect a yes/no (binary) answer — '
        'i.e. should the council vote approve or reject it?\n'
        'Answer only "yes" or "no".\n\n'
        'Examples:\n'
        '  "Should I buy AAPL?" → yes\n'
        '  "Is AAPL a good long-term investment?" → yes\n'
        '  "Should I hold or sell?" → yes\n'
        '  "What price should I sell AAPL at?" → no\n'
        '  "What are AAPL sell targets?" → no\n'
        '  "Analyze AAPL fundamentals" → no\n'
        '  "What is the market cap of AAPL?" → no\n\n'
        f'Question: "{intent}"'
    )
    try:
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        answer = (resp.text or "").strip().lower()
        result = answer.startswith("yes")
        logger.info("Binary classification for '%s' → %s (raw: %s)", intent, result, answer)
        return result
    except Exception:
        logger.warning("Binary classification via Gemini failed, using regex fallback", exc_info=True)
        return bool(_BINARY_FALLBACK_RE.search(intent))


# ---------------------------------------------------------------------------
# Bullet-point summary
# ---------------------------------------------------------------------------

async def _summarize_to_bullets(ticker: str, analysis_text: str) -> list[str]:
    """Condense the full analysis into 5 crisp bullet points via Gemini flash-lite."""
    from google import genai

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    prompt = (
        f"Summarize this {ticker} stock analysis into exactly 5 bullet points.\n"
        "Rules:\n"
        "- Each bullet = one short sentence, under 20 words.\n"
        "- Start every bullet with '- '.\n"
        "- Output only the 5 bullets, nothing else.\n\n"
        f"{analysis_text[:4000]}"
    )
    try:
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        lines = (resp.text or "").strip().splitlines()
        bullets = [
            ln.lstrip("-•* ").strip()
            for ln in lines
            if ln.strip() and ln.strip()[0] in "-•*"
        ]
        return bullets[:6] if bullets else []
    except Exception:
        logger.warning("Bullet summary generation failed", exc_info=True)
        return []


async def _generate_direct_answer(intent: str, ticker: str, analysis_text: str) -> str:
    """Return a 1-2 sentence direct answer to the user's specific question."""
    from google import genai

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    prompt = (
        f"A user asked about {ticker}: \"{intent}\"\n\n"
        f"Based on this analysis:\n{analysis_text[:4000]}\n\n"
        "Write a direct, specific answer to their question in 1-2 sentences. "
        "Be concrete — include numbers, dates, or targets where relevant. "
        "Do not start with 'Based on' or refer to 'the analysis'. "
        "Just answer the question directly."
    )
    try:
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash-lite",
            contents=prompt,
        )
        return (resp.text or "").strip()
    except Exception:
        logger.warning("Direct answer generation failed", exc_info=True)
        return ""


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.get("/auth/me", tags=["Auth"])
async def me(user=Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return {
        "id": user.id,
        "email": user.email,
        "created_at": user.created_at,
    }


# ---------------------------------------------------------------------------
# Watchlist (stocks) routes
# ---------------------------------------------------------------------------

@app.get("/stocks", tags=["Stocks"])
async def list_stocks(user=Depends(get_current_user)):
    """Return the authenticated user's stock watchlist."""
    rows = await get_user_stocks(user.id)
    return {"stocks": rows, "total": len(rows)}


@app.post("/stocks", tags=["Stocks"], status_code=201)
async def add_stock(body: dict, user=Depends(get_current_user)):
    """Add a ticker to the user's watchlist."""
    ticker = (body.get("ticker_name") or "").upper().strip()
    if not ticker:
        raise HTTPException(status_code=422, detail="ticker_name is required")
    await upsert_stock(user.id, ticker, body.get("display_name"))
    return {"ticker_name": ticker}


@app.delete("/stocks/{ticker_name}", tags=["Stocks"])
async def remove_stock(ticker_name: str, user=Depends(get_current_user)):
    """Remove a ticker from the user's watchlist."""
    await delete_stock(user.id, ticker_name.upper())
    return {"deleted": ticker_name.upper()}


# ---------------------------------------------------------------------------
# Analysis history routes
# ---------------------------------------------------------------------------

@app.get("/analyses", tags=["Analyses"])
async def list_analyses(user=Depends(get_current_user)):
    """Return the authenticated user's 30 most recent analyses."""
    rows = await get_user_analyses(user.id)
    return {"analyses": rows, "total": len(rows)}


@app.get("/analyses/{analysis_id}", tags=["Analyses"])
async def get_analysis(analysis_id: str, user=Depends(get_current_user)):
    """Return a single analysis owned by the authenticated user."""
    row = await get_analysis_by_id(analysis_id, user.id)
    if not row:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return row


@app.delete("/analyses/{analysis_id}", tags=["Analyses"])
async def delete_analysis(analysis_id: str, user=Depends(get_current_user)):
    """Delete a single analysis owned by the authenticated user."""
    from supabase_client import get_admin_client
    try:
        get_admin_client().table("analyses").delete().eq("id", analysis_id).eq("user_id", user.id).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"deleted": analysis_id}


# ---------------------------------------------------------------------------
# Research route
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Meta"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Stock Research API — see /docs"}


@app.get("/stocks.html")
async def stocks_page():
    f = FRONTEND_DIR / "stocks.html"
    return FileResponse(str(f)) if f.exists() else {"error": "not found"}


@app.get("/stock.html")
async def stock_page():
    f = FRONTEND_DIR / "stock.html"
    return FileResponse(str(f)) if f.exists() else {"error": "not found"}


@app.post("/research/analyze", tags=["Research"])
async def analyze_stock(
    request: AnalyzeRequest,
    raw_request: Request,
) -> StreamingResponse:
    ticker = request.ticker.upper().strip()
    intent = request.intent

    # Resolve user from Authorization header (optional — no error if absent)
    user = await get_optional_user(raw_request)
    user_id: str | None = user.id if user else None

    # Classify intent before streaming begins
    is_binary = await _classify_binary_intent(intent)
    logger.info("Intent '%s' → binary=%s", intent, is_binary)

    async def event_stream() -> AsyncGenerator[str, None]:
        def sse(payload: dict) -> str:
            return f"data: {json.dumps(payload)}\n\n"

        queue: asyncio.Queue[dict] = asyncio.Queue()
        council_outcome: dict = {}

        # ── Intent classification ─────────────────────────────────────
        yield sse({
            "type": "intent_classified",
            "is_binary": is_binary,
            "intent": intent,
        })

        # ── Phase 1: Brave web research ──────────────────────────────
        yield sse({"type": "phase", "phase": "brave", "message": "Starting web research..."})

        brave_results = await gather_brave_context(ticker, intent, queue)
        while not queue.empty():
            yield sse(queue.get_nowait())

        brave_context = compile_context_text(brave_results, ticker, intent) if brave_results else ""

        # ── Phase 2: Agent analysis ──────────────────────────────────
        yield sse({"type": "phase", "phase": "agent", "message": "Starting AI analysis..."})

        prompt = _build_prompt(ticker, request, brave_context)
        deps = StockDeps(ticker=ticker, event_queue=queue)

        agent_task: asyncio.Task = asyncio.create_task(
            run_agent_stream(prompt, deps)
        )

        analysis_text = ""
        message_history: list[dict] = []
        images: list[dict] = []

        try:
            while not agent_task.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.05)
                    yield sse(event)
                except asyncio.TimeoutError:
                    pass

            while not queue.empty():
                yield sse(queue.get_nowait())

            exc = agent_task.exception()
            if exc:
                raise exc

            result = agent_task.result()
            message_history = json.loads(result)
            images = deps.image_store
            analysis_text = _extract_all_text(message_history)

            # Generate bullet summary (passed to client; full text goes to council)
            bullets = await _summarize_to_bullets(ticker, analysis_text)

            # For non-binary questions add a direct answer to the specific query
            direct_answer = ""
            if not is_binary:
                direct_answer = await _generate_direct_answer(intent, ticker, analysis_text)

            yield sse({
                "type": "agent_done",
                "ticker": ticker,
                "message_history": message_history,
                "images": images,
                "analysis_text": analysis_text,
                "bullets": bullets,
                "direct_answer": direct_answer,
                "is_binary": is_binary,
            })

        except Exception as exc:
            logger.exception("Agent run failed for %s", ticker)
            agent_task.cancel()
            yield sse({"type": "error", "detail": str(exc)})
            return

        # ── Phase 3: Council debate (binary questions only) ───────────
        if is_binary:
            yield sse({"type": "phase", "phase": "council", "message": "Convening the council..."})

            proposal = _build_council_proposal(ticker, intent, analysis_text)
            council = CouncilOrchestrator(
                discussion_id=str(uuid.uuid4()),
                idea=proposal,
                event_queue=queue,
            )

            council_task: asyncio.Task = asyncio.create_task(council.run_debate())

            try:
                while not council_task.done():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.05)
                        if event.get("type") == "council_verdict":
                            council_outcome = event
                        yield sse(event)
                    except asyncio.TimeoutError:
                        pass

                while not queue.empty():
                    event = queue.get_nowait()
                    if event.get("type") == "council_verdict":
                        council_outcome = event
                    yield sse(event)

                exc = council_task.exception()
                if exc:
                    raise exc

            except Exception as exc:
                logger.exception("Council debate failed for %s", ticker)
                council_task.cancel()
                yield sse({"type": "error", "detail": str(exc)})
                return

        # ── Persist to database (authenticated users only) ────────────
        analysis_id: str | None = None
        if user_id:
            verdict = council_outcome.get("decision", "approved") if is_binary else "approved"
            await upsert_stock(user_id, ticker)
            analysis_id = await save_analysis(
                user_id=user_id,
                ticker_name=ticker,
                prompt=intent,
                advice=analysis_text,
                council_verdict=verdict,
                approve_count=council_outcome.get("approve", 0) if is_binary else 0,
                reject_count=council_outcome.get("reject", 0) if is_binary else 0,
            )
            if analysis_id:
                logger.info("Saved analysis %s for user %s", analysis_id, user_id)

        yield sse({"type": "done", "ticker": ticker, "analysis_id": analysis_id})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Stock Market Data Endpoints (for frontend UI)
# ---------------------------------------------------------------------------

import yfinance as yf


def fetch_yahoo_quote_for_symbol(symbol: str) -> dict:
    """Fetch the latest quote for a symbol from Yahoo Finance."""
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.info
        return {
            symbol: {
                "symbol": symbol,
                "name": data.get("longName", symbol),
                "close": data.get("regularMarketPrice", 0),
                "previous_close": data.get("regularMarketPreviousClose", 0),
                "open": data.get("open", 0),
                "change": (data.get("regularMarketPrice", 0) - data.get("regularMarketPreviousClose", 0)) if data.get("regularMarketPrice") else 0,
                "percent_change": data.get("regularMarketChangePercent", 0) * 100 if data.get("regularMarketChangePercent") else 0,
            }
        }
    except Exception as e:
        logger.warning(f"Failed to fetch quote for {symbol}: {e}")
        return {symbol: {"symbol": symbol, "name": symbol, "close": 0, "change": 0, "percent_change": 0}}


def search_yahoo_symbols(query: str) -> list[dict]:
    """Search for stock symbols using Yahoo Finance."""
    try:
        ticker = yf.Ticker(query)
        info = ticker.info

        # yfinance always returns a dict even for non-existent tickers.
        # A real ticker has at minimum a market price or a company name.
        has_price = (
            info.get("regularMarketPrice") is not None
            or info.get("currentPrice") is not None
            or info.get("previousClose") is not None
        )
        has_name = bool(info.get("longName") or info.get("shortName"))
        if not (has_price or has_name):
            return []

        symbol = info.get("symbol", query.upper())
        name = info.get("longName") or info.get("shortName") or symbol
        exchange = info.get("exchange", "")
        return [{"symbol": symbol, "name": name, "exchange": exchange}]
    except Exception as e:
        logger.warning(f"Search failed for {query}: {e}")
        return []


def fetch_yahoo_candles(symbol: str, interval: str, outputsize: int) -> dict:
    """Fetch OHLC candle data from Yahoo Finance."""
    try:
        ticker = yf.Ticker(symbol)
        
        if interval == "5min":
            hist = ticker.history(period="1d", interval="5m")
        elif interval == "1hour":
            hist = ticker.history(period="30d", interval="1h")
        elif interval == "1day":
            hist = ticker.history(period="1y", interval="1d")
        elif interval == "1week":
            hist = ticker.history(period="5y", interval="1wk")
        else:
            hist = ticker.history(period="1mo", interval="1d")
        
        if hist.empty:
            return {"values": []}
        
        values = []
        for date, row in hist.iterrows():
            values.append({
                "timestamp": date.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
            })
        
        return {"values": values[-outputsize:] if outputsize else values}
    except Exception as e:
        logger.warning(f"Failed to fetch candles for {symbol}: {e}")
        return {"values": []}


@app.get("/api/stocks/quotes", tags=["Stock Market Data"])
async def get_stock_quotes(symbols: str) -> dict:
    """Get current stock quotes for given symbols."""
    symbol_list = [s.strip().upper() for s in symbols.split(",")]
    result = {}
    for symbol in symbol_list:
        quote_data = fetch_yahoo_quote_for_symbol(symbol)
        result.update(quote_data)
    return result


@app.get("/api/stocks/time-series", tags=["Stock Market Data"])
async def get_time_series(symbol: str, interval: str = "1day", outputsize: int = 30) -> dict:
    """Get historical OHLC data for a stock."""
    return fetch_yahoo_candles(symbol.upper(), interval, outputsize)


@app.get("/api/stocks/search", tags=["Stock Market Data"])
async def search_stocks(query: str) -> list[dict]:
    """Search for stocks by symbol or company name."""
    return search_yahoo_symbols(query.upper())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
