from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic_ai import BinaryContent

load_dotenv()

from app.agent import StockDeps, agent  # noqa: E402 — after load_dotenv
from app.models import AnalyzeRequest  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


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
        "AI-powered deep equity research. The /research endpoint runs a "
        "PydanticAI agent (Gemini) that autonomously gathers charts, fundamentals, "
        "financial statements, and news, then returns the full message history for "
        "downstream summarization."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _build_prompt(ticker: str, request: AnalyzeRequest) -> str | list:
    """Build the multimodal user prompt from the request context."""
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
    if extra_text_lines:
        intro += "\n\n**Additional context from the user:**\n" + "\n".join(extra_text_lines)

    if image_parts:
        return [intro, *image_parts]
    return intro


@app.get("/health", tags=["Meta"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/research/analyze", tags=["Research"])
async def analyze_stock(request: AnalyzeRequest) -> StreamingResponse:
    ticker = request.ticker.upper().strip()
    prompt = _build_prompt(ticker, request)

    async def event_stream() -> AsyncGenerator[str, None]:
        def sse(payload: dict) -> str:
            return f"data: {json.dumps(payload)}\n\n"

        queue: asyncio.Queue[dict] = asyncio.Queue()
        deps = StockDeps(ticker=ticker, event_queue=queue)

        # Run the agent in a background task so we can stream queue events
        # concurrently as tools execute.
        agent_task: asyncio.Task = asyncio.create_task(
            agent.run(prompt, deps=deps)
        )

        try:
            while not agent_task.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.05)
                    yield sse(event)
                except asyncio.TimeoutError:
                    pass  # keep polling

            # Drain any remaining events the tools emitted
            while not queue.empty():
                yield sse(queue.get_nowait())

            # Raise if the agent task itself failed
            exc = agent_task.exception()
            if exc:
                raise exc

            result = agent_task.result()
            message_history: list[dict] = json.loads(result.all_messages_json())
            yield sse({"type": "done", "ticker": ticker, "message_history": message_history, "images": deps.image_store})

        except Exception as exc:
            logger.exception("Streaming agent run failed for ticker %s", ticker)
            agent_task.cancel()
            yield sse({"type": "error", "detail": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable Nginx proxy buffering
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)