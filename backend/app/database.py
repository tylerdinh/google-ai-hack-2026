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
    ticker: str,
    intent: str,
    analysis_text: str,
    council_verdict: str,   # "approved" | "rejected"
    approve_count: int,
    reject_count: int,
) -> str | None:
    """
    Persist a completed analysis.  Returns the new row's UUID or None on error.
    """
    try:
        client = get_admin_client()
        result = (
            client.table(_TABLE)
            .insert(
                {
                    "user_id": user_id,
                    "ticker": ticker,
                    "intent": intent,
                    "analysis_text": analysis_text,
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
        logger.exception("Failed to save analysis for user %s / %s", user_id, ticker)
        return None


async def get_user_analyses(user_id: str, limit: int = 30) -> list[dict[str, Any]]:
    """
    Return the most recent analyses for a user, newest first.
    Only fetches lightweight columns — not the full analysis_text blob.
    """
    try:
        client = get_admin_client()
        result = (
            client.table(_TABLE)
            .select("id, ticker, intent, council_verdict, approve_count, reject_count, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception:
        logger.exception("Failed to fetch analyses for user %s", user_id)
        return []


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
