"""
Pydantic data models for request/response validation.

Schemas for:
- Authentication (signup, login, token responses)
- Stocks (create, list, retrieve)
- Analysis (research briefs, comments)
"""

from pydantic import BaseModel, Field, EmailStr, field_validator
from datetime import datetime
from typing import Optional


# ============================================================================
# Authentication Schemas
# ============================================================================

class SignUpRequest(BaseModel):
    """User registration request."""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="Password (min 8 chars)")

    model_config = {"json_schema_extra": {"example": {
        "email": "user@example.com",
        "password": "securepassword123"
    }}}


class LoginRequest(BaseModel):
    """User login request."""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")

    model_config = {"json_schema_extra": {"example": {
        "email": "user@example.com",
        "password": "securepassword123"
    }}}


class AuthResponse(BaseModel):
    """Authentication response with JWT token."""
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    user_id: str = Field(..., description="Authenticated user ID")
    email: str = Field(..., description="Authenticated user email")

    model_config = {"json_schema_extra": {"example": {
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "token_type": "bearer",
        "user_id": "550e8400-e29b-41d4-a716-446655440000",
        "email": "user@example.com"
    }}}


class UserResponse(BaseModel):
    """User profile response."""
    id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    created_at: datetime = Field(..., description="Account creation timestamp")

    model_config = {"json_schema_extra": {"example": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "email": "user@example.com",
        "created_at": "2026-04-11T10:00:00Z"
    }}}


# ============================================================================
# Stock Schemas
# ============================================================================

class StockCreate(BaseModel):
    """Request to add a stock to user's portfolio."""
    ticker_name: str = Field(..., min_length=1, max_length=10, description="Stock ticker symbol (e.g., AAPL)")
    display_name: Optional[str] = Field(None, max_length=100, description="User-friendly name for the stock")

    @field_validator("ticker_name")
    @classmethod
    def uppercase_ticker(cls, v: str) -> str:
        return v.upper().strip()

    model_config = {"json_schema_extra": {"example": {
        "ticker_name": "AAPL",
        "display_name": "Apple Inc."
    }}}


class StockResponse(BaseModel):
    """Response when retrieving a stock."""
    ticker_name: str = Field(..., description="Stock ticker symbol")
    display_name: Optional[str] = Field(None, description="User-friendly name")
    added_at: datetime = Field(..., description="Timestamp when stock was added")

    model_config = {"json_schema_extra": {"example": {
        "ticker_name": "AAPL",
        "display_name": "Apple Inc.",
        "added_at": "2026-04-11T10:00:00Z"
    }}}


class StockListResponse(BaseModel):
    """Response containing list of user's stocks."""
    stocks: list[StockResponse] = Field(default_factory=list, description="List of stocks")
    total: int = Field(..., ge=0, description="Total number of stocks")

    model_config = {"json_schema_extra": {"example": {
        "stocks": [
            {"ticker_name": "AAPL", "display_name": "Apple Inc.", "added_at": "2026-04-11T10:00:00Z"},
            {"ticker_name": "GOOGL", "display_name": None, "added_at": "2026-04-11T11:00:00Z"}
        ],
        "total": 2
    }}}


# ============================================================================
# Analysis Schemas
# ============================================================================

class AnalysisCreate(BaseModel):
    """Request to store analysis for a stock."""
    ticker_name: str = Field(..., min_length=1, max_length=10, description="Stock ticker symbol")
    prompt: str = Field(..., description="Analysis prompt or focus area")
    advice: str = Field(..., description="Analysis advice or findings")

    @field_validator("ticker_name")
    @classmethod
    def uppercase_ticker(cls, v: str) -> str:
        return v.upper().strip()

    model_config = {"json_schema_extra": {"example": {
        "ticker_name": "AAPL",
        "prompt": "What are the growth prospects?",
        "advice": "Strong services revenue growth offsets hardware slowdown."
    }}}


class AnalysisResponse(BaseModel):
    """Response containing a stored analysis."""
    id: str = Field(..., description="Analysis ID (UUID)")
    ticker_name: str = Field(..., description="Stock ticker symbol")
    prompt: str = Field(..., description="Analysis prompt used")
    advice: str = Field(..., description="Analysis advice or findings")
    created_at: datetime = Field(..., description="When analysis was stored")

    model_config = {"json_schema_extra": {"example": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "ticker_name": "AAPL",
        "prompt": "What are the growth prospects?",
        "advice": "Strong services revenue growth offsets hardware slowdown.",
        "created_at": "2026-04-11T10:00:00Z"
    }}}


# ============================================================================
# Error Schemas
# ============================================================================

class ErrorResponse(BaseModel):
    """Standard error response."""
    detail: str = Field(..., description="Error message")
    status_code: int = Field(..., description="HTTP status code")

    model_config = {"json_schema_extra": {"example": {
        "detail": "Stock not found",
        "status_code": 404
    }}}