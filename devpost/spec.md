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
5. **The reply includes a link** to `http://localhost:5173/dashboard` (a sign-in link opens the dashboard unless it names another page). The Transactions page loads today's confirmed transactions from the API and refetches every few seconds (`prd.md > Web app: transactions and analytics`).
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
- Money in and money out are told apart by several cues at once, so none has to be noticed on its own: an arrow and the words "Money in" or "Money out" in a filled badge, a + or − sign on the amount, a coloured stripe on the row's left edge, a light green tint on money-in rows, and green versus red amounts. Every text colour on its background is at least 4.5:1.

## Components

### Telegram bot
Receives messages and files by async polling; sends acknowledgements, threaded replies, confirmation buttons, nudges and summaries. Only responds to the configured chat id. Commands: `/login`, `/signout`, `/demo_summary`, `/demo_nudge`. Uploads start the extraction graph as a background task; casual messages start the chat graph.
PRD ref: `prd.md > Upload and extraction`, `prd.md > Confirmation and data fields`.

### Extraction graph
LangGraph graph with nodes: detect type → parse → extract (Gemini Pro, structured output) → infer card → validate required fields → request missing input / await confirmation (interrupt) → commit. Unreadable fields stay `null`. Statement summary (count, highest, lowest, total) is computed in code, not by the model. Receipt images are held in memory only: they go from Telegram to the model and are discarded when extraction ends, and they are never stored in graph state, so the Postgres checkpointer never holds them.
PRD ref: `prd.md > Upload and extraction`, `prd.md > Confirmation and data fields`.

Statements take a second branch of the same graph: `extract_statement` (PDF straight to Gemini Pro; CSV and Excel parsed in Python, then sent as text in batches of 100 rows) -> `review_statement` (interrupt) -> `commit_statement`. The summary (count, total, highest, lowest) is computed in code. Money in and money out are both saved, each with its direction (the model classifies every line, and is told the user's registered cards so it can recognise moves between their own accounts; those get the `Transfer` category and the `is_transfer` flag when the lines are created, and are summarised on their own line, outside money in, money out and the net); unreadable lines are left out and counted, and lines matching an already-confirmed transaction on the same card and in the same direction are skipped. The summary is computed in code for money out and money in apart, plus the net. Files are held in memory only (`FileStash`) and never enter graph state or disk.

### Chat graph
Flash Lite routes a message (structured output: `kind` casual or insights, plus `period`, `offset` and an optional `category`; a routing failure counts as casual) to a casual reply or an insights answer. An insights answer is computed by `gather_facts` from the analytics and budget services, rendered as plain lines, and written up by the model from those lines alone; the sentences are used only if every figure in them appears in the facts (`numbers_grounded`). The reply is those sentences followed by `render_stats`, the figures laid out one per line by code (a category question leads with that category and its budget and leaves out the long lists; goals, budgets and top categories are capped to fit one Telegram message). If the model fails or strays, a plain introduction and the same figures are sent. The model never queries the database freely. A correction message during confirmation is routed to the extraction graph's resume step.
PRD ref: `prd.md > Weekly summary and recommendations`.

### Recommendation graph
Nodes: `gather` (the week's facts from SQL via the analytics and budget services, goals, and the budgets worth flagging) → `write` (Flash Lite writes 3 to 5 lines of advice from the rendered facts; the reply is checked and replaced by a template, `fallback_recommendations`, if the model fails, returns nothing, or quotes a figure that is not in the facts) → `store` (one `weekly_summaries` row per week, replaced if the week is written again). `SummaryService` picks the week (the last full Monday to Sunday), the Monday job skips a finished week that already exists, and `/demo_summary` always writes a fresh one, falling back to the current week so far (marked partial, replaced by the real Monday summary later) when the last week is empty. The Telegram message and the dashboard panel both read the stored facts. Budgets reported are the month of the run date, so the advice looks ahead at what is left.
PRD ref: `prd.md > Weekly summary and recommendations`.

### Analytics service
Async SQL aggregations for day, week, month, quarter and year: totals, category breakdown, budget remaining. Money out and money in are always aggregated separately; budgets and "spent" figures use money out only. Movements between the user's own cards, accounts or pockets (transactions with `is_transfer` set) are excluded from both spending and income, and stay listed and filterable; the statement prompt limits `Transfer` to such internal moves, so money sent to another person counts as spending. Source of truth for every number the UI and the LLM show.
`GET /analytics?period=day|week|month|quarter|year&date=YYYY-MM-DD` returns one period (the one containing `date`, today by default) with the previous period for comparison. Periods are by the receipt date (`occurred_on`); weeks run Monday to Sunday and quarters are calendar quarters. The chart series is cut into days (week, month), weeks (quarter) or months (year), with empty buckets filled with zeros. A percentage change from nothing is `None` by default (see `percent_change`).
PRD ref: `prd.md > Web app: transactions and analytics`.

### Nudge scheduler
APScheduler async jobs: nudges at the stored slot times and the weekly summary on Monday at `SUMMARY_HOUR` (default 8, in the configured timezone). Like the nudges, the jobs live in this process's memory, so a summary is only sent if the app is running on Monday morning (accepted tradeoff; `/demo_summary` writes one any time). `GET /summary` returns the latest saved summary for the dashboard. Slot learning: with fewer than 20 confirmed transactions, use the six default slots (breakfast, mid-morning, lunch, afternoon, dinner, evening). Otherwise, group the time-of-day of past uploads into six clusters and use their centers. Ignored nudges are not followed up. Learning clusters the local time of confirmation with a deterministic one-dimensional k-means, treating the day as starting at 04:00 so late-night uploads group together; if fewer than six distinct clusters emerge, the rest are filled from the default times, skipping any within an hour of a learned slot. Slots are recomputed at startup and daily at 04:00, and `/demo_nudge` sends one on demand.
PRD ref: `prd.md > Adaptive nudges`.

### REST API
Async FastAPI routers for transactions (including `GET /transactions` with receipt/confirmation date, month, amount, category, direction and `is_transfer` filters (true lists only moves between the user's own accounts, false only what is counted), and `PATCH /transactions` to change the category, the direction, the transfer flag, or any mix, of one or many saved transactions, all or nothing), banks and cards, budgets, goals, analytics and summaries. Every transaction has a stored `is_transfer` flag (migration 0007 set it for existing `Transfer` rows), independent of its category, which is the single rule for "not counted as spending or income". `PATCH /transactions` accepts `category`, `direction` and `is_transfer`, alone or together; flagging never changes the category. Budgets and goals: `GET /budgets?month=YYYY-MM` (every budget that applies, with spent, remaining and totals), `PUT /budgets` (`category`, `month`, `amount`; always adds a version), `GET /budgets/history?category=&month=` (newest first), `POST /budgets/copy` (`from_month`, `to_month`; copies each current budget of the source month as version 1 of the target and skips any category that already has one there, under the same lock as saving, so simultaneous copies create each budget once; answers `{copied, skipped}`), `GET/POST /goals`, `PATCH/DELETE /goals/{id}`. `GET /analytics` also carries the month's budgets when `period=month`. Which month's budget applies to a month with none of its own is one pure function, `applicable_month`. Every route except `/health` and `/auth/*` requires a session cookie; see Components > Sign-in.
PRD ref: `prd.md > Screens and Layout`.

### Sign-in
A Telegram magic link with JWTs (PyJWT, HS256, signed with `AUTH_SECRET`). `/login` and every "Saved" reply send a login JWT (10 minutes, single use: its `jti` is stored in `login_tokens` and consumed atomically). The web `/auth` page exchanges it with `POST /auth/exchange` (a POST, so link-preview bots cannot spend it) for a session JWT (7 days) in an HttpOnly, SameSite=Lax cookie. Every other route checks that cookie. Telegram link previews are disabled on these messages and the token is removed from the address bar on arrival. When a link is used, the bot sends a short notice ("Signed in to the web app on … Not you? Send /signout."). `/signout` stores a "sessions valid after" time in the single-row `auth_state` table and marks every unused link as used; any session token issued at or before that second is rejected.
PRD ref: `prd.md > The Core Journey` (step 6)

### Web app
React pages: Dashboard (landing, first in the menu), Today's transactions, Budgets (one month at a time: budget, spent, what is left in words and a bar, an inline edit and a list of saved versions), Goals (progress bars, inline edit, delete), and a banks/cards settings page. TanStack Query refetches every few seconds. On the Transactions page the filter toolbar is sticky at the top (a summary of the active filters, with the controls opening in place and scrolling inside themselves if tall), and the bar for ticked rows plus its confirmation message are fixed at the bottom of the screen, with extra space below the list so they never hide the last rows. Figures scale to fit their cards. The Dashboard page draws its chart with Recharts and is loaded on demand, so the other pages do not carry the chart library; it can also be read as a table.
PRD ref: `prd.md > Screens and Layout`, `prd.md > Budgets`, `prd.md > Goals`.

## Data Model

All tables live in Postgres and persist across restarts. LangGraph's checkpointer adds its own tables for paused graph state.

- **banks**(id, name)
- **cards**(id, bank_id, name, last4)
- **categories**(id, name) — seeded at startup from `config/categories.json` (path in `CATEGORIES_FILE`); startup only adds missing names and never deletes.
- **uploads**(id, telegram_message_id, kind, filename, status: processing | needs_input | awaiting_confirmation | done | failed, created_at)
- **transactions**(id, upload_id, card_id, merchant, amount, occurred_on, category_id, description, direction: out | in, status: pending | confirmed, created_at, confirmed_at) — only `confirmed` rows count in analytics. `amount` is always positive; `direction` says whether the money went out (an expense, the default) or came in. A database check allows only those two values.
- **budget_versions**(id, category_id, month, amount, version, created_at) — `month` is the first day of the month; unique on (category, month, version); amount above zero. The current budget is the highest version for a category and month; older versions are never changed or deleted. Saving takes a Postgres advisory lock on the category and month until the commit, so simultaneous edits get consecutive versions.
- **goals**(id, name, target_amount, target_date, saved_amount, created_at) — target above zero, saved not negative; progress is `saved_amount / target_amount`, with `saved_amount` edited in the web app (assumption, see Open Issues).
- **nudge_slots**(id, time_of_day, source: default | learned)
- **weekly_summaries**(id, week_start unique, stats_json, recommendations_text, created_at) — `stats_json` holds the computed facts and who wrote the advice (`model` or `fallback`); `recommendations_text` is one line per piece of advice.
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
│       │   └── exceptions.py   # every domain exception (LLMError, StatementError, AuthError)
│       ├── models/             # SQLAlchemy tables
│       ├── schemas/            # pydantic models: request/response shapes and domain value objects (statements.py, nudges.py, auth.py)
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
- **LangSmith** — observability for every LangGraph and Gemini call. Statement and receipt contents are masked in uploaded traces (images, PDFs, CSV and Excel rows, the transactions a model read, and card hints), while run structure, timings and errors stay visible; extracted receipt fields are not masked. Needs `LANGSMITH_API_KEY`; free tier is enough. Off by default (`LANGSMITH_TRACING=false`) because traces contain messages and extracted receipt data. Receipt images are always redacted from the uploaded copy of a trace (`core/tracing.py`, a LangSmith client `anonymizer`); the request sent to Gemini is never altered. Added by the learner during slice 1; docs: https://docs.smith.langchain.com/.
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
