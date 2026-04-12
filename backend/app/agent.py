from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import yfinance as yf
from pydantic_ai import Agent, BinaryContent, RunContext

matplotlib.use("Agg")

logger = logging.getLogger(__name__)

_MODEL = f"google-gla:{os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')}"

SYSTEM_PROMPT = """\
You are an expert equity research analyst conducting deep, data-driven investment research.
You have access to tools to generate price charts, technical indicator charts, fetch fundamental
metrics, and review financial statements for any stock.

For the target stock, conduct a thorough analysis covering price action, technical indicators,
fundamental valuation, financial statement trends, and key risks and opportunities.

Call tools freely and in whatever order makes sense. When a chart image is returned to you,
analyze it carefully before continuing. Be thorough, objective, and cite specific data points.

FORMATTING RULES — follow these exactly:
- Write in plain continuous prose. No markdown, no special characters of any kind.
- Do not use asterisks, underscores, pound signs, backticks, or dashes as bullets.
- Do not start any sentence or paragraph with a label followed by a colon.
  Bad examples: "Income Statement Analysis:", "Risks:", "Price Action:", "Overview:".
  Instead, just begin the paragraph with the actual content.
- Do not use numbered or bulleted lists. Integrate all information into flowing paragraphs.
- Separate paragraphs with a blank line.
- The output must read naturally as plain text with zero special characters.\
"""


@dataclass
class StockDeps:
    """Dependencies injected into every tool call."""

    ticker: str
    # When set, tools push progress events here for SSE streaming.
    event_queue: asyncio.Queue[dict] | None = field(default=None, compare=False)
    # Collects base64-encoded chart images as tools run (for PDF embedding).
    image_store: list[dict] = field(default_factory=list, compare=False)


agent: Agent[StockDeps, str] = Agent(
    _MODEL,
    deps_type=StockDeps,
    system_prompt=SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _emit(ctx: RunContext[StockDeps], event: dict) -> None:
    """Push an event onto the SSE queue if one is attached."""
    if ctx.deps.event_queue is not None:
        await ctx.deps.event_queue.put(event)


def _generate_png(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _df_to_dict(df: pd.DataFrame | None, max_periods: int = 4) -> dict[str, Any]:
    if df is None or df.empty:
        return {}
    df = df.iloc[:, :max_periods].copy()
    df.columns = [
        col.date().isoformat() if hasattr(col, "date") else str(col)
        for col in df.columns
    ]
    return df.to_dict()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@agent.tool
async def get_price_chart(
    ctx: RunContext[StockDeps],
    period: str = "3mo",
    ticker: str | None = None,
) -> BinaryContent:
    """Generate a candlestick price chart with volume bars for a stock.

    Args:
        period: Lookback period. Options: '1mo', '3mo', '6mo', '1y', '2y', '5y'.
        ticker: Ticker symbol. Defaults to the primary analysis ticker.

    Returns:
        A PNG candlestick chart image with volume.
    """
    symbol = (ticker or ctx.deps.ticker).upper()
    await _emit(ctx, {"type": "tool_call", "tool": "get_price_chart", "label": f"Fetching price chart for {symbol}"})
    await asyncio.sleep(1)
    try:
        hist = yf.Ticker(symbol).history(period=period)
        if hist.empty:
            raise ValueError(f"No price data returned for {symbol}")

        buf = io.BytesIO()
        mpf.plot(
            hist,
            type="candle",
            style="charles",
            title=f"{symbol} — Price & Volume ({period})",
            volume=True,
            figsize=(14, 8),
            savefig=dict(fname=buf, dpi=120, bbox_inches="tight"),
        )
        buf.seek(0)
        img_bytes = buf.read()
        result = BinaryContent(data=img_bytes, media_type="image/png")
        ctx.deps.image_store.append({"tool": "get_price_chart", "data": base64.b64encode(img_bytes).decode()})
        await _emit(ctx, {"type": "tool_done", "tool": "get_price_chart", "label": "Price chart ready — analyzing"})
        return result
    except Exception:
        logger.exception("get_price_chart failed for %s", symbol)
        raise


@agent.tool
async def get_technical_chart(
    ctx: RunContext[StockDeps],
    period: str = "6mo",
    ticker: str | None = None,
) -> BinaryContent:
    """Generate a technical analysis chart with Bollinger Bands, RSI, and MACD.

    Args:
        period: Lookback period. Options: '3mo', '6mo', '1y', '2y'.
        ticker: Ticker symbol. Defaults to the primary analysis ticker.

    Returns:
        A PNG chart with three panels: price + Bollinger Bands, RSI (14), MACD (12/26/9).
    """
    symbol = (ticker or ctx.deps.ticker).upper()
    await _emit(ctx, {"type": "tool_call", "tool": "get_technical_chart", "label": f"Generating technical indicators for {symbol}"})
    await asyncio.sleep(1)
    try:
        hist = yf.Ticker(symbol).history(period=period)
        if hist.empty:
            raise ValueError(f"No price data returned for {symbol}")

        close = hist["Close"]

        # Bollinger Bands (20-period)
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_upper = sma20 + 2 * std20
        bb_lower = sma20 - 2 * std20

        # RSI (14-period)
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain / loss))

        # MACD (12 / 26 / 9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - signal_line

        fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
        fig.suptitle(f"{symbol} — Technical Analysis ({period})", fontsize=14, y=1.01)

        # Panel 1: Price + Bollinger Bands
        axes[0].plot(close.index, close, label="Close", linewidth=1.5, color="#1f77b4")
        axes[0].plot(close.index, sma20, label="SMA 20", linestyle="--", linewidth=1, color="orange")
        axes[0].fill_between(close.index, bb_lower, bb_upper, alpha=0.12, color="#1f77b4", label="BB (2σ)")
        axes[0].set_ylabel("Price")
        axes[0].legend(loc="upper left", fontsize=8)
        axes[0].grid(True, alpha=0.3)

        # Panel 2: RSI
        axes[1].plot(rsi.index, rsi, color="purple", linewidth=1.5)
        axes[1].axhline(70, color="red", linestyle="--", linewidth=1, label="Overbought (70)")
        axes[1].axhline(30, color="green", linestyle="--", linewidth=1, label="Oversold (30)")
        axes[1].axhline(50, color="gray", linestyle=":", linewidth=0.8)
        axes[1].set_ylim(0, 100)
        axes[1].set_ylabel("RSI (14)")
        axes[1].legend(loc="upper left", fontsize=8)
        axes[1].grid(True, alpha=0.3)

        # Panel 3: MACD
        bar_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in macd_hist]
        axes[2].bar(macd_hist.index, macd_hist, color=bar_colors, alpha=0.6, width=1.5, label="Histogram")
        axes[2].plot(macd_line.index, macd_line, label="MACD", linewidth=1.5, color="#1f77b4")
        axes[2].plot(signal_line.index, signal_line, label="Signal", linewidth=1.5, color="orange")
        axes[2].axhline(0, color="black", linewidth=0.8)
        axes[2].set_ylabel("MACD (12/26/9)")
        axes[2].legend(loc="upper left", fontsize=8)
        axes[2].grid(True, alpha=0.3)

        plt.tight_layout()
        img_bytes = _generate_png(fig)
        result = BinaryContent(data=img_bytes, media_type="image/png")
        ctx.deps.image_store.append({"tool": "get_technical_chart", "data": base64.b64encode(img_bytes).decode()})
        await _emit(ctx, {"type": "tool_done", "tool": "get_technical_chart", "label": "Technical chart ready — analyzing RSI, MACD, Bollinger Bands"})
        return result
    except Exception:
        logger.exception("get_technical_chart failed for %s", symbol)
        raise


@agent.tool
async def get_stock_fundamentals(
    ctx: RunContext[StockDeps],
    ticker: str | None = None,
) -> dict[str, Any]:
    """Retrieve key fundamental metrics: valuation, profitability, growth, balance sheet,
    cash flow, dividends, and analyst price targets.

    Args:
        ticker: Ticker symbol. Defaults to the primary analysis ticker.

    Returns:
        Dict of fundamental metrics (None values omitted).
    """
    symbol = (ticker or ctx.deps.ticker).upper()
    await _emit(ctx, {"type": "tool_call", "tool": "get_stock_fundamentals", "label": f"Fetching fundamental metrics for {symbol}"})
    await asyncio.sleep(1)
    try:
        info = yf.Ticker(symbol).info
        fields: dict[str, Any] = {
            # Identity
            "name": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "exchange": info.get("exchange"),
            "currency": info.get("currency"),
            # Price & market cap
            "current_price": info.get("currentPrice"),
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "beta": info.get("beta"),
            # Valuation
            "pe_ratio_ttm": info.get("trailingPE"),
            "pe_ratio_forward": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_sales_ttm": info.get("priceToSalesTrailing12Months"),
            "price_to_book": info.get("priceToBook"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "ev_to_revenue": info.get("enterpriseToRevenue"),
            # Profitability
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "net_profit_margin": info.get("profitMargins"),
            "return_on_equity": info.get("returnOnEquity"),
            "return_on_assets": info.get("returnOnAssets"),
            # Growth
            "revenue_growth_yoy": info.get("revenueGrowth"),
            "earnings_growth_yoy": info.get("earningsGrowth"),
            "earnings_growth_quarterly": info.get("earningsQuarterlyGrowth"),
            # Balance sheet
            "total_cash": info.get("totalCash"),
            "total_debt": info.get("totalDebt"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            # Cash flow
            "free_cashflow": info.get("freeCashflow"),
            "operating_cashflow": info.get("operatingCashflow"),
            # Dividends
            "dividend_yield": info.get("dividendYield"),
            "payout_ratio": info.get("payoutRatio"),
            # Analyst consensus
            "analyst_recommendation_mean": info.get("recommendationMean"),
            "analyst_recommendation_key": info.get("recommendationKey"),
            "number_of_analysts": info.get("numberOfAnalystOpinions"),
            "target_price_low": info.get("targetLowPrice"),
            "target_price_mean": info.get("targetMeanPrice"),
            "target_price_high": info.get("targetHighPrice"),
        }
        result = {k: v for k, v in fields.items() if v is not None}
        await _emit(ctx, {"type": "tool_done", "tool": "get_stock_fundamentals", "label": "Fundamentals loaded"})
        return result
    except Exception:
        logger.exception("get_stock_fundamentals failed for %s", symbol)
        raise


@agent.tool
async def get_financial_statements(
    ctx: RunContext[StockDeps],
    ticker: str | None = None,
) -> dict[str, Any]:
    """Retrieve the last 4 years of annual financial statements: income statement,
    balance sheet, and cash flow statement.

    Args:
        ticker: Ticker symbol. Defaults to the primary analysis ticker.

    Returns:
        Dict with keys 'income_statement', 'balance_sheet', 'cash_flow_statement',
        each containing line items keyed by fiscal year date.
    """
    symbol = (ticker or ctx.deps.ticker).upper()
    await _emit(ctx, {"type": "tool_call", "tool": "get_financial_statements", "label": f"Fetching financial statements for {symbol}"})
    await asyncio.sleep(1)
    try:
        stock = yf.Ticker(symbol)
        result = {
            "income_statement": _df_to_dict(stock.financials),
            "balance_sheet": _df_to_dict(stock.balance_sheet),
            "cash_flow_statement": _df_to_dict(stock.cashflow),
        }
        await _emit(ctx, {"type": "tool_done", "tool": "get_financial_statements", "label": "Financial statements loaded"})
        return result
    except Exception:
        logger.exception("get_financial_statements failed for %s", symbol)
        raise



