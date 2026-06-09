# FoundrAI — Autonomous AI Advisory Platform for Startup Founders

FoundrAI gives startup founders a private AI analyst. Upload financial CSVs, ask natural-language questions, run scenario simulations, and get structured answers backed by your own data, live market news, and four specialist AI agents — all streamed in real time.

**Live Demo:** [Frontend → Vercel](https://foundr-ai-coral.vercel.app) · [Backend → Render](https://foundr-ai-api.onrender.com) · Database → Supabase

---

## What It Does

1. **Upload financials** — CSV, Excel, PDF, or images. The backend extracts text, parses financial columns (revenue, burn_rate, headcount, CAC, LTV) into a structured row store, and indexes the document into pgvector.
2. **Ask questions** — The chatbot fetches your actual CSV rows directly from the database and passes them to Groq. A query classifier routes to: **Data** (exact CSV analysis), **Web** (DuckDuckGo search), or **Advisory** (4-agent pipeline).
3. **Run simulations** — Bear / Base / Bull Monte Carlo (10K paths, NumPy-vectorised, <200ms) seeded from your uploaded metrics.
4. **View charts** — Recharts AreaChart with P10/P50/P90 confidence bands.

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Backend API | FastAPI + Uvicorn (Python 3.12) | Async SSE streaming, type-safe Pydantic schemas |
| AI LLM | Groq API — Llama 3.1-8b / 3.3-70b / 3.2-Vision | ~500 tok/sec, vision for image analysis |
| AI Agents | 3-Route Orchestrator + 4-Agent Pipeline | ~73% token savings via query classification |
| Embeddings | fastembed `BAAI/bge-small-en-v1.5` (ONNX Runtime) | 384-dim embeddings, no PyTorch/CUDA — fits 512MB RAM |
| Vector DB | pgvector on Supabase PostgreSQL 15 | Cosine similarity search, same DB as app data |
| Simulation | NumPy vectorised Monte Carlo (10K paths) | <200ms, no GPU required |
| Auth | Supabase Auth + ES256 JWKS middleware | ES256 JWT (JWKS-verified), TOTP MFA, self-healing profile sync |
| Database | Supabase PostgreSQL 15 | RLS per table, pgvector extension, file storage |
| Frontend | React 18 + Vite 5 + TypeScript 5 | SPA, HMR, tree-shaking |
| Styling | TailwindCSS 3 | Utility-first dark theme |
| Charts | Recharts 2 | AreaChart confidence bands |
| **Backend Deploy** | **Render** | Managed Python hosting, GitHub auto-deploy |
| **Frontend Deploy** | **Vercel** | Edge CDN, instant deploys, HTTPS automatic |
| **Keep-Alive** | **GitHub Actions cron** | Pings `/health` every 5 min — prevents Render free-tier sleep |

---

## Repository Structure

```
FoundrAI/
├── .github/
│   └── workflows/
│       ├── deploy.yml               # CI: backend tests + frontend build on every push
│       └── keep-alive.yml           # Cron: pings Render /health every 5 min
│
├── backend/
│   ├── main.py                      # FastAPI app, CORS, lifespan, routers, root health route
│   ├── config.py                    # pydantic-settings env vars + cors_allow_origin_regex
│   ├── Dockerfile                   # Uses ${PORT:-8000}, pre-bakes fastembed ONNX model
│   ├── auth/
│   │   ├── router.py                # Register, Login (auto-creates missing profile), MFA, /me
│   │   └── middleware.py            # ES256 JWKS verification + self-healing founder profile
│   ├── agents/
│   │   ├── orchestrator.py          # 3-Route pipeline (data/web/advisory) + CSV context
│   │   ├── market_agent.py          # TAM/SAM/SOM analysis
│   │   ├── risk_agent.py            # Risk scoring
│   │   ├── revenue_agent.py         # Revenue forecasting
│   │   └── strategy_agent.py        # Executive synthesis
│   ├── rag/
│   │   ├── pipeline.py              # RAGPipeline: index + query
│   │   ├── indexer.py               # Chunking + embedding + pgvector upsert
│   │   ├── encoder.py               # fastembed ONNX singleton (replaces sentence-transformers)
│   │   └── retriever.py             # pgvector cosine similarity search
│   ├── automl/
│   │   ├── monte_carlo.py           # 10K-path NumPy simulation
│   │   └── trainer.py               # Metric extraction from CSV/Excel/text
│   ├── news/
│   │   ├── ingestion.py             # NewsCatcher + news-please + RAG indexing
│   │   └── scheduler.py             # APScheduler 6h interval
│   ├── routers/
│   │   ├── upload.py                # POST /upload/financials (async background)
│   │   ├── query.py                 # POST /query (SSE) + _fetch_upload_context()
│   │   ├── simulate.py              # POST /simulate (guards against missing upload_id)
│   │   ├── charts.py                # GET /charts/simulations
│   │   ├── founders.py              # Profile + uploads CRUD
│   │   └── news.py                  # GET /news/latest
│   ├── storage/
│   │   ├── supabase_client.py       # Singleton client
│   │   ├── supabase_storage.py      # File upload helpers
│   │   ├── extractors.py            # CSV/Excel/PDF/DOCX/Image text extraction
│   │   └── migrations/              # 001–008 SQL scripts
│   └── tests/
│       ├── test_agents.py
│       ├── test_api.py
│       ├── test_automl.py
│       └── test_extractors.py
│
├── frontend/
│   ├── vercel.json                  # /api/* proxy → Render + SPA catch-all
│   └── src/
│       ├── features/
│       │   ├── auth/                # Login, Register, MfaPage (TOTP enroll + verify)
│       │   ├── dashboard/           # Metrics overview
│       │   ├── upload/              # File upload UI
│       │   ├── query/               # AI chatbot (SSE streaming, CSV badge)
│       │   ├── simulate/            # Monte Carlo sliders + chart
│       │   └── charts/              # Historical simulation charts
│       └── shared/
│           ├── api/client.ts        # fetch wrapper + streamQuery() — SSE hits Render directly
│           ├── auth/supabase.ts     # Supabase JS client
│           └── components/
│               ├── Layout.tsx       # Sidebar + backend wake-up banner (cold start UX)
│               ├── ProtectedRoute.tsx
│               └── Spinner.tsx
│
├── system_design.html               # Full system design documentation
├── requirements.txt
├── .env.example
└── README.md
```

---

## Local Development

### Prerequisites
- Miniconda or Python 3.12+
- Node.js 20+
- Supabase project (free at supabase.com)
- Groq API key (free at console.groq.com/keys)

### Backend

```bash
# From project root
conda create -n foundr-ai python=3.12 -y
conda activate foundr-ai

# Install compiled packages via conda first (avoids C compiler errors on Windows)
conda install numpy scipy pandas scikit-learn -y

# Then install the rest
pip install -r requirements.txt

# Copy and fill env vars
cp .env.example .env
# Edit .env with your Supabase + Groq credentials

# Run DB migrations — paste each in Supabase → SQL Editor (in order):
# 001 → 002 → 003 → 004 → 004b → 005 → 006 → 007 → 008

# Start backend (must run from project root, not from backend/)
uvicorn backend.main:app --reload --port 8000 --host 0.0.0.0
```

> **Note:** On first startup, fastembed downloads the ONNX model (~33MB) from HuggingFace. This takes ~15 seconds once, then it's cached locally.

### Frontend

```bash
cd frontend
npm install
npm run dev
# Opens at http://localhost:5173
```

### Tests

```bash
pytest backend/tests/ -v --cov=backend --cov-report=term-missing
```

---

## Deployment

### Backend → Render

1. **Push to GitHub** (`git push origin main`)

2. **Create Web Service on Render**
   - Go to render.com → New → Web Service
   - Connect your GitHub repo
   - **Runtime:** Docker (uses `backend/Dockerfile`)
   - The Dockerfile pre-bakes the fastembed ONNX model at build time for instant startup

3. **Set Environment Variables** in Render dashboard:

   | Variable | Value |
   |----------|-------|
   | `SUPABASE_URL` | `https://xxxx.supabase.co` |
   | `SUPABASE_KEY` | your anon key |
   | `SUPABASE_SERVICE_ROLE_KEY` | your service role key |
   | `SUPABASE_JWT_SECRET` | from Supabase → Settings → API → JWT Secret |
   | `GROQ_API_KEY` | `gsk_xxxxxxxx` |
   | `ENVIRONMENT` | `production` |
   | `CORS_ORIGINS` | `https://your-app.vercel.app` |
   | `LOG_LEVEL` | `INFO` |

4. **Click Create Web Service** — Render builds and deploys automatically.

5. **Verify:** `curl https://foundr-ai-api.onrender.com/health`

> **Free tier cold starts:** The Render free tier sleeps after 15 minutes of inactivity. The included GitHub Actions cron (`keep-alive.yml`) pings `/health` every 5 minutes to prevent this. No external service required.

---

### Frontend → Vercel

1. **`frontend/vercel.json`** is already configured with:
   - `/api/:path*` → proxied to Render backend (no CORS issues for regular calls)
   - `/(.*)`  → `/index.html` (SPA routing)

2. **Create Vercel Project**
   - Go to vercel.com → New Project → Import GitHub repo
   - **Framework Preset:** Vite
   - **Root Directory:** `frontend`
   - **Build Command:** `npm run build`
   - **Output Directory:** `dist`

3. **Set Environment Variables** in Vercel dashboard:

   | Variable | Value |
   |----------|-------|
   | `VITE_SUPABASE_URL` | `https://xxxx.supabase.co` |
   | `VITE_SUPABASE_ANON_KEY` | your anon key (safe to expose) |

   > `VITE_API_URL` is **not needed** — the `vercel.json` proxy handles all `/api/*` routing automatically.
   > `VITE_STREAM_URL` is **not needed** — the Render URL is hardcoded as the SSE fallback in `client.ts`.

4. **Disable Deployment Protection**
   - Vercel → Project → Settings → Deployment Protection → **Disabled**
   - Without this, preview URLs return 403 to all non-Vercel-team visitors.

5. **Click Deploy** — every `git push` to `main` auto-deploys.

6. **Update CORS on Render** — add your Vercel production URL to `CORS_ORIGINS` env var on Render. Preview URLs are covered automatically by the `CORS_ALLOW_ORIGIN_REGEX` (`https://.*\.vercel\.app`).

---

### CI/CD (after initial setup)

```
git push origin main
  → GitHub Actions: runs backend unit tests + frontend build check (~2 min)
  → Render: rebuilds and redeploys backend (~3-5 min)
  → Vercel: rebuilds and redeploys frontend (~30 sec)
  → All live automatically, no manual steps
```

---

## Keep-Alive (Render Free Tier)

The file `.github/workflows/keep-alive.yml` runs a GitHub Actions cron job every 5 minutes that pings [`https://foundr-ai-api.onrender.com/health`](https://foundr-ai-api.onrender.com/health). This keeps the Render free-tier instance awake 24/7 without any external paid service.

To verify it's working: **GitHub → your repo → Actions → Keep Render Alive**

---

## Database Migrations

Run in order in Supabase → SQL Editor:

| File | Creates |
|------|---------|
| `001_create_founders.sql` | founders profile table |
| `002_create_document_embeddings.sql` | pgvector embeddings table + IVFFlat index |
| `003_create_news_tables.sql` | news_articles table |
| `004_create_uploads.sql` | uploads table |
| `004b_add_metrics_column.sql` | initial_metrics column on uploads |
| `005_create_simulation_results.sql` | Monte Carlo results table |
| `006_create_financial_rows.sql` | Per-row CSV storage for direct LLM analysis |
| `007_create_chat_history.sql` | Chat history persistence |
| `008_add_active_upload_id.sql` | active_upload_id column on founders |

---

## Key Design Decisions

**CSV Context Injection** — Instead of relying purely on vector similarity search (which misses exact numbers), the chatbot fetches actual CSV rows from `financial_rows` and passes them directly to Groq. This means the LLM can compute exact totals, averages, and growth rates from your data.

**Immediate Upload Response** — The upload endpoint returns in <100ms. All heavy work (Storage, embedding, financial_rows insert) runs in a FastAPI `BackgroundTask` so the user isn't blocked waiting.

**3-Route Token Efficiency** — The query classifier costs ~150 tokens. Data and web routes cost ~700–900 tokens total. The full advisory route costs ~8,000 tokens. Routing saves ~73% of token spend across typical usage.

**ONNX Embeddings (no PyTorch)** — `sentence-transformers` was replaced with `fastembed` (ONNX Runtime). PyTorch + CUDA binaries total ~2GB and caused OOM crashes on Render's 512MB free tier. The ONNX model is ~33MB and uses ~100MB RAM at runtime with identical 384-dim output.

**ES256 JWT Verification** — Supabase issues ES256 tokens (ECDSA). The auth middleware fetches the JWKS public key from Supabase's `.well-known/jwks.json` endpoint and verifies signatures cryptographically — no shared secret required.

**Self-Healing Founder Profile** — If a user authenticates via Supabase but their `founders` row is missing (e.g. created directly in Supabase dashboard), the auth middleware and login endpoint auto-create a default profile instead of returning 403.

**SSE Bypasses Vercel Proxy** — Vercel's edge proxy buffers chunked responses, breaking real-time streaming. The `streamQuery()` function calls Render directly using a hardcoded fallback URL, bypassing the proxy entirely for SSE.

---

## License

MIT License.
#   F o u n d r A I  
 