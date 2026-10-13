# Submission kit

What the hackathon asks for:

- **A demo video, 1 to 3 minutes** (a screen recording is fine).
- **A public repo URL** (GitHub, GitLab or Bitbucket).
- **A short description:** what it does, who it's for, what you learned.

> **Reviewers will not clone or run the code, so the video has to show it working.** The
> README and screenshots in the repo are the second thing they see. Everything below is
> built around that.

## 1. Short description (draft: edit it into your own words)

**pfa is a personal finance assistant that lives in Telegram.** You send it a photo of a
receipt, or a bank statement as PDF, CSV or Excel. It reads the document with Gemini,
shows you what it found, and saves it only when you confirm. A web app then shows where
your money went: a dashboard by day, week, month, quarter or year; budgets with a
version history; savings goals; and a weekly summary with advice that pfa also sends you
every Monday. It nudges you at the times you usually spend, and you can ask it things like
"how am I doing on dining this week?".

**Who it's for:** one person who wants to understand their own spending without
spreadsheets or a bank integration, and who would rather send a photo to a chat than fill
in a form.

**What makes it different:** the model never supplies a number. Every figure is computed in
code from your confirmed transactions; Gemini only writes the sentences, does any
arithmetic through a calculator tool, and any reply that quotes a figure that is not a fact
is thrown away. Money in and money out are kept apart, and moves between your own accounts
are left out of both, so paying a card bill never counts twice.

**What I learned** (draft):

- **Keep the model away from the numbers.** The most important decision was a design rule,
  not a prompt: compute figures in code, let the model write words, and verify its output
  against the facts. It caught real mistakes, and it was still not enough on its own: a
  reply with no numbers can still claim a trend that is not there ("spending looks steady"
  on a week with no transactions), so words need guards too.
- **Look at the real thing.** Many of the problems that mattered, such as a salary
  flattening a spending chart, a cramped table, or a sentence that read wrongly, only showed
  up in a real browser or in the real Telegram message, not in tests.
- **Product decisions come from using it.** Treating "a move between my own pockets" as a
  flag on the transaction instead of a category, keeping money in and out apart, and
  letting people review what was left out of the totals all came from trying the app and
  asking "does this make sense to a person?".
- **Small safety habits add up**: receipts held only in memory, masked traces, single-use
  sign-in links, one chat answered, nothing counted until confirmed.

**Built with:** Python, FastAPI, SQLAlchemy and Alembic, PostgreSQL, python-telegram-bot,
APScheduler, LangGraph and LangChain, Google Gemini (Flash Lite and Pro), LangSmith
(optional), Vite, React, TypeScript, TanStack Query, Recharts, Docker.

### The 2-sentence version (for a short field)

pfa turns a photo of a receipt or a bank statement, sent to a Telegram bot, into a
confirmed record, then shows budgets, goals and a Monday summary in a web app. Every
number is computed in code and checked, never written by the AI.

## 2. The demo video (aim for about 2:30; hard limit 3:00)

Show it working, in this order. Each beat has what to show and a line to say (keep your
own words; these are prompts).

| Time | On screen | Say |
|---|---|---|
| 0:00 | Telegram on the left, the web app on the right. pfa's chat open | "This is pfa. I never open a finance app: I just send it things." |
| 0:10 | Send `examples/receipt.png` as a photo. The "processing" reply, then the extraction reply with merchant, amount, date, category, card | "I send a receipt. It replies at once and keeps chatting while Gemini reads it." |
| 0:35 | Tap **Confirm**. The "Saved" reply with the sign-in link | "Nothing is saved until I confirm. Then it gives me a one-time link into the web app." |
| 0:45 | Open the link. The dashboard loads, the new transaction is visible under Transactions | "A single-use link, no passwords. And there it is." |
| 1:00 | Dashboard: money out and in kept apart, **Between accounts** card, the chart, **Budgets** with one over budget | "Money in and out are separate, and moving money between my own pockets isn't counted as spending." |
| 1:20 | Click **Review** on the Between accounts card, then a category link | "I can always see what was left out, and every number links to its transactions." |
| 1:35 | **Budgets**: edit one, open **Versions**. Then **Goals** | "Budgets keep every version. Goals show the pace I need." |
| 1:55 | Telegram: send `/demo_summary`. The summary message arrives | "Every Monday it speaks up on its own. Here is the summary, with advice." |
| 2:10 | Ask "how am I doing on dining this month?" Show the answer and the figures under it | "I can ask in plain words. The sentences come from Gemini; every figure is computed by code." |
| 2:25 | Ask "what is 15% of 2,000,000?" | "Even simple maths goes through a calculator tool. The model never makes up a number." |
| 2:40 | The README or the architecture diagram, then the repo URL | "Built with Gemini, LangGraph, FastAPI and React. The code and screenshots are in the repo." |

**To get under 2:00**, drop the **Review** click, the Budgets/Goals beat and the
calculator question.

**If you want to show a statement too**, send `examples/statement.csv` after the receipt:
pfa shows the count, total, highest and lowest, lists moves between your own accounts on
their own line, and saves it on one tap.

### Before you record (10 minutes)

1. **Start clean, with sample data behind you.**
   ```bash
   make reset-db      # asks first; deletes the local database
   make migrate
   make seed          # fictional sample data, so the dashboard is full
   ```
2. `make doctor` should show every line ticked. Start `make api` and `make web`.
3. Send **`/signout`** so the video can show signing in, then send `/login` when you reach
   that beat.
4. **Do one dry run of a receipt first** to make sure Gemini answers and your quota is fine.
   Then repeat step 1 (reset, migrate, seed) so the receipt you record is the first one.
5. **Don't show secrets.** Keep `.env` closed, and don't leave a sign-in link on screen
   longer than needed (it works once and expires in 10 minutes, but still).
6. **Telegram links on `localhost` aren't tappable.** Copy the link and paste it into the
   browser; you can cut that moment.
7. Use the desktop Telegram app next to the browser, a large font, 1080p, and close other
   chats and notifications.
8. Gemini calls take a few seconds. Cutting the waiting is fine; it is a screen recording.

## 3. Before you submit

- [ ] **The repo is public**, and the README renders with its screenshots. (The whole git
      history was scanned for keys, tokens and secrets: none found; no `.env`, key, data
      or personal-profile file was ever committed.)
- [ ] **Add a `LICENSE` file.** There isn't one yet. A public repo without a licence is, in
      law, "all rights reserved"; MIT is the usual choice for a hackathon project, but it
      is your decision.
- [ ] **The video is 1 to 3 minutes** and is public or unlisted with a link that works
      without signing in.
- [ ] **The description** (section 1) is pasted in and edited into your own words, especially
      "what I learned".
- [ ] **Re-run `make check`** on the final commit (tests, lint, web build).
- [ ] Optional: add two Telegram screenshots to `docs/screenshots/` and to the README
      (the receipt confirmation and the Monday summary). They can't be generated here, and
      they are the most distinctive part of the product.
