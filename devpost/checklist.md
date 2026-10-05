---
doc: checklist
status: approved
---

# Build Checklist

Build mode: learn for slice 1; learner chooses the mode again before each later slice (until they say otherwise)

## Slices

- [ ] **1. You message pfa on Telegram and it answers like a person**
  Becomes usable: A running pfa process that replies to your Telegram messages using Gemini Flash Lite, only for your chat id. Also proves the three risky pieces early: Gemini model IDs, a LangGraph graph, and Telegram polling inside the FastAPI lifespan.
  Why now: These are the unverified items in the spec and everything else hangs off the bot loop, so bad news should arrive first. Project bootstrapping lives here: `pyproject.toml`, `.env.example`, `core/` config and loggers, Postgres in Docker Compose, FastAPI app.
  PRD ref: `prd.md > The Core Journey` (steps 1, 3), `prd.md > Look and Feel` (Telegram tone)
  Spec ref: `spec.md > Stack`, `spec.md > Where It Runs and How Someone Tries It`, `spec.md > Components` (Telegram bot, Chat graph), `spec.md > File Structure`
  Build: Scaffold the package per the spec file structure with `uv`, add `core/config.py`, `core/loggers.py`, `core/exceptions.py`, `docker-compose.yml` (Postgres), a `/health` endpoint, the Gemini model factory in `graphs/llm.py`, a casual-reply chat graph, and the Telegram bot started from the lifespan with a chat-id guard. Pytest with `conftest.py` covers config loading, the chat-id guard and the graph with a fake model.
  Verify (mechanical): `uv run pytest` passes; `docker compose up -d db` is healthy; start uvicorn with `.env.example` values and confirm `GET /health` returns 200 and logs show polling started; one live round trip of the chat graph against Gemini returns text.
  Learner check: Put your bot token, chat id and Gemini key in your local env, start the app, message the bot "hi, what can you do?" and tell me whether the reply feels human and professional.
  Commit: `Add scaffold, Telegram polling and Flash Lite chat`

- [ ] **2. You send a receipt and confirm it into the database**
  Becomes usable: Upload a receipt photo in Telegram, get an immediate "processing" reply, keep chatting, then receive a reply threaded to your upload with merchant, amount, date, category, card and description. Tap Confirm and the transaction is saved.
  Why now: This is the core of the loop and the biggest technical risk (Gemini Pro structured extraction, LangGraph interrupt with the Postgres checkpointer). Nothing in analytics, nudges or the web app exists without confirmed data.
  PRD ref: `prd.md > Upload and extraction`, `prd.md > Confirmation and data fields`, `prd.md > States and Boundaries` (processing, blurry, missing card, unconfirmed)
  Spec ref: `spec.md > Components` (Extraction graph, Telegram bot), `spec.md > Data Model` (banks, cards, categories, uploads, transactions), `spec.md > Important Failure Modes`
  Build: Alembic async migration and seeded categories; models, schemas and repositories for banks, cards, uploads and transactions; minimal REST endpoints to create a bank and card (the web page arrives in slice 3); extraction graph for images (detect type, extract with Gemini Pro, infer card, validate required fields, interrupt for confirmation, commit); background-task start so chat stays usable; threaded reply with Confirm button, card buttons when the card is missing, null fields listed for manual entry; typed corrections parsed by Flash Lite; failure and retry handling as in the spec.
  Verify (mechanical): `uv run pytest` passes with a fake extraction model covering confirm, correction, missing card, unreadable field and failure; `alembic upgrade head` runs clean; a real sample receipt through Gemini Pro produces a `pending` row that becomes `confirmed` only after the confirm callback; restart the app mid-confirmation and confirm the pause resumes from the checkpointer.
  Learner check: Create a bank and a card with the API (I'll give the one-line command), send one of your real receipts in Telegram, send a casual message while it processes, then confirm and tell me whether the extracted fields are right.
  Commit: `Add receipt extraction and confirmation flow`

- [ ] **3. The Telegram link opens Today's transactions in the web app**
  Becomes usable: The confirmation reply ends with a link; it opens a Deloitte-style web page listing today's confirmed transactions, refreshed every few seconds, with navigation stubs and a banks/cards settings page where you add banks and cards.
  Why now: First time the receipt becomes visible analytics, which is the "oh that's cool" beat, and the first moment look-and-feel feedback can shape the rest of the web work.
  PRD ref: `prd.md > Web app: transactions and analytics`, `prd.md > Screens and Layout`, `prd.md > Look and Feel`
  Spec ref: `spec.md > Components` (REST API, Web app), `spec.md > Look and Feel`, `spec.md > File Structure` (`web/`)
  Build: Scaffold `web/` (Vite, React, TypeScript, TanStack Query), `theme.css` with CSS variables, confirm the accent color and font from the reference page, layout with navigation, Today page, Settings page for banks and cards, `GET /transactions/today` and bank/card CRUD routers, link appended to the bot's confirmation reply, empty states.
  Verify (mechanical): `uv run pytest` for the new routers; `npm run build` and typecheck pass; start API and web, fetch today's transactions through the dev server and confirm the confirmed row from slice 2 appears and a pending one does not.
  Learner check: Confirm a receipt in Telegram, click the link, and check that it shows up within a few seconds. Say what you would change about the look.
  Commit: `Add web app with Today's transactions and bank/card settings`

- [ ] **4. pfa nudges you at the times you usually spend (the unique kernel)**
  Becomes usable: pfa sends upload nudges at six default daily slots, learns slots from your past confirmed transactions once there are enough, and `/demo_nudge` fires one on demand. Ignored nudges get no follow-up.
  Why now: The nudge is one half of the unique kernel and only needs confirmed transactions, so it goes in right after the data exists instead of last.
  PRD ref: `prd.md > Adaptive nudges`, `prd.md > States and Boundaries` (ignored nudge, demo triggering)
  Spec ref: `spec.md > Components` (Nudge scheduler), `spec.md > Data Model` (`nudge_slots`)
  Build: `nudge_slots` migration and repository, default slot seeding, `services/nudges.py` with slot learning (fewer than 20 confirmed transactions uses defaults, otherwise six clusters of upload/confirmation time), APScheduler `AsyncIOScheduler` jobs registered from the lifespan, `/demo_nudge` command.
  Verify (mechanical): `uv run pytest` covers default slots, the 20-transaction threshold, clustering into six slots on seeded timestamps, and that a job sends exactly one message and no follow-up; `/demo_nudge` triggers a real Telegram message in a live run.
  Learner check: Send `/demo_nudge` and read the message. Say whether the wording fits you, and whether the six default times match your day.
  Commit: `Add adaptive nudge slots and scheduler`

- [ ] **5. You can upload a statement (PDF, CSV or Excel) and confirm it in one go**
  Becomes usable: Upload a statement file, get a summary (count, highest, lowest, total), and confirm every transaction with one tap.
  Why now: Same graph as receipts with a new parse branch, so the riskiest wiring is already proven. It adds real volume for analytics before we build them.
  PRD ref: `prd.md > Upload and extraction`, `prd.md > Confirmation and data fields`
  Spec ref: `spec.md > Components` (Extraction graph), `spec.md > Stack` (File parsing)
  Build: Add file-type detection and parse branches: CSV and Excel read in Python via `asyncio.to_thread`, PDF sent to Gemini; code-computed statement summary; batch confirm; handling for columns that don't map.
  Verify (mechanical): `uv run pytest` with small CSV, Excel and PDF fixtures; confirm the summary numbers match a hand count; confirm one tap flips all `pending` rows to `confirmed`.
  Learner check: Upload one real statement you're comfortable using, check the summary against your statement, confirm, and look at the Today page.
  Commit: `Add statement upload and batch confirmation`

- [ ] **6. You can explore aggregated spending on the dashboard**
  Becomes usable: A Dashboard page with day, week, month, quarter and year views, category breakdown and totals, updating as confirmed data arrives.
  Why now: Analytics is the source of truth for the web app and for every number the LLM will quote, so it must exist before budgets and recommendations.
  PRD ref: `prd.md > Web app: transactions and analytics`
  Spec ref: `spec.md > Components` (Analytics service, REST API, Web app), `spec.md > Look and Feel` (restrained charts)
  Build: Async SQL aggregations in `services/analytics.py`, analytics router, Dashboard page with Recharts, empty states.
  Verify (mechanical): `uv run pytest` seeds transactions across days, weeks, quarters and years and asserts totals and category breakdowns; web build and typecheck pass; fetch a dashboard payload and compare against a SQL total.
  Learner check: Open the Dashboard, switch periods, and check the numbers against what you've confirmed.
  Commit: `Add analytics service and dashboard`

- [ ] **7. You can set versioned monthly budgets and savings goals**
  Becomes usable: Budgets page (per category, per month, editable, older versions viewable) and Goals page (name, target amount, target date, manually edited saved amount, progress), with budget remaining shown on the dashboard.
  Why now: Recommendations compare spending against budgets and goals, so these must exist before the second half of the kernel.
  PRD ref: `prd.md > Budgets`, `prd.md > Goals`
  Spec ref: `spec.md > Data Model` (`budget_versions`, `goals`), `spec.md > Components` (REST API, Web app, Analytics service)
  Build: Migration, repositories, routers and pages for budget versions and goals; budget remaining added to analytics.
  Verify (mechanical): `uv run pytest` asserts an edit creates a new version, the current budget is the highest version and older versions remain; goal progress is `saved_amount / target_amount`; web build and typecheck pass.
  Learner check: Create a budget, edit it, and view the older version; create a goal and update its saved amount.
  Commit: `Add versioned budgets and goals`

- [ ] **8. pfa speaks up on its own: Monday summary and recommendations (the unique kernel)**
  Becomes usable: `/demo_summary` (and the Monday job) sends a short summary with a dashboard link; the dashboard shows last week's stats, category breakdown and recommendations against remaining budget; asking pfa in chat for insights answers from your confirmed data.
  Why now: Last by dependency, since it uses analytics, budgets and goals, but it completes the kernel and the demo's closing beat.
  PRD ref: `prd.md > Weekly summary and recommendations`, `prd.md > States and Boundaries` (demo triggering)
  Spec ref: `spec.md > Components` (Recommendation graph, Chat graph, Analytics service, Nudge scheduler), `spec.md > Data Model` (`weekly_summaries`)
  Build: `weekly_summaries` migration and repository, recommendation graph (gather aggregates, budgets, goals; Flash Lite writes recommendations; store and format), Monday job and `/demo_summary`, chat graph routing for insights and recommendation questions through the analytics service, summary section on the Dashboard.
  Verify (mechanical): `uv run pytest` with a fake model asserting that recommendations only draw on provided numbers and the summary is stored once per week; a live `/demo_summary` produces a Telegram message and a saved row that the dashboard API returns; a chat question returns an answer with figures matching analytics.
  Learner check: Send `/demo_summary`, open the link, then ask pfa "how am I doing on food this month?" and judge whether the advice reflects your data.
  Commit: `Add weekly summary, recommendations and chat insights`

## Hands-on Checkpoints

- [ ] Early usable behavior explored — after slice 3 (receipt to Today's transactions), so look-and-feel and extraction feedback can shape slices 4-8
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
