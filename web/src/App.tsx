import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ApiError } from './api/client'
import { Layout } from './components/Layout'
import { RequireAuth } from './components/RequireAuth'
import { ComingSoon } from './pages/ComingSoon'
import { Settings } from './pages/Settings'
import { SignIn } from './pages/SignIn'
import { Transactions } from './pages/Transactions'

// Any 401 means the session ended: re-check it so the gate shows the sign-in screen.
function handleError(error: Error) {
  if (error instanceof ApiError && error.status === 401) {
    void queryClient.invalidateQueries({ queryKey: ['auth'] })
  }
}

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({ onError: handleError }),
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
              <Route index element={<Navigate to="/transactions/today" replace />} />
              <Route path="/transactions" element={<Transactions />} />
              <Route path="/transactions/today" element={<Transactions />} />
              <Route path="/dashboard" element={<ComingSoon title="Dashboard" />} />
              <Route path="/budgets" element={<ComingSoon title="Budgets" />} />
              <Route path="/goals" element={<ComingSoon title="Goals" />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="*" element={<Navigate to="/transactions/today" replace />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
