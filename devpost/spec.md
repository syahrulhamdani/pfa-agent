---
doc: spec
status: approved
---

# pfa — Technical Spec

## How This Works, In Plain Language

pfa is one Python program plus one web page, backed by one Postgres database. Everything that can wait on something slow (Telegram, Gemini, the database, the browser's requests) is written to run asynchronously, so one slow step never freezes the rest.

- **The Python program (FastAPI)** does three jobs at once: it serves the data the web page needs, it runs the Telegram bot by repeatedly asking Telegram "any new messages?" (polling, so nothing needs to be exposed to the internet), and it runs a small clock that fires the nudges and the Monday summary.
- **LangGraph orchestrates every LLM call.** Instead of scattered prompts, each job is a small graph of steps: one graph reads uploads, one handles chat, one writes recommendations. Each step does one thing, and the graph decides what happens next.
- **Two Gemini models** do the thinking. A fast, small one (Flash Lite) chats with you and writes recommendations. A stronger one (Pro) reads receipts and statements and turns them into rows.
- **Postgres** stores banks, cards, transactions, budgets and goals. A transaction is only "real" once you confirm it; until then it is held as pending.
- **The web page (React)** asks the Python program for data every few seconds, so a confirmed transaction appears without you reloading.

Why this shape: one process is easy to start and debug, polling and a refetch timer avoid public URLs and websockets, and the demo runs entirely on your laptop.

## The Core Journey Through the System

PRD ref: `prd.md > The Core Journey`.

1. **You send a receipt or statement in Telegram.** The bot (async polling) downloads it with `getFile` straight into memory, saves a record in `uploads` (no file is written to disk), and instantly replies "processing" (`prd.md > Upload and extraction`).
2. **The extraction graph runs as a background task** so the chat stays usable. Steps: detect file type → parse (CSV and Excel rows are read in Python; images and PDFs go straight to Gemini) → extract fields with Gemini Pro → infer the card → check which required fields are missing. Results are stored as `pending` transactions.
3. **The bot replies to your original message** with the extracted fields. Missing or unreadable fields are listed and you are asked to fill them in; a missing card shows your cards as buttons. For a statement, the reply gives the total count, highest, lowest and total amount (`prd.md > Confirmation and data fields`).
4. **The graph pauses for your confirmation** (a human-in-the-loop interrupt). Your tap on Confirm, or a typed correction that Flash Lite parses into field changes, resumes it. Confirming flips pending rows to `confirmed`; one tap confirms a whole statement.
5. **The reply includes a link** to `http://localhost:5173/transactions/today`. The web page loads today's confirmed transactions from the API and refetches every few seconds (`prd.md > Web app: transactions and analytics`).
6. **You manage banks, cards, budgets and goals in the web page**, which writes through the API to Postgres (`prd.md > Budgets`, `prd.md > Goals`).
7. **The clock fires nudges** at the stored slot times. On Monday the recommendation graph runs: aggregates are computed in SQL, Flash Lite writes the short recommendations, the summary is saved and sent to Telegram with a dashboard link (`prd.md > Adaptive nudges`, `prd.md > Weekly summary and recommendations`).
8. **You can ask in chat** for insights at any time; the chat graph routes the question, fetches the computed aggregates it needs, and answers from them.

## Stack

| Piece | Choice | Rationale |
|---|---|---|
| Language/tooling | Python (pyenv-managed), `uv`, `ruff`, `black`, `pytest` + `pytest-asyncio`, `loguru` | Your standing toolchain; async tests added. |
| API | FastAPI, async endpoints — https://fastapi.tiangolo.com/ | Your choice; async by default. |
| LLM orchestration | LangGraph — https://langchain-ai.github.io/langgraph/ with `langchain-google-genai` — https://python.langchain.com/docs/integrations/chat/google_generative_ai/ | Your decision: all LLM calls run as graphs, using async `ainvoke`. |
| Graph state/pause | LangGraph interrupts with the Postgres checkpointer (`langgraph-checkpoint-postgres`, async saver) | Lets the extraction graph wait for your confirmation across messages. |
| Telegram | `python-telegram-bot` v20+ (native async, polling) — https://docs.python-telegram-bot.org/ | Polling chosen: works locally, no public URL. |
| Gemini | Flash Lite for chat and recommendations, Pro for extraction (your requirement) — https://ai.google.dev/gemini-api/docs | Model IDs held in env vars. |
| Scheduler | APScheduler `AsyncIOScheduler`, in-process — https://apscheduler.readthedocs.io/ | Accepted tradeoff: only runs while the app runs. |
| Database | PostgreSQL via Docker Compose — https://www.postgresql.org/docs/ | Your choice. |
| DB access | SQLAlchemy 2 async engine + `asyncpg`, Alembic with an async env — https://docs.sqlalchemy.org/ | Repository pattern on top; fully async. |
| File parsing | `openpyxl` (Excel) and the standard `csv` module, run off the event loop with `asyncio.to_thread` | Blocking parsers must not stall the loop. |
| Frontend | Vite + React + TypeScript — https://vite.dev/ | Accepted recommendation. |
| Charts | Recharts — https://recharts.org/ | Accepted with the frontend. |
| Frontend data | TanStack Query with `async/await` fetches and a few-second `refetchInterval` — https://tanstack.com/query | Non-blocking UI; "live" feel without websockets (your decision). |

Unverified, to check first in the build: the exact Gemini model IDs for Flash Lite and Pro; current LangGraph interrupt and Postgres-checkpointer APIs; and the current `python-telegram-bot` async polling inside a FastAPI lifespan.

## Where It Runs and How Someone Tries It

Everything runs locally; this is enough for the required demo video and the public GitHub repo. No deployment.

- Requirements: Python via pyenv, `uv`, Node, Docker, a Telegram bot token (from BotFather) and a Gemini API key.
- Config: `.env.example` is the env file (per your convention) with `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`, `GEMINI_CHAT_MODEL`, `GEMINI_EXTRACT_MODEL`, `WEB_BASE_URL`, `TIMEZONE`, `LOG_LEVEL`, `LOG_USE_BASIC_FORMAT`, `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `CATEGORIES_FILE`, `AUTH_SECRET`, `AUTH_LINK_TTL_MINUTES`, `AUTH_SESSION_DAYS`, `AUTH_COOKIE_SECURE`. Real secrets must not be committed to the public repo.
- Start:
  1. `docker compose up -d db`
  2. `uv run --env-file .env.example alembic upgrade head`
  3. `uv run --env-file .env.example uvicorn pfa.main:app --reload` (starts the API, bot polling and scheduler in one event loop)
  4. `cd web && npm install && npm run dev`
- To record: open the web app at `http://localhost:5173` and Telegram on your phone or desktop. Trigger the Monday summary and a nudge on demand with `/demo_summary` and `/demo_nudge` in Telegram.

## Look and Feel

Carried from `prd.md > Look and Feel`. Implementation direction:
- White page background, dark gray text, light gray dividers and card borders, a single accent color for primary actions and key figures. The reference page's CSS could not be read during the build, so `web/src/theme.css` uses Deloitte's published brand green (`#86BC25`, with `#26890D` for text) and an Open Sans-first font stack, all as CSS variables so one edit changes the theme.
- Clean sans-serif system font stack, hierarchy through size and weight, not color.
- Modular cards in a grid; generous white space; restrained, data-forward charts (one accent plus grays).
- Copy tone: concise and professional, no filler or emoji-heavy chatter. Telegram messages follow the same tone.

## Components

### Telegram bot
Receives messages and files by async polling; sends acknowledgements, threaded replies, confirmation buttons, nudges and summaries. Only responds to the configured chat id. Commands: `/login`, `/signout`, `/demo_summary`, `/demo_nudge`. Uploads start the extraction graph as a background task; casual messages start the chat graph.
PRD ref: `prd.md > Upload and extraction`, `prd.md > Confirmation and data fields`.

### Extraction graph
LangGraph graph with nodes: detect type → parse → extract (Gemini Pro, structured output) → infer card → validate required fields → request missing input / await confirmation (interrupt) → commit. Unreadable fields stay `null`. Statement summary (count, highest, lowest, total) is computed in code, not by the model. Receipt images are held in memory only: they go from Telegram to the model and are discarded when extraction ends, and they are never stored in graph state, so the Postgres checkpointer never holds them.
PRD ref: `prd.md > Upload and extraction`, `prd.md > Confirmation and data fields`.

### Chat graph
Flash Lite routes a message to: casual reply, insights lookup, or recommendation request. Lookup nodes call the analytics service and answer from its numbers; the model never queries the database freely. A correction message during confirmation is routed to the extraction graph's resume step.
PRD ref: `prd.md > Weekly summary and recommendations`.

### Recommendation graph
Nodes: gather aggregates, budgets and goals → Flash Lite writes recommendations for insights, budgets and goals → store and format for Telegram. Used for the weekly summary and on-demand questions.
PRD ref: `prd.md > Weekly summary and recommendations`.

### Analytics service
Async SQL aggregations for day, week, month, quarter and year: totals, category breakdown, budget remaining. Source of truth for every number the UI and the LLM show.
PRD ref: `prd.md > Web app: transactions and analytics`.

### Nudge scheduler
APScheduler async jobs: nudges at the stored slot times and the weekly summary on Monday. Slot learning: with fewer than 20 confirmed transactions, use the six default slots (breakfast, mid-morning, lunch, afternoon, dinner, evening). Otherwise, group the time-of-day of past uploads into six clusters and use their centers. Ignored nudges are not followed up. Learning clusters the local time of confirmation with a deterministic one-dimensional k-means, treating the day as starting at 04:00 so late-night uploads group together; if fewer than six distinct clusters emerge, the rest are filled from the default times, skipping any within an hour of a learned slot. Slots are recomputed at startup and daily at 04:00, and `/demo_nudge` sends one on demand.
PRD ref: `prd.md > Adaptive nudges`.

### REST API
Async FastAPI routers for transactions (including `GET /transactions` with receipt/confirmation date, month, amount and category filters), banks and cards, budgets, goals, analytics and summaries. Every route except `/health` and `/auth/*` requires a session cookie; see Components > Sign-in.
PRD ref: `prd.md > Screens and Layout`.

### Sign-in
A Telegram magic link with JWTs (PyJWT, HS256, signed with `AUTH_SECRET`). `/login` and every "Saved" reply send a login JWT (10 minutes, single use: its `jti` is stored in `login_tokens` and consumed atomically). The web `/auth` page exchanges it with `POST /auth/exchange` (a POST, so link-preview bots cannot spend it) for a session JWT (7 days) in an HttpOnly, SameSite=Lax cookie. Every other route checks that cookie. Telegram link previews are disabled on these messages and the token is removed from the address bar on arrival. When a link is used, the bot sends a short notice ("Signed in to the web app on … Not you? Send /signout."). `/signout` stores a "sessions valid after" time in the single-row `auth_state` table and marks every unused link as used; any session token issued at or before that second is rejected.
PRD ref: `prd.md > The Core Journey` (step 6)

### Web app
React pages: Today's transactions (landing), Dashboard, Budgets, Goals, and a banks/cards settings page. TanStack Query refetches every few seconds.
PRD ref: `prd.md > Screens and Layout`, `prd.md > Budgets`, `prd.md > Goals`.

## Data Model

All tables live in Postgres and persist across restarts. LangGraph's checkpointer adds its own tables for paused graph state.

- **banks**(id, name)
- **cards**(id, bank_id, name, last4)
- **categories**(id, name) — seeded at startup from `config/categories.json` (path in `CATEGORIES_FILE`); startup only adds missing names and never deletes.
- **uploads**(id, telegram_message_id, kind, filename, status: processing | needs_input | awaiting_confirmation | done | failed, created_at)
- **transactions**(id, upload_id, card_id, merchant, amount, occurred_on, category_id, description, status: pending | confirmed, created_at, confirmed_at) — only `confirmed` rows count in analytics.
- **budget_versions**(id, category_id, month, amount, version, created_at) — the current budget is the highest version for a category and month; older versions remain viewable.
- **goals**(id, name, target_amount, target_date, saved_amount) — progress is `saved_amount / target_amount`, with `saved_amount` edited in the web app (assumption, see Open Issues).
- **nudge_slots**(id, time_of_day, source: default | learned)
- **weekly_summaries**(id, week_start, stats_json, recommendations_text, created_at)
- **login_tokens**(jti, expires_at, used_at, created_at) — one row per issued sign-in link.
- **auth_state**(id = 1, sessions_valid_after) — a single row, set by `/signout`.

Nudge learning uses the upload/confirmation time, not the receipt date, because receipts often have no time of day.

## File Structure

```
pfa/
├── pyproject.toml
├── docker-compose.yml          # Postgres
├── .env.example                # env file for dev and testing
├── alembic.ini
├── src/
│   └── pfa/
│       ├── __init__.py
│       ├── main.py             # FastAPI app; lifespan starts bot polling + scheduler + checkpointer
│       ├── core/
│       │   ├── config.py       # settings from env
│       │   ├── loggers.py      # loguru; LOG_LEVEL, LOG_USE_BASIC_FORMAT
│       │   └── exceptions.py
│       ├── models/             # SQLAlchemy models
│       ├── schemas/            # pydantic request/response models
│       ├── repository/         # one async repository per aggregate (transactions, budgets, ...)
│       ├── services/
│       │   ├── analytics.py
│       │   ├── nudges.py       # slot learning + scheduler jobs
│       │   ├── uploads.py      # upload bookkeeping
│       │   └── images.py       # in-memory hand-off of receipt images (never on disk)
│       ├── graphs/             # LangGraph orchestration for every LLM call
│       │   ├── extraction.py
│       │   ├── chat.py
│       │   ├── recommendations.py
│       │   └── llm.py          # Gemini model factories (chat vs extract)
│       ├── bot/                # Telegram handlers and message formatting
│       ├── api/                # FastAPI routers
│       └── migrations/         # Alembic versions (async env)
├── tests/
│   ├── conftest.py
│   └── ...                     # async unit tests per service and graph; BDD scenarios for key flows
├── web/                        # Vite + React + TypeScript
│   ├── package.json
│   └── src/
│       ├── pages/              # Today, Dashboard, Budgets, Goals, Settings
│       ├── components/
│       ├── api/                # async fetch + TanStack Query hooks
│       └── theme.css           # CSS variables for the theme
└── devpost/                    # Devpost learning workspace
```

## External Services and Dependencies

- **Gemini API** — docs: https://ai.google.dev/gemini-api/docs. Needs `GEMINI_API_KEY`. Flash Lite for chat and recommendations; Pro for extraction with structured (JSON schema) output, called through LangGraph nodes. Rate limits and pricing: check current docs at the start of the build.
- **Telegram Bot API** — docs: https://core.telegram.org/bots/api. Needs a token from BotFather. Free. File downloads go through `getFile`.
- **PostgreSQL** — local Docker container; no cost.
- **LangGraph** — open-source library, no account needed.
- **LangSmith** — observability for every LangGraph and Gemini call. Needs `LANGSMITH_API_KEY`; free tier is enough. Off by default (`LANGSMITH_TRACING=false`) because traces contain messages and extracted receipt data. Receipt images are always redacted from the uploaded copy of a trace (`core/tracing.py`, a LangSmith client `anonymizer`); the request sent to Gemini is never altered. Added by the learner during slice 1; docs: https://docs.smith.langchain.com/.
- No hosting, email or payment services.

## Important Failure Modes

- **Extraction fails or the file is blurry** → the bot returns what it could read and asks you to enter the missing fields; if the whole graph run fails, the upload is marked `failed` and you get a short "couldn't process, please resend".
- **Gemini rate limit or timeout** → one retry inside the graph node, then the failure message above. Chat replies a short "busy, try again".
- **Bot restarts while an image is being read** → receipt images exist only in memory, so that upload is marked `failed` and you are asked to resend it. Nothing is recovered from disk because nothing is stored there.
- **Bot process stops** → nudges and summaries stop, and paused confirmations resume after restart because they live in the Postgres checkpointer. In-process scheduling is the accepted cost; the `/demo_*` commands are the demo fallback.

## What Was Simplified and Why

- **One user, identified by a configured Telegram chat id**, instead of accounts — the PoC is for one person. The learner required sign-in, so the web app is protected by a Telegram magic link instead of passwords (see Components > Sign-in).
- **Polling refetch** instead of websockets — looks live, far simpler.
- **Bot polling** instead of webhooks — no public URL needed.
- **In-process scheduler** instead of a job queue — fewer moving parts.
- **Manual `saved_amount` on goals** instead of linking goals to transactions — keeps goals independent of the extraction pipeline.
- **Local-only run** instead of deployment — video and repo are the submission.
- **Portfolios, WhatsApp, email digest** are out of this build, as agreed in `prd.md > Deferred From the POC`.

## Decisions and Open Issues

Learner decisions:
- FastAPI backend with a JS frontend; Postgres; Telegram polling.
- Vite + React + TypeScript with Recharts; accepted as recommended.
- APScheduler with manual demo triggers; accepted as recommended.
- UI refetch every few seconds instead of live push.
- All LLM calls orchestrated with LangGraph.
- Backend and frontend use async wherever possible.
- Banks and cards are set up in the web app only.
- A statement is confirmed in one go, with a summary of count, highest, lowest and total amount.

Derived implementation details (not separate learner decisions): single-user and no-auth, table shapes, the nudge clustering rule (20-transaction threshold, six clusters), using the LangGraph Postgres checkpointer for the confirmation pause, `python-telegram-bot`, SQLAlchemy async with `asyncpg`, Alembic, TanStack Query, and `pytest-asyncio`.

Learner uncertainty: none identified.

Open issues:
- **Assumption:** goal progress is a manually edited saved amount. Confirm in review.
- **Assumption:** ignoring a nudge counts as no data, not a recorded zero (from `prd.md > Open Questions`).
- **Can wait:** exact accent color and font; where quarterly and yearly insights sit on the dashboard (assumed Dashboard).
- **Check early in the build:** Gemini model IDs, API rate limits, the LangGraph interrupt/checkpointer behavior, and extraction quality on a real receipt and a real statement.
