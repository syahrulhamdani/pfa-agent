# pfa web app

The React front end for pfa: dashboard, transactions, budgets, goals, and banks and cards.

It is part of the larger project: see the [main README](../README.md) for what pfa is and
how to run all of it. In short, with the API running (`uv run --env-file .env uvicorn
pfa.main:app` from the project root):

```bash
npm ci          # install, from the lockfile
npm run dev     # http://localhost:5173
npm run build   # type-check and build
npm run lint    # oxlint
```

The browser calls `/api/*` and the dev server forwards it to the API on port 8000 (set
`VITE_API_TARGET` to use another address), so there is nothing to configure for CORS.
Sign in by sending `/login` to your Telegram bot and opening the link.

Stack: Vite, React 19, TypeScript, TanStack Query, react-router, Recharts. The colours,
spacing and fonts are CSS variables at the top of `src/theme.css`.
