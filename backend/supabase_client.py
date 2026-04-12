"""
Supabase client management for authentication and database operations.
Provides:
- Admin client singleton (service role, bypasses RLS for internal use)
- User-scoped client factory (anon key + user JWT, enforces RLS)
- Connection utilities and error handling
"""
import os
from typing import Optional
from supabase import create_client, Client
from supabase.lib.client_options import ClientOptions

# Module-level constants — read once at startup, not per request
_SUPABASE_URL: Optional[str] = os.getenv("SUPABASE_URL")
_ANON_KEY: Optional[str] = os.getenv("SUPABASE_ANON_KEY")
_SERVICE_ROLE_KEY: Optional[str] = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Admin client singleton
_admin_client: Optional[Client] = None


def get_admin_client() -> Client:
    """
    Get or create the admin Supabase client (service role key).
    WARNING: This client bypasses RLS. Use only for:
    - Internal server operations
    - User management (create, delete)
    - System maintenance tasks
    Do NOT use this for user data access — use get_user_client() instead.
    """
    global _admin_client
    if _admin_client is None:
        if not _SUPABASE_URL or not _SERVICE_ROLE_KEY:
            raise ValueError(
                "Missing required environment variables: "
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"
            )
        options = ClientOptions(
            auto_refresh_token=True,
            persist_session=False,
            storage_options={"path": "/tmp"},
        )
        _admin_client = create_client(_SUPABASE_URL, _SERVICE_ROLE_KEY, options=options)
    return _admin_client


def get_user_client(user_token: str) -> Client:
    """
    Get a user-scoped Supabase client using a JWT token.
    Uses the anon key but authenticates DB requests with the user's JWT,
    so RLS policies are automatically enforced — the user can only access
    rows they own.
    Args:
        user_token: JWT token from Supabase Auth
    Returns:
        User-scoped Supabase client with RLS enforced
    Raises:
        ValueError: If environment variables or token are missing
    """
    if not _SUPABASE_URL or not _ANON_KEY:
        raise ValueError(
            "Missing required environment variables: "
            "SUPABASE_URL and SUPABASE_ANON_KEY"
        )
    if not user_token:
        raise ValueError("User token is required for user-scoped client")

    options = ClientOptions(
        auto_refresh_token=False,
        persist_session=False,
        storage_options={"path": "/tmp"},
    )
    client = create_client(_SUPABASE_URL, _ANON_KEY, options=options)

    # Set the JWT directly on the PostgREST client so RLS is enforced.
    # We don't call set_session() because we're not managing a session —
    # we just need the user's token on outgoing DB requests.
    client.postgrest.auth(user_token)

    return client


def validate_supabase_config():
    """
    Validate that all required Supabase environment variables are set.
    Call this during app startup to fail fast if configuration is missing.
    Raises:
        ValueError: If any required variables are missing
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