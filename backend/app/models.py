from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ContextItem(BaseModel):
    """A single item in the user-provided multimodal context."""

    type: Literal["text", "image"]
    data: str = Field(
        description=(
            "For type='text': the text content. "
            "For type='image': base64-encoded image bytes."
        )
    )
    media_type: str = Field(
        default="image/jpeg",
        description="MIME type for image items (e.g. 'image/png', 'image/jpeg').",
    )


class AnalyzeRequest(BaseModel):
    ticker: str = Field(
        description="Stock ticker symbol to analyze (e.g. 'AAPL', 'TSLA')."
    )
    intent: str = Field(
        default="Provide a comprehensive stock analysis.",
        description="What the user wants to analyze (e.g. 'Is this a good long-term investment?').",
    )
    context: list[ContextItem] = Field(
        default_factory=list,
        description=(
            "Optional multimodal context for the agent — can include text guidance "
            "and/or images (e.g. charts or screenshots the user wants analyzed)."
        ),
    )


class AnalyzeResponse(BaseModel):
    ticker: str
    message_history: list[dict]
    """
    Full pydantic-ai message history serialized to JSON-compatible dicts.
    Includes all user turns, tool calls, tool results, and assistant responses.
    Intended for downstream processing by the summary/recommendation endpoint.
    """
