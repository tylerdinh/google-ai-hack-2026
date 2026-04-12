from dotenv import load_dotenv
# Load environment variables
load_dotenv(".env")

from fastapi import FastAPI, HTTPException, Depends, status, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict
from datetime import datetime
import asyncio
import json
import uuid
import os
from supabase import AuthApiError

from council_orchestrator import CouncilOrchestrator
from agents import get_all_agents_info, AGENTS
from supabase_client import get_admin_client, get_user_client, validate_supabase_config
from auth import get_current_user, get_current_user_with_token
from models import (
    SignUpRequest,
    LoginRequest,
    AuthResponse,
    UserResponse,
    StockCreate,
    StockResponse,
    StockListResponse,
    ErrorResponse,
)

# Initialize app
app = FastAPI(
    title="Stock Research API",
    description="AI-powered stock research with multi-agent council",
    version="1.0.0"
)

# Validate Supabase configuration on startup
@app.on_event("startup")
async def startup_event():
    """Validate Supabase config and perform initialization."""
    try:
        validate_supabase_config()
    except ValueError as e:
        print(f"ERROR: {e}")
        raise

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global exception handler for Supabase Auth errors
@app.exception_handler(AuthApiError)
async def auth_api_error_handler(request, exc):
    """Handle Supabase auth errors and return 401."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=str(exc)
    )

# Store active discussions
active_discussions: Dict[str, CouncilOrchestrator] = {}

# ============================================================================
# Council Debate Endpoints (Existing)
# ============================================================================

class IdeaSubmission(BaseModel):
    idea: str

@app.get("/api/council/agents")
async def get_agents():
    """Get the list of available agents."""
    return {"agents": get_all_agents_info()}


@app.post("/api/council/discuss")
async def start_discussion(submission: IdeaSubmission):
    """Start a new council discussion."""
    
    discussion_id = str(uuid.uuid4())
    
    orchestrator = CouncilOrchestrator(discussion_id, submission.idea)
    active_discussions[discussion_id] = orchestrator
    
    # Start debate (in background)
    asyncio.create_task(orchestrator.run_debate())
    
    return {
        "discussion_id": discussion_id,
        "idea": submission.idea,
        "agents": list(AGENTS.keys())
    }

@app.get("/api/council/discussion/{discussion_id}/stream")
async def stream_discussion(discussion_id: str):
    """SSE for real-time debate updates for a given discussion."""
    
    if discussion_id not in active_discussions:
        raise HTTPException(status_code=404, detail="Discussion not found")
    
    orchestrator = active_discussions[discussion_id]
    
    async def event_generator():
        try:
            while True:
                event = await orchestrator.sse_queue.get()
                
                yield f"data: {json.dumps(event)}\n\n"
                
                if event["type"] == "complete":
                    break
        
        except asyncio.CancelledError:
            pass
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

@app.get("/api/council/discussion/{discussion_id}")
async def get_discussion(discussion_id: str):
    """Get a complete discussion history."""
    
    if discussion_id not in active_discussions:
        raise HTTPException(status_code=404, detail="Discussion not found")
    
    orchestrator = active_discussions[discussion_id]
    
    return {
        "discussion_id": discussion_id,
        "idea": orchestrator.idea,
        "status": "complete" if orchestrator.debate_complete else "active",
        "votes": [
            {
                "agent": v.agent,
                "vote": v.vote,
                "reasoning": v.reasoning
            }
            for v in orchestrator.votes.values()
        ] if orchestrator.votes else []
    }


# ============================================================================
# Authentication Endpoints
# ============================================================================

@app.post("/api/auth/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(request: SignUpRequest):
    """
    Register a new user with email and password.
    
    Returns JWT access token and user info on success.
    Note: Stores refresh_token on client side for token renewal.
    """
    try:
        admin = get_admin_client()
        response = admin.auth.sign_up({
            "email": request.email,
            "password": request.password,
        })
        
        # Supabase returns the user session after signup
        return AuthResponse(
            access_token=response.session.access_token,
            token_type="bearer",
            user_id=response.user.id,
            email=response.user.email,
        )
    
    except AuthApiError as e:
        if "already registered" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User already exists"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@app.post("/api/auth/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    """
    Authenticate user with email and password.
    
    Returns JWT access token and user info on success.
    """
    try:
        admin = get_admin_client()
        response = admin.auth.sign_in_with_password({
            "email": request.email,
            "password": request.password,
        })
        
        return AuthResponse(
            access_token=response.session.access_token,
            token_type="bearer",
            user_id=response.user.id,
            email=response.user.email,
        )
    
    except AuthApiError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(user = Depends(get_current_user)):
    """
    Logout the current user.
    
    NOTE: Supabase JWTs are valid until expiration. Frontend must:
    1. Discard the access_token locally
    2. Discard the refresh_token locally
    
    For a true token revocation list, implement in Phase 2.
    """
    return None


@app.post("/api/auth/refresh", response_model=AuthResponse)
async def refresh(request: Request, user = Depends(get_current_user)):
    """
    Refresh JWT access token using Supabase refresh_token.
    
    Frontend must:
    1. Store refresh_token from signup/login response
    2. Send refresh_token in request body to this endpoint
    3. Receive new access_token + refresh_token
    
    Example body:
        {"refresh_token": "..."}
    
    For Phase 2: Implement full OAuth2 refresh token flow with client library.
    """
    try:
        body = await request.json()
        refresh_token = body.get("refresh_token")
        
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="refresh_token required in request body"
            )
        
        admin = get_admin_client()
        response = admin.auth.refresh_session({
            "refresh_token": refresh_token
        })
        
        return AuthResponse(
            access_token=response.session.access_token,
            token_type="bearer",
            user_id=response.user.id,
            email=response.user.email,
        )
    
    except HTTPException:
        raise
    except AuthApiError as e:
        if "invalid" in str(e).lower() or "expired" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token invalid or expired; please login again"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token refresh failed"
        )


@app.get("/api/auth/me", response_model=UserResponse)
async def get_me(user = Depends(get_current_user)):
    """
    Get current authenticated user info.
    
    Requires valid JWT token in Authorization header.
    """
    return UserResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at if hasattr(user, 'created_at') else datetime.now(),
    )


# ============================================================================
# Stock Management Endpoints (Protected)
# ============================================================================

@app.post("/api/stocks", response_model=StockResponse, status_code=status.HTTP_201_CREATED)
async def create_stock(
    request: StockCreate,
    user_token = Depends(get_current_user_with_token)
):
    """
    Add a stock to the user's portfolio.
    
    Requires authentication. RLS enforced at database level via user-scoped client.
    """
    user, token = user_token
    
    try:
        # Use user-scoped client — RLS is automatically enforced
        client = get_user_client(token)
        
        # Insert stock record — RLS will reject if user_id differs
        response = client.table("stocks").insert({
            "user_id": user.id,
            "ticker_name": request.ticker_name,
            "display_name": request.display_name,
            "added_at": datetime.now().isoformat(),
        }).execute()
        
        if response.data:
            stock = response.data[0]
            return StockResponse(
                ticker_name=stock["ticker_name"],
                display_name=stock["display_name"],
                added_at=datetime.fromisoformat(stock["added_at"]),
            )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create stock"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        error_str = str(e).lower()
        if "unique constraint" in error_str or "duplicate" in error_str:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Stock {request.ticker_name} already in portfolio"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@app.get("/api/stocks", response_model=StockListResponse)
async def list_stocks(user_token = Depends(get_current_user_with_token)):
    """
    Get all stocks in the user's portfolio.
    
    RLS enforced at database level — returns only user's own stocks.
    """
    user, token = user_token
    
    try:
        # Use user-scoped client — RLS is automatically enforced
        client = get_user_client(token)
        
        # Query returns only this user's stocks (RLS enforced)
        response = client.table("stocks").select("*").execute()
        
        stocks = [
            StockResponse(
                ticker_name=s["ticker_name"],
                display_name=s["display_name"],
                added_at=datetime.fromisoformat(s["added_at"]),
            )
            for s in response.data
        ]
        
        return StockListResponse(
            stocks=stocks,
            total=len(stocks),
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve stocks: {str(e)}"
        )


@app.get("/api/stocks/{ticker_name}", response_model=StockResponse)
async def get_stock(
    ticker_name: str,
    user_token = Depends(get_current_user_with_token)
):
    """
    Get a specific stock by ticker.
    
    RLS enforced — returns 404 if user doesn't own the stock.
    """
    user, token = user_token
    
    try:
        # Use user-scoped client — RLS is automatically enforced
        client = get_user_client(token)
        
        # Query returns only if user owns it (RLS enforced)
        response = client.table("stocks").select("*").eq(
            "ticker_name", ticker_name
        ).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Stock {ticker_name} not found"
            )
        
        stock = response.data[0]
        return StockResponse(
            ticker_name=stock["ticker_name"],
            display_name=stock["display_name"],
            added_at=datetime.fromisoformat(stock["added_at"]),
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve stock: {str(e)}"
        )


@app.delete("/api/stocks/{ticker_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stock(
    ticker_name: str,
    user_token = Depends(get_current_user_with_token)
):
    """
    Remove a stock from the user's portfolio.
    
    RLS enforced — returns 404 if user doesn't own the stock.
    """
    user, token = user_token
    
    try:
        # Use user-scoped client — RLS is automatically enforced
        client = get_user_client(token)
        
        # Delete returns only stocks user owns (RLS enforced)
        response = client.table("stocks").delete().eq(
            "ticker_name", ticker_name
        ).execute()
        
        if not response.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Stock {ticker_name} not found"
            )
        
        return None
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete stock: {str(e)}"
        )


# ============================================================================
# Health Check
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
