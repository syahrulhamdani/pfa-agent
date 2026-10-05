---
doc: scope
status: approved
---

# Personal Finance Agent

A Telegram-first agent that turns uploaded receipts and statements into live analytics, and proactively nudges, summarizes and recommends so one person can run their own money.

## The Unique Kernel
Recommendations and insights that adapt to the running transactions: weekly summaries that reflect the upcoming week's budget, budget and goal suggestions based on actual spending, and an adaptive nudge. With no bank integration, the agent learns when you usually transact from past timestamps (cold start: six slots a day around breakfast, lunch and dinner) and asks you to upload receipts, or to confirm that nothing was spent, in each slot.

## Who It's For
The learner themself: someone managing their own money across several banks, multiple cards per bank account and investment portfolios, with no bank integration. Today they would have to track and categorize everything by hand.

## The Core Loop
Chat with the agent on Telegram, as naturally as with a human, and upload a receipt or statement. The agent extracts the data, replies once it's processed with a link to the web app, and the numbers are aggregated in real time. Between uploads the agent nudges, and you confirm or upload. On the first day of the week, a summary arrives in the web app and on Telegram: last week's stats, category breakdown, and recommendations against the remaining budget for the coming week.

## Inspiration & Identity
Not stated yet. Direction volunteered: the Telegram chat should feel like talking to a person, not a bot menu.

## Why This Matters to the Learner
A tool for their own personal finances, and a way to learn how to work with coding agents without heavy prompting.

## What "Working" Looks Like
A one-minute demo video:
1. Upload a receipt in Telegram. Chat feels human; the agent replies when processed, with a link to the web app.
2. In the web app, explore aggregated data, then manage budgets and financial goals.
3. Back in Telegram, show the Monday summary, a nudge, and the recommendations/insights sent to the user. These are triggered on demand for the demo, not by waiting a week.

The "oh, that's cool" beat: the receipt becomes live analytics, and the agent then speaks up on its own with advice grounded in that data.

## The POC Boundary
- Telegram chat with the agent (Gemini Flash Lite for chat)
- Upload and extraction of receipts and statements: images, PDF, CSV and Excel (Gemini Pro for extraction)
- Multiple cards under each bank account
- Investment portfolios
- Web app: aggregated transactions, categories, budgets, goals
- Weekly summary (web app plus Telegram), and quarterly and yearly insights
- Adaptive nudge with "no transactions" confirmation, six slots a day to start
- Recommendations for insights, budgets and goals

## Later
- WhatsApp as a second chat channel (assumed later, since Telegram was the one named; confirm)
- Email digest for reminders

## Explicitly Cut
- Bank integration: no real transaction feed, so uploads plus nudge-and-confirm stand in.
