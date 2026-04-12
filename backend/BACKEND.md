# Backend — Stock Research API

FastAPI backend powered by [PydanticAI](https://ai.pydantic.dev/) and Google Gemini.
An autonomous agent calls tools freely to produce deep equity research, then returns
the full message history for downstream summarization.

## Stack

| Layer | Library |
|---|---|
| Web framework | FastAPI + Uvicorn |
| AI agent | PydanticAI (`google-gla` provider) |
| LLM | Gemini 2.0 Flash (configurable) |
| Stock data | yfinance |
| Charting | mplfinance + matplotlib |

## Project structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py        # FastAPI app, CORS, /research/analyze endpoint
│   ├── models.py      # AnalyzeRequest / AnalyzeResponse Pydantic models
│   └── agent.py       # PydanticAI agent + all tools
├── requirements.txt
└── .env.example
```

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your GEMINI_API_KEY
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

## Endpoint

### `POST /research/analyze`

Runs the Gemini agent against a stock ticker. The agent can call tools in any
order it sees fit, generating and analyzing charts along the way.

**Request body**

```json
{
  "ticker": "AAPL",
  "context": [
    { "type": "text", "data": "Focus on near-term growth catalysts." },
    { "type": "image", "data": "<base64>", "media_type": "image/png" }
  ]
}
```

- `ticker` — stock symbol (case-insensitive)
- `context` — optional list of text strings and/or base64-encoded images to
  include as multimodal context for the agent

**Response**

```json
{
  "ticker": "AAPL",
  "message_history": [ ... ]
}
```

`message_history` is the complete pydantic-ai conversation — every user turn,
tool call, tool result, and assistant response — serialized to JSON. Feed it
into the forthcoming summary/recommendation endpoint.

## Agent tools

| Tool | Description |
|---|---|
| `get_price_chart` | Candlestick + volume chart (mplfinance) |
| `get_technical_chart` | Bollinger Bands, RSI (14), MACD (12/26/9) |
| `get_stock_fundamentals` | Valuation, margins, growth, balance sheet, analyst targets |
| `get_financial_statements` | Last 4 years: income statement, balance sheet, cash flow |
| `get_recent_news` | Recent news headlines and summaries |

All chart tools return `BinaryContent(media_type="image/png")` which Gemini
receives inline as a multimodal image it can directly analyze.
Each tool accepts an optional `ticker` override so the agent can pull
comparative data for related companies.
