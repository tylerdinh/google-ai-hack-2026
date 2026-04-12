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
from pydantic_ai import Agent, BinaryContent, ModelRetry, RunContext

matplotlib.use("Agg")

logger = logging.getLogger(__name__)

_MODEL = f"google-gla:{os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')}"

SYSTEM_PROMPT = """\
You are an expert equity research analyst. Your entire analysis must be laser-focused on the
user's specific question and intent — every observation you make and every tool you call should
serve to answer that question as directly and concretely as possible.

You have access to tools that generate price charts, technical indicator charts, fetch fundamental
metrics, and retrieve financial statements.

WORKFLOW — follow this structure exactly, and do not deviate:

1. INTRODUCTION: Before calling any tool, write one or two paragraphs that frame the analysis
   around the user's specific question. State what angle you will investigate and why the tools
   you are about to call are relevant to answering it.

2. TOOL + ANALYSIS LOOP: For each tool you call, follow this exact sequence:
   a. Call the tool.
   b. Once you receive the result, write a focused analytical paragraph about what that data
      reveals, always tying it explicitly back to the user's question.
   c. Only after writing that analysis, decide whether to call the next tool.
   Repeat until you have gathered everything needed to answer the question thoroughly.
   Call as many tools as useful — more depth is better.

3. CONCLUSION: After all tools have been analyzed, write two or three paragraphs that synthesize
   your findings. Directly answer the user's question with a clear, evidence-based stance.
   Acknowledge key risks or counterarguments and note what would change your view.

TOOL PARAMETER GUIDANCE:
- Call as many or as few tools as the question warrants. There is no minimum or maximum.
  A simple momentum question may only need a price chart and technicals. A deep valuation
  question may need fundamentals, financial statements, and multiple chart timeframes.
- You may call the same tool multiple times with different parameters. For example: call
  get_price_chart once with '1y' to see the trend, then again with '1mo' to zoom into
  recent price action. Call get_technical_chart with a short period to assess entry timing
  and again with a long period to assess the macro trend. This is encouraged.
- Choose chart periods and intervals based on the user's intent:
    Short-term / momentum: period '1mo'–'3mo', interval '1d'
    Swing / position trading: period '6mo', interval '1d' or '1wk'
    Long-term trend: period '1y'–'2y', interval '1d' or '1wk'
    Multi-year / structural: period '5y', interval '1wk' or '1mo'
- Tune technical indicator parameters when precision matters: tighter RSI periods (9) for
  momentum reads, wider (21) for trend confirmation; narrow Bollinger Bands for breakout
  signals, wider for volatility context.
- Use 'quarterly' frequency for financial statements when the user's question is about
  recent trend, beat/miss history, or near-term outlook. Use 'annual' for long-term
  structural analysis.
- Use the ticker override to pull peer data for relative valuation or competitive analysis.
- The full message history is always in view. Build on prior tool results — deepen them,
  do not repeat observations already made.

REPORT ASSEMBLY:
Your prose output — introduction, per-tool analysis paragraphs, and conclusion — will be
assembled together with the chart images produced by tool calls to form a published research
report. The chart image for each tool sits inline next to the paragraph that analyzes it.
Write each analytical paragraph as a self-contained, report-quality section: specific, crisp,
and meaningful to a reader who sees your words alongside the corresponding chart or data.
The full sequence of messages and images will be extracted in order, so structure matters:
each piece of writing should flow naturally from the previous one and set up the next.

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
    # Tracks the last completed tool for writing-status notifications.
    _last_completed_tool_label: str = field(default="", compare=False)


agent: Agent[StockDeps, str] = Agent(
    _MODEL,
    deps_type=StockDeps,
    system_prompt=SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_TOOL_FRIENDLY_NAMES: dict[str, str] = {
    "get_price_chart": "price chart",
    "get_technical_chart": "technical indicators",
    "get_stock_fundamentals": "fundamental metrics",
    "get_financial_statements": "financial statements",
}


async def _emit(ctx: RunContext[StockDeps], event: dict) -> None:
    """Push an event onto the SSE queue if one is attached."""
    if ctx.deps.event_queue is None:
        return
    await ctx.deps.event_queue.put(event)
    # After each tool completes, immediately notify that the LLM is analyzing its output.
    if event.get("type") == "tool_done":
        tool = event.get("tool", "")
        friendly = _TOOL_FRIENDLY_NAMES.get(tool, tool)
        ctx.deps._last_completed_tool_label = friendly
        await ctx.deps.event_queue.put({
            "type": "agent_status",
            "message": f"Analyzing {friendly} output...",
        })


async def run_agent_stream(prompt: str | list, deps: StockDeps) -> str:
    """Run the agent, emitting writing-phase status events to the queue.

    Emits:
      agent_status "Writing introduction..." before the agent run begins.
      agent_status "Analyzing <tool> output..." immediately after each tool completes.
    Tool events (tool_call, tool_done) are emitted by the tools themselves via _emit.
    Returns all_messages_json() as a string when the run completes.
    """
    if deps.event_queue is not None:
        await deps.event_queue.put({
            "type": "agent_status",
            "message": "Writing introduction...",
        })

    result = await agent.run(prompt, deps=deps)

    if deps.event_queue is not None:
        await deps.event_queue.put({
            "type": "agent_status",
            "message": "Wrapping things up...",
        })

    return result.all_messages_json()


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


@agent.tool(retries=2)
async def get_price_chart(
    ctx: RunContext[StockDeps],
    period: str,
    interval: str,
    chart_type: str,
    ticker: str | None = None,
) -> BinaryContent:
    """Generate a price chart with volume bars for a stock.
    Call this multiple times with different periods/intervals to compare timeframes.

    Args:
        period: Lookback period. Choose explicitly based on the user's intent.
            '1mo' or '3mo' for short-term / momentum analysis.
            '6mo' for medium-term swing or position trading.
            '1y' or '2y' for long-term trend and cycle analysis.
            '5y' for multi-year buy-and-hold or structural trend analysis.
        interval: Bar interval. Choose to match the period and intent.
            '1d' — daily bars, good for periods up to 1y.
            '1wk' — weekly bars, better for 1y–5y to reduce noise.
            '1mo' — monthly bars, best for 5y+ structural views.
        chart_type: Visual style of the price chart. Choose deliberately.
            'candle' — candlestick, best for reading open/high/low/close and candlestick patterns.
            'ohlc'   — OHLC bar chart, similar information in a different style.
            'line'   — closing price line, cleaner for very long periods or peer comparisons.
        ticker: Ticker symbol. Omit to use the primary analysis ticker.
            Pass a peer ticker to generate a comparative chart.

    Returns:
        A PNG price chart image with volume.
    """
    _VALID_PERIODS = {"1mo", "3mo", "6mo", "1y", "2y", "5y"}
    _VALID_INTERVALS = {"1d", "1wk", "1mo"}
    _INCOMPATIBLE = {
        # interval -> periods too short to return enough bars
        "1wk": {"1mo"},
        "1mo": {"1mo", "3mo"},
    }
    if period not in _VALID_PERIODS:
        raise ModelRetry(
            f"Invalid period '{period}'. Must be one of: {sorted(_VALID_PERIODS)}. "
            "Choose again."
        )
    if interval not in _VALID_INTERVALS:
        raise ModelRetry(
            f"Invalid interval '{interval}'. Must be one of: {sorted(_VALID_INTERVALS)}. "
            "Choose again."
        )
    if period in _INCOMPATIBLE.get(interval, set()):
        raise ModelRetry(
            f"Incompatible combination: period='{period}' is too short for interval='{interval}'. "
            f"Use '1d' for short periods, or choose a longer period for '{interval}'."
        )
    symbol = (ticker or ctx.deps.ticker).upper()
    label_suffix = f"{period} / {interval}"
    await _emit(ctx, {"type": "tool_call", "tool": "get_price_chart", "label": f"Fetching price chart for {symbol} ({label_suffix})"})
    await asyncio.sleep(1)
    try:
        hist = yf.Ticker(symbol).history(period=period, interval=interval)
        if hist.empty:
            raise ModelRetry(
                f"No price data returned for {symbol} with period='{period}', interval='{interval}'. "
                "Try a different period/interval combination."
            )

        valid_types = {"candle", "ohlc", "line"}
        mpf_type = chart_type if chart_type in valid_types else "candle"

        buf = io.BytesIO()
        mpf.plot(
            hist,
            type=mpf_type,
            style="charles",
            title=f"{symbol} — Price & Volume ({period}, {interval})",
            volume=True,
            figsize=(14, 8),
            savefig=dict(fname=buf, dpi=120, bbox_inches="tight"),
        )
        buf.seek(0)
        img_bytes = buf.read()
        result = BinaryContent(data=img_bytes, media_type="image/png")
        ctx.deps.image_store.append({"tool": "get_price_chart", "ticker": symbol, "period": period, "interval": interval, "data": base64.b64encode(img_bytes).decode()})
        await _emit(ctx, {"type": "tool_done", "tool": "get_price_chart", "label": f"Price chart ready ({label_suffix})"})
        return result
    except ModelRetry:
        raise
    except Exception:
        logger.exception("get_price_chart failed for %s", symbol)
        raise


@agent.tool(retries=2)
async def get_technical_chart(
    ctx: RunContext[StockDeps],
    period: str,
    interval: str,
    rsi_period: int,
    bb_period: int,
    bb_std: float,
    macd_fast: int,
    macd_slow: int,
    macd_signal: int,
    ticker: str | None = None,
) -> BinaryContent:
    """Generate a technical analysis chart with Bollinger Bands, RSI, and MACD.
    Call this multiple times with different periods or indicator settings to compare signals.

    Args:
        period: Lookback period. Choose based on the user's intent.
            '3mo' for short-term momentum or entry/exit timing.
            '6mo' for medium-term trend and indicator analysis.
            '1y' for broader cycle context.
            '2y' to assess how indicators have behaved across a full market cycle.
        interval: Bar interval. Choose to match the period.
            '1d' for daily bars (periods up to 1y). '1wk' for weekly (longer periods).
        rsi_period: RSI lookback window in bars.
            9 for a sensitive, fast-reacting RSI suited to momentum / short-term reads.
            14 for the classic, widely-followed setting.
            21 for a smoother RSI better suited to trend confirmation.
        bb_period: Bollinger Band SMA period.
            10 tightens bands for breakout detection.
            20 is the classic setting.
            50 widens bands to mark major support/resistance levels.
        bb_std: Standard deviation multiplier for Bollinger Band width.
            1.5 for tighter, more responsive bands.
            2.0 is the classic setting.
            2.5 or 3.0 for extreme-move detection only.
        macd_fast: Fast EMA period. 12 is classic; use 5 for a more responsive signal.
        macd_slow: Slow EMA period. 26 is classic; use 35 for a longer-term signal.
        macd_signal: Signal line EMA period. 9 is classic.
        ticker: Ticker symbol. Omit to use the primary analysis ticker.
            Pass a peer ticker to compare technicals side by side.

    Returns:
        A PNG chart with three panels: price + Bollinger Bands, RSI, MACD.
    """
    _VALID_PERIODS = {"3mo", "6mo", "1y", "2y"}
    _VALID_INTERVALS = {"1d", "1wk"}
    _INCOMPATIBLE = {"1wk": {"3mo"}}
    if period not in _VALID_PERIODS:
        raise ModelRetry(
            f"Invalid period '{period}'. Must be one of: {sorted(_VALID_PERIODS)}. Choose again."
        )
    if interval not in _VALID_INTERVALS:
        raise ModelRetry(
            f"Invalid interval '{interval}'. Must be one of: {sorted(_VALID_INTERVALS)}. Choose again."
        )
    if period in _INCOMPATIBLE.get(interval, set()):
        raise ModelRetry(
            f"Incompatible combination: period='{period}' is too short for interval='{interval}'. "
            "Use '1d' for 3mo, or choose a longer period for weekly bars."
        )
    if rsi_period < 2:
        raise ModelRetry(f"rsi_period must be at least 2, got {rsi_period}.")
    if bb_period < 2:
        raise ModelRetry(f"bb_period must be at least 2, got {bb_period}.")
    if bb_std <= 0:
        raise ModelRetry(f"bb_std must be positive, got {bb_std}.")
    if macd_fast >= macd_slow:
        raise ModelRetry(
            f"macd_fast ({macd_fast}) must be less than macd_slow ({macd_slow}). Choose again."
        )
    if macd_signal < 1:
        raise ModelRetry(f"macd_signal must be at least 1, got {macd_signal}.")
    symbol = (ticker or ctx.deps.ticker).upper()
    label_suffix = f"{period} / {interval} | RSI({rsi_period}) BB({bb_period},{bb_std}) MACD({macd_fast},{macd_slow},{macd_signal})"
    await _emit(ctx, {"type": "tool_call", "tool": "get_technical_chart", "label": f"Generating technical indicators for {symbol} ({period})"})
    await asyncio.sleep(1)
    try:
        hist = yf.Ticker(symbol).history(period=period, interval=interval)
        if hist.empty:
            raise ModelRetry(
                f"No price data returned for {symbol} with period='{period}', interval='{interval}'. "
                "Try a different combination."
            )

        close = hist["Close"]

        # Bollinger Bands
        sma = close.rolling(bb_period).mean()
        std = close.rolling(bb_period).std()
        bb_upper = sma + bb_std * std
        bb_lower = sma - bb_std * std

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
        rsi = 100 - (100 / (1 + gain / loss))

        # MACD
        ema_fast = close.ewm(span=macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=macd_slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=macd_signal, adjust=False).mean()
        macd_hist_vals = macd_line - signal_line

        fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
        fig.suptitle(f"{symbol} — Technical Analysis ({period}, {interval})", fontsize=14, y=1.01)

        # Panel 1: Price + Bollinger Bands
        axes[0].plot(close.index, close, label="Close", linewidth=1.5, color="#1f77b4")
        axes[0].plot(close.index, sma, label=f"SMA {bb_period}", linestyle="--", linewidth=1, color="orange")
        axes[0].fill_between(close.index, bb_lower, bb_upper, alpha=0.12, color="#1f77b4", label=f"BB ({bb_std}σ)")
        axes[0].set_ylabel("Price")
        axes[0].legend(loc="upper left", fontsize=8)
        axes[0].grid(True, alpha=0.3)

        # Panel 2: RSI
        axes[1].plot(rsi.index, rsi, color="purple", linewidth=1.5)
        axes[1].axhline(70, color="red", linestyle="--", linewidth=1, label="Overbought (70)")
        axes[1].axhline(30, color="green", linestyle="--", linewidth=1, label="Oversold (30)")
        axes[1].axhline(50, color="gray", linestyle=":", linewidth=0.8)
        axes[1].set_ylim(0, 100)
        axes[1].set_ylabel(f"RSI ({rsi_period})")
        axes[1].legend(loc="upper left", fontsize=8)
        axes[1].grid(True, alpha=0.3)

        # Panel 3: MACD
        bar_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in macd_hist_vals]
        axes[2].bar(macd_hist_vals.index, macd_hist_vals, color=bar_colors, alpha=0.6, width=1.5, label="Histogram")
        axes[2].plot(macd_line.index, macd_line, label="MACD", linewidth=1.5, color="#1f77b4")
        axes[2].plot(signal_line.index, signal_line, label="Signal", linewidth=1.5, color="orange")
        axes[2].axhline(0, color="black", linewidth=0.8)
        axes[2].set_ylabel(f"MACD ({macd_fast}/{macd_slow}/{macd_signal})")
        axes[2].legend(loc="upper left", fontsize=8)
        axes[2].grid(True, alpha=0.3)

        plt.tight_layout()
        img_bytes = _generate_png(fig)
        result = BinaryContent(data=img_bytes, media_type="image/png")
        ctx.deps.image_store.append({"tool": "get_technical_chart", "ticker": symbol, "period": period, "interval": interval, "data": base64.b64encode(img_bytes).decode()})
        await _emit(ctx, {"type": "tool_done", "tool": "get_technical_chart", "label": f"Technical chart ready ({period})"})
        return result
    except ModelRetry:
        raise
    except Exception:
        logger.exception("get_technical_chart failed for %s", symbol)
        raise


@agent.tool(retries=2)
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
    except ModelRetry:
        raise
    except Exception:
        logger.exception("get_stock_fundamentals failed for %s", symbol)
        raise


@agent.tool(retries=2)
async def get_financial_statements(
    ctx: RunContext[StockDeps],
    frequency: str,
    max_periods: int,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Retrieve financial statements: income statement, balance sheet, and cash flow statement.
    Call this twice — once annual, once quarterly — to get both structural trends and recent momentum.

    Args:
        frequency: Reporting frequency. Choose deliberately.
            'annual'    — fiscal year data, up to max_periods years. Best for long-term
                          structural analysis (margin expansion, debt trajectory, etc.).
            'quarterly' — last N quarters. Best for recent trend, beat/miss history,
                          and near-term trajectory analysis.
        max_periods: Number of periods to return. Choose based on desired depth.
            For annual: 4 years is standard; use 6 or 8 for a longer historical view.
            For quarterly: 4 covers the last year; use 8 for two years of quarterly data.
        ticker: Ticker symbol. Omit to use the primary analysis ticker.

    Returns:
        Dict with keys 'income_statement', 'balance_sheet', 'cash_flow_statement',
        each containing line items keyed by period date.
    """
    if frequency not in {"annual", "quarterly"}:
        raise ModelRetry(
            f"Invalid frequency '{frequency}'. Must be 'annual' or 'quarterly'. Choose again."
        )
    if max_periods < 1:
        raise ModelRetry(f"max_periods must be at least 1, got {max_periods}.")
    symbol = (ticker or ctx.deps.ticker).upper()
    freq_label = frequency.capitalize()
    await _emit(ctx, {"type": "tool_call", "tool": "get_financial_statements", "label": f"Fetching {freq_label} financial statements for {symbol}"})
    await asyncio.sleep(1)
    try:
        stock = yf.Ticker(symbol)
        if frequency == "quarterly":
            result = {
                "income_statement": _df_to_dict(stock.quarterly_financials, max_periods=max_periods),
                "balance_sheet": _df_to_dict(stock.quarterly_balance_sheet, max_periods=max_periods),
                "cash_flow_statement": _df_to_dict(stock.quarterly_cashflow, max_periods=max_periods),
            }
        else:
            result = {
                "income_statement": _df_to_dict(stock.financials, max_periods=max_periods),
                "balance_sheet": _df_to_dict(stock.balance_sheet, max_periods=max_periods),
                "cash_flow_statement": _df_to_dict(stock.cashflow, max_periods=max_periods),
            }
        await _emit(ctx, {"type": "tool_done", "tool": "get_financial_statements", "label": f"{freq_label} financial statements loaded"})
        return result
    except ModelRetry:
        raise
    except Exception:
        logger.exception("get_financial_statements failed for %s", symbol)
        raise



