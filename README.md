# Boardroom

An AI-powered stock deep research platform to ask questions about any stock and get an expert analysis, with a live multi-agent council debate using the LLM-as-a-judge technique for evaluation on binary questions.

## Stack

- **Backend** — Python, FastAPI, PydanticAI, Google Gemini, Brave Search, ElevenLabs, yfinance, Supabase
- **Frontend** — React, TypeScript, Vite, Tailwind CSS, Supabase JS

---

## Running locally

### 1. Clone and configure environment variables

Copy the example and fill in your keys:

```bash
cp .env.example .env
```

Required keys in `.env`:

```
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

BRAVE_API_KEY=
ELEVENLABS_API_KEY=

SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=

ALLOWED_ORIGINS=http://localhost:5173
```

### 2. Start the backend

```bash
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

> Requires [uv](https://github.com/astral-sh/uv). Install with `pip install uv` or `curl -Ls https://astral.sh/uv/install.sh | sh`.

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

The Vite dev server proxies all API calls (`/api`, `/research`, `/stocks`, `/analyses`, `/auth`) to the backend on port 8000.

---

## Production build

```bash
cd frontend && npm run build
cd backend && uv run uvicorn app.main:app --port 8000
```

The backend will serve the built React app from `frontend/dist/` at [http://localhost:8000](http://localhost:8000).

---

## Database

The app uses Supabase. Run the migration to create the required tables:

```sql
-- Run contents of backend/migrations/001_schema.sql in your Supabase SQL editor
```
