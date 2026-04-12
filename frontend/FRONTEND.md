# Frontend Stock UI

## Stock Data Setup

The stock list page and stock detail page now use backend proxy endpoints powered by Yahoo Finance data.

No API key is required for stock quotes and chart candles.

### 1. Start backend API

From `google-ai-hack-2026/backend` run your FastAPI server (for example with uvicorn).

Example:

uvicorn main:app --reload --port 8000

### 2. Open frontend pages

The frontend defaults to `http://127.0.0.1:8000` for stock API calls.

If your backend runs elsewhere, set this before scripts run:

window.STOCK_API_BASE_URL = 'http://YOUR_HOST:YOUR_PORT';

## Pages using live data (through backend)

- stocks.html
  - Fetches quote data for: AAPL, GOOG, AMZN, RBLX
  - Fetches short time series to draw mini sparkline charts via `/api/stocks/time-series`

- stock.html
  - Reads symbol from query param: symbol
  - Fetches quote and daily time series for that symbol via backend
  - Renders summary metrics and a candlestick chart

## Notes

- If backend is down or Yahoo data is unavailable, UI shows graceful fallback text.
