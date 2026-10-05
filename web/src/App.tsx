import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ComingSoon } from './pages/ComingSoon'
import { Settings } from './pages/Settings'
import { Today } from './pages/Today'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/transactions/today" replace />} />
            <Route path="/transactions/today" element={<Today />} />
            <Route path="/dashboard" element={<ComingSoon title="Dashboard" />} />
            <Route path="/budgets" element={<ComingSoon title="Budgets" />} />
            <Route path="/goals" element={<ComingSoon title="Goals" />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/transactions/today" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
