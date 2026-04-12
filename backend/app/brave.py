import asyncio
import json
import os
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_RESULTS = 5
FETCH_TIMEOUT = 8.0
MAX_TEXT_LENGTH = 3000

router = APIRouter(prefix="/brave", tags=["brave"])


class StockSearchRequest(BaseModel):
    stock: str = Field(..., description="Stock ticker or company name (e.g. 'AAPL', 'Tesla')")
    intent: str = Field(
        ...,
        description="What the user wants to analyze (e.g. 'Is this a good long-term investment?', 'Should I sell under $5?')",
    )


class LinkResult(BaseModel):
    rank: int
    title: str
    url: str
    snippet: str
    page_text: Optional[str] = None
    fetch_error: Optional[str] = None


class StockSearchResponse(BaseModel):
    query: str
    stock: str
    intent: str
    results: list[LinkResult]


# ---------------------------------------------------------------------------
# Core functions (reusable by the pipeline in main.py)
# ---------------------------------------------------------------------------


def build_query(stock: str, intent: str) -> str:
    intent_lower = intent.lower()

    if any(w in intent_lower for w in ["long-term", "longterm", "long term", "hold"]):
        angle = "long term investment outlook analysis"
    elif any(w in intent_lower for w in ["sell", "exit", "dump"]):
        angle = "sell signal price target analysis"
    elif any(w in intent_lower for w in ["buy", "entry", "undervalued"]):
        angle = "buy signal undervalued analysis"
    elif any(w in intent_lower for w in ["short", "bearish", "overvalued"]):
        angle = "short bearish overvalued analysis"
    elif any(w in intent_lower for w in ["dividend", "income", "yield"]):
        angle = "dividend yield income analysis"
    elif any(w in intent_lower for w in ["earnings", "revenue", "financials"]):
        angle = "earnings revenue financial analysis"
    else:
        angle = "stock analysis"

    return f"{stock} stock {angle} 2026"


async def search_brave(query: str) -> list[dict]:
    if not BRAVE_API_KEY:
        raise HTTPException(status_code=500, detail="BRAVE_API_KEY not configured")

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    params = {"q": query, "count": MAX_RESULTS}

    async with httpx.AsyncClient() as client:
        resp = await client.get(BRAVE_SEARCH_URL, headers=headers, params=params)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"Brave API error: {resp.text}",
            )
        data = resp.json()

    web_results = data.get("web", {}).get("results", [])
    return web_results[:MAX_RESULTS]


def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    combined = "\n".join(lines)
    return combined[:MAX_TEXT_LENGTH]


async def fetch_page_text(client: httpx.AsyncClient, url: str) -> tuple[str | None, str | None]:
    try:
        resp = await client.get(
            url,
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; StockAnalysisBot/1.0)"},
        )
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}"
        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type:
            return None, f"Non-HTML content: {content_type}"
        return extract_text(resp.text), None
    except httpx.TimeoutException:
        return None, "Timeout"
    except Exception as e:
        return None, str(e)[:200]


async def gather_brave_context(
    stock: str,
    intent: str,
    event_queue: asyncio.Queue[dict],
) -> list[LinkResult]:
    """
    Run brave search + page fetching, pushing SSE events to the queue.
    Returns the list of LinkResults for use as agent context.
    """
    query = build_query(stock, intent)
    await event_queue.put({"type": "brave_status", "message": f"Searching: {query}"})

    try:
        raw_results = await search_brave(query)
    except HTTPException as e:
        await event_queue.put({"type": "brave_error", "message": e.detail})
        return []

    if not raw_results:
        await event_queue.put({"type": "brave_error", "message": "No search results found"})
        return []

    await event_queue.put({
        "type": "brave_status",
        "message": f"Found {len(raw_results)} results. Fetching pages...",
        "total": len(raw_results),
    })

    results: list[LinkResult] = []
    async with httpx.AsyncClient() as client:
        for i, raw in enumerate(raw_results):
            url = raw.get("url", "")
            title = raw.get("title", "")
            snippet = raw.get("description", "")

            await event_queue.put({
                "type": "brave_fetching",
                "rank": i + 1,
                "title": title,
                "url": url,
            })

            page_text, fetch_error = await fetch_page_text(client, url)

            link = LinkResult(
                rank=i + 1,
                title=title,
                url=url,
                snippet=snippet,
                page_text=page_text,
                fetch_error=fetch_error,
            )
            results.append(link)

            await event_queue.put({
                "type": "brave_result",
                "rank": i + 1,
                "title": title,
                "url": url,
                "snippet": snippet,
                "page_text": page_text,
            })

    await event_queue.put({"type": "brave_done", "message": "Web research complete"})
    return results


def compile_context_text(results: list[LinkResult], stock: str, intent: str) -> str:
    """Turn brave results into a text block suitable for the agent prompt."""
    parts = [
        f"The user wants to analyze {stock} with the following intent: \"{intent}\"",
        "",
        "Below is real-time web research gathered from top search results. "
        "Use this information as additional context for your analysis:",
        "",
    ]
    for r in results:
        parts.append(f"--- Source {r.rank}: {r.title} ---")
        parts.append(f"URL: {r.url}")
        if r.snippet:
            parts.append(f"Summary: {r.snippet}")
        if r.page_text:
            parts.append(r.page_text[:1500])
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Standalone router endpoints (for direct testing)
# ---------------------------------------------------------------------------


@router.post("/search", response_model=StockSearchResponse)
async def search_stock(req: StockSearchRequest):
    query = build_query(req.stock, req.intent)
    raw_results = await search_brave(query)

    if not raw_results:
        raise HTTPException(status_code=404, detail="No search results found")

    urls = [r.get("url", "") for r in raw_results]
    async with httpx.AsyncClient() as client:
        tasks = [fetch_page_text(client, url) for url in urls]
        page_data = await asyncio.gather(*tasks)

    results = []
    for i, raw in enumerate(raw_results):
        page_text, fetch_error = page_data[i]
        results.append(
            LinkResult(
                rank=i + 1,
                title=raw.get("title", ""),
                url=raw.get("url", ""),
                snippet=raw.get("description", ""),
                page_text=page_text,
                fetch_error=fetch_error,
            )
        )

    return StockSearchResponse(
        query=query,
        stock=req.stock,
        intent=req.intent,
        results=results,
    )


@router.post("/search/stream")
async def search_stock_stream(req: StockSearchRequest):
    query = build_query(req.stock, req.intent)

    async def event_stream():
        yield _sse({"type": "status", "message": f"Searching Brave for: {query}"})

        try:
            raw_results = await search_brave(query)
        except HTTPException as e:
            yield _sse({"type": "error", "message": e.detail})
            return

        if not raw_results:
            yield _sse({"type": "error", "message": "No search results found"})
            return

        yield _sse({
            "type": "status",
            "message": f"Found {len(raw_results)} results. Fetching pages...",
            "total": len(raw_results),
        })

        async with httpx.AsyncClient() as client:
            for i, raw in enumerate(raw_results):
                url = raw.get("url", "")
                title = raw.get("title", "")
                snippet = raw.get("description", "")

                yield _sse({"type": "fetching", "rank": i + 1, "title": title, "url": url})
                page_text, fetch_error = await fetch_page_text(client, url)
                yield _sse({
                    "type": "result", "rank": i + 1, "title": title, "url": url,
                    "snippet": snippet, "page_text": page_text, "fetch_error": fetch_error,
                })

        yield _sse({"type": "done"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
