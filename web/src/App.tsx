import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query'
import { Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ApiError } from './api/client'
import { Layout } from './components/Layout'
import { RequireAuth } from './components/RequireAuth'
import { ComingSoon } from './pages/ComingSoon'
import { Settings } from './pages/Settings'
import { SignIn } from './pages/SignIn'
import { Transactions } from './pages/Transactions'

// Only the dashboard needs the chart library, so that page loads on demand.
const Dashboard = lazy(() =>
  import('./pages/Dashboard').then((m) => ({ default: m.Dashboard })),
)

// A 401 from a data request means the session ended: re-check it so the gate shows
// the sign-in screen. The session check itself is excluded. Its own 401 is the
// answer, and invalidating it would refetch it forever.
function handleError(error: Error) {
  if (error instanceof ApiError && error.status === 401) {
    void queryClient.invalidateQueries({ queryKey: ['auth'] })
  }
}

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (query.queryKey[0] !== 'auth') handleError(error)
    },
  }),
  mutationCache: new MutationCache({ onError: handleError }),
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/auth" element={<SignIn />} />
          <Route element={<RequireAuth />}>
            <Route element={<Layout />}>
              <Route index element={<Navigate to="/dashboard" replace />} />
              <Route path="/transactions" element={<Transactions />} />
              <Route path="/transactions/today" element={<Transactions />} />
              <Route
                path="/dashboard"
                element={
                  <Suspense fallback={<p className="state">Loading…</p>}>
                    <Dashboard />
                  </Suspense>
                }
              />
              <Route path="/budgets" element={<ComingSoon title="Budgets" />} />
              <Route path="/goals" element={<ComingSoon title="Goals" />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
