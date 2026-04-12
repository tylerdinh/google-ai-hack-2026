"""
Authentication utilities for FastAPI.
Provides:
- get_current_user: FastAPI dependency that validates Supabase JWT tokens
- get_optional_user: same but returns None instead of 401 when unauthenticated
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import AuthApiError

from supabase_client import get_admin_client

# FastAPI security scheme — adds Authorize button to Swagger UI
security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    FastAPI dependency: extract & validate Bearer JWT, return Supabase user.
    Raises HTTP 401 if the token is missing or invalid.
    """
    return await _resolve_user(credentials.credentials)


async def get_current_user_with_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    FastAPI dependency: returns (user, token) tuple.
    Used when the caller also needs the raw token to create a user-scoped client.
    """
    token = credentials.credentials
    user = await _resolve_user(token)
    return user, token


async def get_optional_user(request: Request):
    """
    FastAPI dependency: returns the Supabase user if a valid Bearer token is
    present, otherwise returns None.  Never raises 401.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    try:
        return await _resolve_user(token)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _resolve_user(token: str):
    """Validate a JWT with Supabase and return the user object."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        admin_client = get_admin_client()
        response = admin_client.auth.get_user(token)
        return response.user
    except AuthApiError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )
