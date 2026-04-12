"""
Supabase client management for authentication and database operations.
Provides:
- Admin client singleton (service role, bypasses RLS for internal use)
- Connection utilities and error handling
"""
import os
from typing import Optional
from supabase import create_client, Client

# Module-level constants — read once at startup, not per request
_SUPABASE_URL: Optional[str] = os.getenv("SUPABASE_URL")
_ANON_KEY: Optional[str] = os.getenv("SUPABASE_ANON_KEY")
_SERVICE_ROLE_KEY: Optional[str] = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Admin client singleton (created lazily on first use)
_admin_client: Optional[Client] = None


def get_admin_client() -> Client:
    """
    Get or create the admin Supabase client (service role key).
    Bypasses RLS — use only for internal server operations.
    """
    global _admin_client
    if _admin_client is None:
        if not _SUPABASE_URL or not _SERVICE_ROLE_KEY:
            raise ValueError(
                "Missing required environment variables: "
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"
            )
        _admin_client = create_client(_SUPABASE_URL, _SERVICE_ROLE_KEY)
    return _admin_client


def validate_supabase_config():
    """
    Validate that all required Supabase environment variables are set.
    Call this during app startup to fail fast if configuration is missing.
    """
    required_vars = {
        "SUPABASE_URL": _SUPABASE_URL,
        "SUPABASE_ANON_KEY": _ANON_KEY,
        "SUPABASE_SERVICE_ROLE_KEY": _SERVICE_ROLE_KEY,
    }
    missing = [name for name, value in required_vars.items() if not value]
    if missing:
        raise ValueError(
            f"Missing required Supabase environment variables: {', '.join(missing)}"
        )
