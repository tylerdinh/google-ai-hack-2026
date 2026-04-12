"""
Authentication utilities for FastAPI.
Provides:
- get_current_user: FastAPI dependency that validates Supabase JWT tokens
- Token extraction and error handling
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPBasicCredentials
from supabase import AuthApiError

from supabase_client import get_admin_client

# FastAPI security scheme for automatic Swagger UI support
security = HTTPBearer()


async def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    """
    FastAPI dependency to extract and validate the current user from JWT token.
    Extracts Bearer token from Authorization header, validates it with Supabase,
    and returns the authenticated user object.
    Usage:
        @app.get("/api/protected")
        async def protected_endpoint(user = Depends(get_current_user)):
            return {"user_id": user.id, "email": user.email}
    Args:
        credentials: HTTPBearer credentials (extracted automatically by FastAPI)
    Returns:
        User object from Supabase Auth with id, email, user_metadata, etc.
    Raises:
        HTTPException: 401 if token is invalid or expired
    """
    token = credentials

    try:
        # Validate token using Supabase Admin client.
        # get_user() calls Supabase's JWT verification internally.
        admin_client = get_admin_client()
        user = admin_client.auth.get_user(token)
        return user
    except AuthApiError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_with_token(credentials: HTTPBasicCredentials = Depends(security)):
    """
    FastAPI dependency that returns both the authenticated user AND the JWT token.
    
    Used for operations that need to enforce RLS at the database level.
    Returns tuple: (user, token)
    
    Usage:
        @app.post("/api/protected")
        async def protected_endpoint(user_token = Depends(get_current_user_with_token)):
            user, token = user_token
            client = get_user_client(token)  # RLS enforced
            return {"user_id": user.id}
    
    Returns:
        Tuple of (user, token) where user is the auth object and token is the JWT string
        
    Raises:
        HTTPException: 401 if token is invalid or expired
    """
    token = credentials.credentials
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        admin_client = get_admin_client()
        user = admin_client.auth.get_user(token)
        return user, token
    
    except AuthApiError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )