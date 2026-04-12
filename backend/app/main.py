from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
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


def _extract_final_text(message_history: list[dict]) -> str:
    for msg in reversed(message_history):
        if msg.get("kind") == "response" and msg.get("parts"):
            for part in msg["parts"]:
                if part.get("part_kind") == "text" and part.get("content"):
                    return part["content"]
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

    async def event_stream() -> AsyncGenerator[str, None]:
        def sse(payload: dict) -> str:
            return f"data: {json.dumps(payload)}\n\n"

        queue: asyncio.Queue[dict] = asyncio.Queue()

        # Track council outcome so we can save it after the debate
        council_outcome: dict = {}

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
            analysis_text = _extract_final_text(message_history)

            yield sse({
                "type": "agent_done",
                "ticker": ticker,
                "message_history": message_history,
                "images": images,
                "analysis_text": analysis_text,
            })

        except Exception as exc:
            logger.exception("Agent run failed for %s", ticker)
            agent_task.cancel()
            yield sse({"type": "error", "detail": str(exc)})
            return

        # ── Phase 3: Council debate ──────────────────────────────────
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
                    # Capture verdict data before forwarding to client
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
        if user_id and council_outcome:
            # Satisfy the FK constraint: ensure the stock is in the watchlist
            await upsert_stock(user_id, ticker)
            analysis_id = await save_analysis(
                user_id=user_id,
                ticker_name=ticker,
                prompt=intent,
                advice=analysis_text,
                council_verdict=council_outcome.get("decision", "rejected"),
                approve_count=council_outcome.get("approve", 0),
                reject_count=council_outcome.get("reject", 0),
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
