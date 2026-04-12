"""
Database helpers for persisting and retrieving stock analyses.
All writes use the admin (service-role) client so we can trust the user_id
that was already validated by the auth middleware.
"""
from __future__ import annotations

import logging
from typing import Any

from supabase_client import get_admin_client

logger = logging.getLogger(__name__)

_TABLE = "analyses"


async def save_analysis(
    user_id: str,
    ticker_name: str,
    prompt: str,
    advice: str,
    council_verdict: str,   # "approved" | "rejected"
    approve_count: int,
    reject_count: int,
) -> str | None:
    """Persist a completed analysis. Returns the new row's UUID or None on error."""
    try:
        client = get_admin_client()
        result = (
            client.table(_TABLE)
            .insert(
                {
                    "user_id": user_id,
                    "ticker_name": ticker_name,
                    "prompt": prompt,
                    "advice": advice,
                    "council_verdict": council_verdict,
                    "approve_count": approve_count,
                    "reject_count": reject_count,
                }
            )
            .execute()
        )
        if result.data:
            return result.data[0]["id"]
        return None
    except Exception:
        logger.exception("Failed to save analysis for user %s / %s", user_id, ticker_name)
        return None


async def get_user_analyses(user_id: str, limit: int = 30) -> list[dict[str, Any]]:
    """
    Return the most recent analyses for a user, newest first.
    """
    try:
        client = get_admin_client()
        result = (
            client.table(_TABLE)
            .select("id, ticker_name, prompt, advice, council_verdict, approve_count, reject_count, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception:
        logger.exception("Failed to fetch analyses for user %s", user_id)
        return []


# ---------------------------------------------------------------------------
# Stocks (watchlist)
# ---------------------------------------------------------------------------

_STOCKS_TABLE = "stocks"


async def upsert_stock(user_id: str, ticker_name: str, display_name: str | None = None) -> None:
    """Add a stock to the user's watchlist, or do nothing if it's already there."""
    try:
        client = get_admin_client()
        client.table(_STOCKS_TABLE).upsert(
            {
                "user_id": user_id,
                "ticker_name": ticker_name.upper(),
                "display_name": display_name,
            },
            on_conflict="user_id,ticker_name",
        ).execute()
    except Exception:
        logger.exception("Failed to upsert stock %s for user %s", ticker_name, user_id)


async def get_user_stocks(user_id: str) -> list[dict[str, Any]]:
    """Return all stocks in the user's watchlist, newest first."""
    try:
        client = get_admin_client()
        result = (
            client.table(_STOCKS_TABLE)
            .select("ticker_name, display_name, added_at")
            .eq("user_id", user_id)
            .order("added_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception:
        logger.exception("Failed to fetch stocks for user %s", user_id)
        return []


async def delete_stock(user_id: str, ticker_name: str) -> None:
    """Remove a stock from the user's watchlist."""
    try:
        client = get_admin_client()
        (
            client.table(_STOCKS_TABLE)
            .delete()
            .eq("user_id", user_id)
            .eq("ticker_name", ticker_name.upper())
            .execute()
        )
    except Exception:
        logger.exception("Failed to delete stock %s for user %s", ticker_name, user_id)


# ---------------------------------------------------------------------------
# Analyses (individual queries)
# ---------------------------------------------------------------------------

async def get_analysis_by_id(analysis_id: str, user_id: str) -> dict[str, Any] | None:
    """
    Fetch a single analysis (full row) owned by user_id.
    Returns None if not found or not owned by that user.
    """
    try:
        client = get_admin_client()
        result = (
            client.table(_TABLE)
            .select("*")
            .eq("id", analysis_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        logger.exception("Failed to fetch analysis %s", analysis_id)
        return None
