---
doc: prd
status: approved
---

# pfa — Product Requirements

pfa (personal finance assistant) is a Telegram-first agent plus a web app that turns uploaded receipts and statements into confirmed, aggregated data, then nudges, summarizes and recommends for one person managing their own money.
Source: `scope.md > The Unique Kernel`, `scope.md > The Core Loop`, `scope.md > What "Working" Looks Like`.

## The Core Journey

1. The user messages pfa on Telegram. There is no greeting or setup flow; they can upload a receipt right away.
2. The user uploads a receipt (image) or a statement (PDF, CSV, Excel). pfa immediately replies that it is processing.
3. While it processes, the user can keep chatting: upload more, or casually ask for recommendations and insights.
4. When processing finishes, pfa replies **to that specific upload message** with the extracted data and a request to confirm.
5. The user confirms (or corrects). Only confirmed data is saved and aggregated.
6. pfa's reply includes a single-use sign-in link to the web app, valid for a few minutes. Opening it signs the user in for a week and lands on the **Dashboard**, from which the user navigates everywhere else: aggregated data, budgets, goals, insights. Sending `/login` to pfa at any time returns a fresh link, and `/signout` ends every web session and invalidates unused links. pfa also messages the user when a link is used, so an unexpected sign-in is noticed. Without a session, the web app only shows how to get one.
7. In the web app the user explores aggregates and manages budgets and goals; changes show up in real time.
8. Between uploads, pfa nudges the user in daily time slots to upload receipts. The user uploads, or ignores the nudge.
9. At the start of each week, pfa sends a short Monday summary on Telegram with a link to the dashboard; the full summary is also in the web app.

Success: a receipt sent on Telegram appears confirmed and aggregated in the web app, and pfa then speaks up on its own with a summary, nudge and recommendations grounded in that data.

## Screens and Layout

Two surfaces, one product.

**Telegram chat** (primary interface): a single conversation with pfa. It handles uploads, confirmations, casual questions and every proactive message (nudges, Monday summary).

**Web app** (reached from links in Telegram), with navigation from the landing screen to:
- **Today's transactions** (second in the menu): the day's confirmed transactions by default, with money out, money in and the net shown apart. The list can be filtered by receipt date or confirmation date (range or month), amount range, categories, direction (money in, money out or both) and counting (everything, only moves between the user's own accounts, or only what is counted); clearing the filters returns to today.
- **Dashboard / analytics** (landing screen, first in the menu): aggregated data for past periods, category stats, the weekly summary, and quarterly and yearly insights. It can be viewed by day, week, month, quarter or year, stepping back and forward through time, and each view is compared with the one before it. It shows money out, money in, the net and the moves between the user's own accounts (not counted) apart, a chart of money out, money in, or both side by side over the period (money out is shown first and on its own by default, so a salary never flattens a month of spending), and where the money went and came from by category, each linking to the matching transactions. Periods go by the date on the receipt; weeks run Monday to Sunday and quarters are calendar quarters.
- **Budgets**: per-category monthly budgets, editable, with version history.
- **Goals**: savings goals with target amount and date.

Assumption: accounts and cards need a place to be managed (see Open Questions).

## Look and Feel

Direction chosen by the learner: use the theme of Deloitte's AI & Data page (`https://www.deloitte.com/global/en/services/consulting/services/artificial-intelligence-and-data.html`) as the web app's look. Observed from the page: white backgrounds, dark gray text, light gray dividers, one brand accent color, clean sans-serif type with hierarchy by size and weight, modular card layout, and a professional, authoritative tone.
Exact accent color and font were not extractable from the page; `4-spec` should confirm them from the site.
Telegram messages follow the same tone: concise, professional, no filler.

## Features and Behavior

### Upload and extraction
Source: `scope.md > The POC Boundary`.
- Accepts receipt images, and statements as PDF, CSV or Excel.
- Replies immediately that the upload will be processed; does not block the chat while it works.
- Replies to the original upload message with the result when done.
- Statements contain many transactions; each is extracted into the same fields.
- A statement is read in one go and confirmed with one tap. Before confirming, pfa shows how many transactions it found, their total, the highest and the lowest amount, and which card it belongs to (asking if it cannot tell).
- Every line is saved as money out (an expense) or money in (income, a refund, interest, a transfer in), and the summary shows both apart with the net between them. A line whose merchant, amount or date cannot be read is left out and counted, never guessed. A line that matches a transaction already confirmed on the same card (same direction, date, amount and merchant) is skipped, so uploading overlapping statements does not double-count.
- Limits: PDF, CSV or Excel (.xlsx, not the old .xls); up to 10 MB and 500 rows per spreadsheet.

- As the user, I want to send a receipt and keep chatting so that I never wait on the agent.
  - [ ] Sending a receipt gets an immediate "processing" reply.
  - [ ] While processing, a second upload or a casual question is answered normally.
  - [ ] The result arrives as a reply threaded to the original upload.
- As the user, I want unreadable parts handed back to me so that nothing is guessed.
  - [ ] For a blurry receipt, pfa returns what it could read and asks me to enter the unreadable fields manually.

### Confirmation and data fields
- Every extracted transaction requires user confirmation before it is saved.
- Required fields: merchant, amount, date, category, account/card. Every transaction also records its direction: money out (an expense, the default and always the case for receipts) or money in (income). Amounts are always positive.
- Optional field: description, prefilled by the agent from the content of the data.
- Account/card: used if it can be inferred from the receipt; otherwise pfa asks the user to provide it.

- As the user, I want to confirm or fix extracted data so that my records are correct.
  - [ ] The extraction reply shows merchant, amount, date, category, account/card and a prefilled description.
  - [ ] Nothing appears in the web app until I confirm.
  - [ ] After I confirm, the transaction shows in Today's transactions and in aggregates without a page-reload delay beyond refresh.
  - [ ] If account/card is missing, pfa asks me for it before saving.

### Web app: transactions and analytics
- Landing on the **Dashboard** from the Telegram link, with Today's transactions one click away.
- Aggregated data and category stats update in real time as confirmed data arrives.
- Quarterly and yearly insights available alongside weekly ones (Assumption: on the dashboard).
- Moves between the user's own cards, accounts or pockets are flagged as transfers (a flag of their own on each transaction, separate from the category, which is kept). They are shown but never counted as spending or income, so paying a card bill does not count twice. The "Between accounts" card on the transactions page and the dashboard says how many were left out and links to a list of exactly those, so they can be reviewed and corrected. Money sent to another person or a business is **not** a transfer and counts as spending. On a statement, pfa flags the lines it recognises as transfers and lists them on their own line before confirming so the user can check them.
- On a long list the user never has to scroll back up: the active filters stay pinned at the top as a slim summary whose "Filters" button opens the full controls in place, and the bar for changing ticked rows (with its confirmation message and "select all shown") stays at the bottom of the screen.
- The category and the direction (money in or money out) of any saved transaction can be changed in the web app by ticking one or more rows and using the bar that appears; with one row ticked, a button selects every row from the same merchant. A third control on the same bar, "Counting", flags the ticked rows as between the user's own accounts or counts them again; it never changes their category. Direction matters most for moves between the user's own pockets, where one side is money out and the other money in. The amount is never changed. The category list itself is still edited in the configuration file.

- As the user, I want to land on today's transactions from the link so that I can see what I just uploaded.
  - [ ] Clicking the link in pfa's reply opens the Dashboard, whose current-month figures include the just-confirmed transaction; Transactions, next in the menu, lists it.
  - [ ] I can navigate from there to dashboard, budgets and goals.

### Budgets
- A budget is per category, per month.
- It is a preset, can be edited, and is versioned (editing creates a new version; earlier versions are kept; the current budget is the latest version).
- The Budgets page shows one month at a time, stepping back and forward, with each category's budget, how much has been spent, what is left (or how far over) in words and a bar, and a link to every saved version. Money spent in categories without a budget is shown apart.
- "Spent" is money out in that month by receipt date. Money in never pays a budget back, and moves between the user's own accounts or pockets (the transfer flag) are not spending; money sent to a person or business is.
- The Dashboard shows what is left of this month's budgets when viewing a month.

- As the user, I want to set and edit monthly category budgets so that spending can be compared against them.
  - [ ] I can create a monthly budget for a category and edit it later.
  - [ ] After an edit, the previous version is still viewable.

### Goals
- A goal is a savings goal with a specific target date and target amount.

- As the user, I want to define savings goals so that pfa can recommend how to reach them.
  - [ ] I can create a goal with a name, target amount and target date.
  - [ ] I can see progress toward each goal.
  - [ ] I can update how much I have saved, edit or delete a goal.
- Progress is the saved amount against the target, which the user edits by hand; it can pass 100%, and the page says when a goal is reached or its date has gone.

### Adaptive nudges
Source: `scope.md > The Unique Kernel`.
- pfa nudges to upload receipts in daily time slots.
- Cold start: six slots a day, including breakfast, lunch and dinner times.
- Over time, slots adapt to the timestamps of the user's past transactions.
- The user responds by uploading. If there is nothing to report, they simply ignore the nudge; pfa does not follow up.

- As the user, I want reminders at the times I usually spend so that I don't forget to upload.
  - [ ] With no history, nudges arrive in six daily slots.
  - [ ] With history, slot timing reflects when past transactions occurred.
  - [ ] Ignoring a nudge produces no follow-up message.

### Weekly summary and recommendations
- At the start of the week, pfa sends a short Monday summary on Telegram with a link to the dashboard.
- The web app holds the full version: last week's stats, category stats, and recommendations against the remaining budget for the upcoming weeks.
- The user can also ask pfa for recommendations and insights at any time in chat.
- Recommendations cover insights, budgets and goals based on the running transactions and expenses.

- As the user, I want a short weekly recap so that I know where I stand without opening the app.
  - [ ] The Telegram summary is short and includes a link to the dashboard.
  - [ ] The dashboard shows last week's stats, category breakdown and recommendations against remaining budget.
  - [ ] Asking pfa in chat for insights returns a response based on my confirmed data.

## States and Boundaries

- **First use** — no greeting; the user can upload immediately. Web app screens with no data show an empty state (Assumption: a short "nothing here yet" line).
- **Processing** — immediate acknowledgement; chat stays usable.
- **Blurry or unreadable upload** — pfa returns what it read and asks the user to manually enter the unreadable fields.
- **Missing card/account** — pfa asks the user for it before saving.
- **Unconfirmed data** — not saved, not aggregated.
- **Ignored nudge** — no follow-up.
- **Demo triggering** — the Monday summary and nudges must be triggerable on demand for the demo video (Assumption; mechanism for `4-spec`).

## Product Decisions

- Name is "pfa" — personal finance assistant.
- No greeting; upload works immediately — keeps the chat feeling like talking to a person.
- Chat stays usable during processing — pfa should feel like a responsive human, not a form.
- Blurry data goes back to the user to fill in — avoid wrong data.
- Every extraction needs confirmation — data trust, since there's no bank feed.
- Required fields: merchant, amount, date, category, account/card; description optional and prefilled.
- Budget is per category per month, editable and versioned.
- Goal is a savings target with amount and date.
- Landing screen is the Dashboard (first in the menu), with Transactions next; everything else is one navigation step away. Changed from Today's transactions at the learner's request.
- Portfolios excluded from the PoC and moved to later — reduces build size.
- Look and Feel follows the Deloitte AI & Data page theme.
- Monday summary is short, with a link to the dashboard.
- Ignored nudges get no follow-up.

## What We're Building

- Telegram chat with the agent, including casual Q&A for recommendations and insights
- Upload of receipt images and statements (PDF, CSV, Excel), with extraction
- Confirmation flow with required fields and prefilled description
- Multiple cards under each bank account
- Web app: Today's transactions, dashboard/analytics, budgets (monthly, per category, versioned), goals
- Weekly summary (short on Telegram, full in web app), plus quarterly and yearly insights
- Adaptive nudges starting from six daily slots, on-demand triggering for the demo
- Recommendations for insights, budgets and goals

## Deferred From the POC

- Investment portfolios: the learner chose to exclude these for the PoC and do them next.
- WhatsApp: Telegram only for now.
- Email digest: Telegram notifications replace it.

## Possible Later Enhancements

- Investment portfolios, with their own uploads and a portfolio screen.
- WhatsApp as a second chat channel.
- Follow-up logic for ignored nudges.

## Non-Goals

- Bank integration: no real transaction feed; uploads and nudges stand in.
- Saving unconfirmed extractions: trust in the data matters more than speed.

## Open Questions

- **Accounts and cards management** — where does the user add a bank account and its cards (web app, chat, or created on first mention)? Resolve before `4-spec`.
- **Statement confirmation** — resolved: a statement is confirmed in one go, with a summary.
- **Ignored vs. "no transactions"** — earlier the idea was to confirm "nothing spent"; now the decision is to ignore the nudge. Assumed: ignoring counts as no data, not as a recorded zero. Confirm.
- **Quarterly and yearly insights** — assumed to live on the dashboard. Can wait for the build.
- **Accent color and font** — to be confirmed from the reference site. Can wait for `4-spec`.
