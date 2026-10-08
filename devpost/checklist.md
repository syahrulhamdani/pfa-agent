---
doc: checklist
status: approved
---

# Build Checklist

Build mode: learn for slice 1; learner chooses the mode again before each later slice (until they say otherwise)

## Slices

- [x] **1. You message pfa on Telegram and it answers like a person**
  Becomes usable: A running pfa process that replies to your Telegram messages using Gemini Flash Lite, only for your chat id. Also proves the three risky pieces early: Gemini model IDs, a LangGraph graph, and Telegram polling inside the FastAPI lifespan.
  Why now: These are the unverified items in the spec and everything else hangs off the bot loop, so bad news should arrive first. Project bootstrapping lives here: `pyproject.toml`, `.env.example`, `core/` config and loggers, Postgres in Docker Compose, FastAPI app.
  PRD ref: `prd.md > The Core Journey` (steps 1, 3), `prd.md > Look and Feel` (Telegram tone)
  Spec ref: `spec.md > Stack`, `spec.md > Where It Runs and How Someone Tries It`, `spec.md > Components` (Telegram bot, Chat graph), `spec.md > File Structure`
  Build: Scaffold the package per the spec file structure with `uv`, add `core/config.py`, `core/loggers.py`, `core/exceptions.py`, `docker-compose.yml` (Postgres), a `/health` endpoint, the Gemini model factory in `graphs/llm.py`, a casual-reply chat graph, and the Telegram bot started from the lifespan with a chat-id guard. Pytest with `conftest.py` covers config loading, the chat-id guard and the graph with a fake model.
  Verify (mechanical): `uv run pytest` passes; `docker compose up -d db` is healthy; start uvicorn with `.env.example` values and confirm `GET /health` returns 200 and logs show polling started; one live round trip of the chat graph against Gemini returns text.
  Learner check: Put your bot token, chat id and Gemini key in your local env, start the app, message the bot "hi, what can you do?" and tell me whether the reply feels human and professional.
  Commit: `Add scaffold, Telegram polling and Flash Lite chat`

- [x] **2. You send a receipt and confirm it into the database**
  Becomes usable: Upload a receipt photo in Telegram, get an immediate "processing" reply, keep chatting, then receive a reply threaded to your upload with merchant, amount, date, category, card and description. Tap Confirm and the transaction is saved.
  Why now: This is the core of the loop and the biggest technical risk (Gemini Pro structured extraction, LangGraph interrupt with the Postgres checkpointer). Nothing in analytics, nudges or the web app exists without confirmed data.
  PRD ref: `prd.md > Upload and extraction`, `prd.md > Confirmation and data fields`, `prd.md > States and Boundaries` (processing, blurry, missing card, unconfirmed)
  Spec ref: `spec.md > Components` (Extraction graph, Telegram bot), `spec.md > Data Model` (banks, cards, categories, uploads, transactions), `spec.md > Important Failure Modes`
  Build: Alembic async migration and seeded categories; models, schemas and repositories for banks, cards, uploads and transactions; minimal REST endpoints to create a bank and card (the web page arrives in slice 3); extraction graph for images (detect type, extract with Gemini Pro, infer card, validate required fields, interrupt for confirmation, commit); background-task start so chat stays usable; threaded reply with Confirm button, card buttons when the card is missing, null fields listed for manual entry; typed corrections parsed by Flash Lite; failure and retry handling as in the spec.
  Verify (mechanical): `uv run pytest` passes with a fake extraction model covering confirm, correction, missing card, unreadable field and failure; `alembic upgrade head` runs clean; a real sample receipt through Gemini Pro produces a `pending` row that becomes `confirmed` only after the confirm callback; restart the app mid-confirmation and confirm the pause resumes from the checkpointer.
  Learner check: Create a bank and a card with the API (I'll give the one-line command), send one of your real receipts in Telegram, send a casual message while it processes, then confirm and tell me whether the extracted fields are right.
  Commit: `Add receipt extraction and confirmation flow`

- [x] **3. The Telegram link opens Today's transactions in the web app**
  Becomes usable: The confirmation reply ends with a link; it opens a Deloitte-style web page listing today's confirmed transactions, refreshed every few seconds, with navigation stubs and a banks/cards settings page where you add banks and cards.
  Why now: First time the receipt becomes visible analytics, which is the "oh that's cool" beat, and the first moment look-and-feel feedback can shape the rest of the web work.
  PRD ref: `prd.md > Web app: transactions and analytics`, `prd.md > Screens and Layout`, `prd.md > Look and Feel`
  Spec ref: `spec.md > Components` (REST API, Web app), `spec.md > Look and Feel`, `spec.md > File Structure` (`web/`)
  Build: Scaffold `web/` (Vite, React, TypeScript, TanStack Query), `theme.css` with CSS variables, confirm the accent color and font from the reference page, layout with navigation, Today page, Settings page for banks and cards, `GET /transactions/today` and bank/card CRUD routers, link appended to the bot's confirmation reply, empty states.
  Verify (mechanical): `uv run pytest` for the new routers; `npm run build` and typecheck pass; start API and web, fetch today's transactions through the dev server and confirm the confirmed row from slice 2 appears and a pending one does not.
  Learner check: Confirm a receipt in Telegram, click the link, and check that it shows up within a few seconds. Say what you would change about the look.
  Commit: `Add web app with Today's transactions and bank/card settings`

- [x] **4. You sign in to the web app with a Telegram link**
  Becomes usable: The API and every web page require a session. pfa's "Saved" reply and a new `/login` command send a short-lived, single-use link; opening it sets a 7-day session cookie and lands on Transactions. Without a session the web app explains how to get a link.
  Why now: You required auth before more financial data and pages (dashboard, budgets, goals) are built on an open API, and every later slice depends on the protected routes.
  PRD ref: `prd.md > The Core Journey` (step 6)
  Spec ref: `spec.md > Components` (REST API, Telegram bot, Web app), `spec.md > What Was Simplified and Why` (no login)
  Build: Add PyJWT and an `AUTH_SECRET` setting; a `login_tokens` table so each link works once; a login JWT (10 minutes, single use) and a session JWT (7 days) in an HttpOnly cookie; `POST /auth/exchange`, `GET /auth/me` and `POST /auth/logout`; a session check on every route except `/health` and `/auth`; Telegram link generation for the "Saved" reply and `/login`, with link previews off; a web `/auth` page that exchanges the token, a sign-in-required screen and a sign-out button.
  Verify (mechanical): `uv run pytest` covers token creation, expiry, tampering, wrong token type, single use, cookie flags, and 401 without a session on every protected route; `npm run build` and lint pass; a live run through the Vite proxy confirms the exchange sets the cookie, protected calls succeed with it and fail without it, and a reused link is rejected.
  Learner check: Send `/login` in Telegram, open the link, confirm Transactions loads, then open the same link again and confirm it is rejected; sign out and confirm the pages ask you to get a new link.
  Commit: `Add Telegram magic-link sign-in with JWT sessions`

- [x] **5. pfa nudges you at the times you usually spend (the unique kernel)**
  Becomes usable: pfa sends upload nudges at six default daily slots, learns slots from your past confirmed transactions once there are enough, and `/demo_nudge` fires one on demand. Ignored nudges get no follow-up.
  Why now: The nudge is one half of the unique kernel and only needs confirmed transactions, so it goes in right after the data exists instead of last.
  PRD ref: `prd.md > Adaptive nudges`, `prd.md > States and Boundaries` (ignored nudge, demo triggering)
  Spec ref: `spec.md > Components` (Nudge scheduler), `spec.md > Data Model` (`nudge_slots`)
  Build: `nudge_slots` migration and repository, default slot seeding, `services/nudges.py` with slot learning (fewer than 20 confirmed transactions uses defaults, otherwise six clusters of upload/confirmation time), APScheduler `AsyncIOScheduler` jobs registered from the lifespan, `/demo_nudge` command.
  Verify (mechanical): `uv run pytest` covers default slots, the 20-transaction threshold, clustering into six slots on seeded timestamps, and that a job sends exactly one message and no follow-up; `/demo_nudge` triggers a real Telegram message in a live run.
  Learner check: Send `/demo_nudge` and read the message. Say whether the wording fits you, and whether the six default times match your day.
  Commit: `Add adaptive nudge slots and scheduler`

- [x] **6. You can upload a statement (PDF, CSV or Excel) and confirm it in one go**
  Becomes usable: Upload a statement file, get a summary (count, highest, lowest, total), and confirm every transaction with one tap.
  Why now: Same graph as receipts with a new parse branch, so the riskiest wiring is already proven. It adds real volume for analytics before we build them.
  PRD ref: `prd.md > Upload and extraction`, `prd.md > Confirmation and data fields`
  Spec ref: `spec.md > Components` (Extraction graph), `spec.md > Stack` (File parsing)
  Build: Add file-type detection and parse branches: CSV and Excel read in Python via `asyncio.to_thread`, PDF sent to Gemini; code-computed statement summary; batch confirm; handling for columns that don't map.
  Verify (mechanical): `uv run pytest` with small CSV, Excel and PDF fixtures; confirm the summary numbers match a hand count; confirm one tap flips all `pending` rows to `confirmed`.
  Learner check: Upload one real statement you're comfortable using, check the summary against your statement, confirm, and look at the Today page.
  Commit: `Add statement upload and batch confirmation`

- [ ] **7. You can explore aggregated spending on the dashboard**
  Becomes usable: A Dashboard page with day, week, month, quarter and year views, category breakdown and totals, updating as confirmed data arrives.
  Why now: Analytics is the source of truth for the web app and for every number the LLM will quote, so it must exist before budgets and recommendations.
  PRD ref: `prd.md > Web app: transactions and analytics`
  Spec ref: `spec.md > Components` (Analytics service, REST API, Web app), `spec.md > Look and Feel` (restrained charts)
  Build: Async SQL aggregations in `services/analytics.py`, analytics router, Dashboard page with Recharts, empty states.
  Verify (mechanical): `uv run pytest` seeds transactions across days, weeks, quarters and years and asserts totals and category breakdowns; web build and typecheck pass; fetch a dashboard payload and compare against a SQL total.
  Learner check: Open the Dashboard, switch periods, and check the numbers against what you've confirmed.
  Commit: `Add analytics service and dashboard`

- [ ] **8. You can set versioned monthly budgets and savings goals**
  Becomes usable: Budgets page (per category, per month, editable, older versions viewable) and Goals page (name, target amount, target date, manually edited saved amount, progress), with budget remaining shown on the dashboard.
  Why now: Recommendations compare spending against budgets and goals, so these must exist before the second half of the kernel.
  PRD ref: `prd.md > Budgets`, `prd.md > Goals`
  Spec ref: `spec.md > Data Model` (`budget_versions`, `goals`), `spec.md > Components` (REST API, Web app, Analytics service)
  Build: Migration, repositories, routers and pages for budget versions and goals; budget remaining added to analytics.
  Verify (mechanical): `uv run pytest` asserts an edit creates a new version, the current budget is the highest version and older versions remain; goal progress is `saved_amount / target_amount`; web build and typecheck pass.
  Learner check: Create a budget, edit it, and view the older version; create a goal and update its saved amount.
  Commit: `Add versioned budgets and goals`

- [ ] **9. pfa speaks up on its own: Monday summary and recommendations (the unique kernel)**
  Becomes usable: `/demo_summary` (and the Monday job) sends a short summary with a dashboard link; the dashboard shows last week's stats, category breakdown and recommendations against remaining budget; asking pfa in chat for insights answers from your confirmed data.
  Why now: Last by dependency, since it uses analytics, budgets and goals, but it completes the kernel and the demo's closing beat.
  PRD ref: `prd.md > Weekly summary and recommendations`, `prd.md > States and Boundaries` (demo triggering)
  Spec ref: `spec.md > Components` (Recommendation graph, Chat graph, Analytics service, Nudge scheduler), `spec.md > Data Model` (`weekly_summaries`)
  Build: `weekly_summaries` migration and repository, recommendation graph (gather aggregates, budgets, goals; Flash Lite writes recommendations; store and format), Monday job and `/demo_summary`, chat graph routing for insights and recommendation questions through the analytics service, summary section on the Dashboard.
  Verify (mechanical): `uv run pytest` with a fake model asserting that recommendations only draw on provided numbers and the summary is stored once per week; a live `/demo_summary` produces a Telegram message and a saved row that the dashboard API returns; a chat question returns an answer with figures matching analytics.
  Learner check: Send `/demo_summary`, open the link, then ask pfa "how am I doing on food this month?" and judge whether the advice reflects your data.
  Commit: `Add weekly summary, recommendations and chat insights`

## Hands-on Checkpoints

- [x] Early usable behavior explored — after slice 3 (receipt to Today's transactions); the learner approved the look and asked for filters and auth, which became revisions
- [ ] Final kick-the-tires exploration and feedback completed

## Final Review

- [ ] Final review complete — feedback resolved and learner confirms ready to ship

## Code Tour and App Map

- [ ] Learning activity complete — guided route, focused alternative, prior practice connected, or brief recap
- [ ] Optional edit and transfer reflection addressed — offered/declined/already covered/not applicable as appropriate
- [ ] `devpost/app-map.html` generated from finished code, checked, and shown, including a project-grounded practice to reuse

Activity and evidence: 
Route and stops: 
Edit outcome: 
Reflection: 
Activity mode: 

## Revisions

- Added LangSmith observability (env-driven tracing, off by default, named `chat` runs) — the learner asked for it after slice 1; the spec had listed LangSmith as not used. Later graphs should set a `run_name` and tags the same way.
- Chat history moved from in-memory to the LangGraph Postgres checkpointer, with the last 20 messages sent to Gemini — the learner saw the bot forget context across restarts, and slice 2's confirmation pause needs the same checkpointer anyway. The compose database now maps to host port 5433 because a local Postgres on the learner's Mac already owns 5432.
- Seeded categories come from `config/categories.json` and are added at startup, instead of being hard-coded in the first migration — the learner asked how to configure them; names are only ever added so existing transactions keep their category.
- Extraction and correction parsing use LangChain's built-in `with_structured_output` — the learner chose this over an agent-style `response_format`.
- The Telegram handlers are registered in `bot/app.py` and covered by `tests/test_bot_app.py` — a first edit left upload, button and error handlers unregistered, so photos were silently ignored.
- `missing_fields()` also treats an amount of zero or less and a date after today as missing — the learner's rule, fixed to handle empty values without crashing.
- "Today's transactions" means transactions confirmed today in the configured timezone, not receipts dated today — the PRD wants the just-confirmed transaction visible, and a receipt is often dated earlier.
- The accent colour and font could not be read from the reference page, so the theme uses Deloitte's published brand green and an Open Sans-first stack, held in CSS variables for the learner to retune at the checkpoint.
- The web app calls the API through a Vite `/api` proxy, so no CORS setup is needed in FastAPI.
- The landing page gained filters (receipt or confirmation date, range or month, amount range, categories) and became "Transactions" with "confirmed today" as the default — the learner asked for it at the early checkpoint. Auth is still undecided and would be added as its own step.
- Added slice 4, Telegram magic-link sign-in with JWT sessions, and renumbered the later slices — the learner requires authentication, which reverses the spec's "No login; one user identified by a configured Telegram chat id" simplification. Session length defaults to 7 days.
- Receipt images are no longer written to disk: they are downloaded into memory, passed to Gemini and discarded, and the `uploads.file_path` column was dropped — the learner asked for this for security. A restart during extraction now fails that upload and asks for a resend. Images are kept out of graph state so the Postgres checkpointer never stores them.
- The bot now tells the owner on Telegram when a sign-in link is used, so an unexpected sign-in is noticed.
- Added `/signout` (ends every web session and unused link) and a sign-in notice that points to it — the learner asked for an actionable response to an unexpected sign-in. Sessions carry their issue time and are rejected if issued before the stored revocation time.
- LangSmith traces now redact receipt images (base64 blocks, data URLs and raw bytes) before upload, through a global client anonymizer — the learner asked for it for privacy; the live Gemini request is untouched.
- Rejected requests now answer in plain words (which field, the expected format, an example), and the Transactions page checks month, date and amount formats itself before asking the server — some browsers show month and date pickers as plain text boxes, and the raw validation error was hidden behind "Unprocessable Entity".
- Nudge slots are re-learned daily at 04:00 as well as at startup, and the clustering day starts at 04:00 to handle times around midnight — details the spec left open; the learner chose the six default times.
- Statements leave out unreadable lines (counted, never guessed) and lines already confirmed on the same card in the same direction — the spec said only that a statement is confirmed in one go with a summary, and overlapping statements would otherwise double-count.
- `ImageStash` became `FileStash` because it now holds statements as well as receipt images; files still live in memory only.
- `parse_amount` now rejects NaN and infinity and rounds half up — a NaN amount passed validation and would have been saved.
- LangSmith masking now also covers PDF, CSV and Excel statement contents, the transactions the model read from them, and card hints — the learner asked that all statement formats be masked, and the first version only covered images.
- Domain value objects that had grown inside service modules (`Spend`, `ParsedRow`, `NormalizedRows`, `StatementSummary`, `Slot`, `SlotSource`, `TokenType`) moved to their own modules under `schemas/` as frozen pydantic models (they are not database tables, so not `models/`), and `StatementError` and `AuthError` moved to `core/exceptions.py` — the learner pointed out that they sat beside the logic instead of in the layout the project follows. Constructors now take keyword arguments; behaviour is otherwise unchanged.
- Every transaction now has a direction (money out or money in), and statements keep credits as money in instead of leaving them out; the summary, duplicate check, API, filters and web page all separate the two — the learner found after testing a statement that dropping income was a missing major feature. Existing transactions default to money out; income categories (Salary, Refund, Transfer, Interest) were added to the category list. Budgets and the dashboard will count money out only.
- The learner kept the strict duplicate rule (same direction, date, amount and merchant ignoring case) for statement lines.
- Transfers between the learner's own cards, accounts or pockets (category `Transfer`) will be excluded from spending and income on the dashboard, and the statement prompt now restricts that category to internal moves so payments to other people still count as spending — the learner decided this to avoid card payments counting twice.
- The category of a saved transaction can now be changed in the web app, singly or in bulk — the learner chose this over a rename-aware config list for category changes, and it is also how a misfiled transfer is corrected. Statement summaries list transfers between the user's own accounts apart from money in and out, the model is told the user's registered cards, and the Transactions page leaves transfers out of its totals; the list of categories itself is still edited in the configuration file.
