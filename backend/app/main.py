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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic_ai import BinaryContent

load_dotenv()

from app.agent import StockDeps, agent  # noqa: E402
from app.brave import gather_brave_context, compile_context_text, router as brave_router  # noqa: E402
from app.council import CouncilOrchestrator  # noqa: E402
from app.models import AnalyzeRequest  # noqa: E402

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
    version="0.3.0",
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

    intro = (
        f"Please conduct a comprehensive deep research analysis of **{ticker}**.\n"
        "Use your tools freely to gather price charts, technical indicators, "
        "fundamental metrics, and financial statements. "
        "Analyze every chart image you receive carefully before drawing conclusions."
    )

    if brave_context:
        intro += f"\n\n{brave_context}"

    if extra_text_lines:
        intro += "\n\n**Additional context from the user:**\n" + "\n".join(extra_text_lines)

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
# Routes
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
async def analyze_stock(request: AnalyzeRequest) -> StreamingResponse:
    ticker = request.ticker.upper().strip()
    intent = request.intent

    async def event_stream() -> AsyncGenerator[str, None]:
        def sse(payload: dict) -> str:
            return f"data: {json.dumps(payload)}\n\n"

        queue: asyncio.Queue[dict] = asyncio.Queue()

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
            agent.run(prompt, deps=deps)
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
            message_history = json.loads(result.all_messages_json())
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
                    yield sse(event)
                except asyncio.TimeoutError:
                    pass

            while not queue.empty():
                yield sse(queue.get_nowait())

            exc = council_task.exception()
            if exc:
                raise exc

        except Exception as exc:
            logger.exception("Council debate failed for %s", ticker)
            council_task.cancel()
            yield sse({"type": "error", "detail": str(exc)})
            return

        yield sse({"type": "done", "ticker": ticker})

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