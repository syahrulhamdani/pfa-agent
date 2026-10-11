import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { isPreset, toApiQuery } from '../filters'
import type { Filters } from '../filters'
import type {
  Analytics,
  Bank,
  Budgets,
  BudgetVersion,
  Card,
  Goal,
  GoalInput,
  Transaction,
  TransactionsChanged,
} from './types'

export function useSession() {
  return useQuery({
    queryKey: ['auth', 'me'],
    queryFn: () => api<{ authenticated: boolean }>('/auth/me'),
    retry: false,
    staleTime: 60_000,
  })
}

export function useLogout() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api<unknown>('/auth/logout', { method: 'POST' }),
    onSuccess: () => {
      client.clear()
    },
  })
}

// New confirmations should appear without a reload.
const LIVE_REFETCH_MS = 5000

// No filters means the "confirmed today" preset; otherwise the filtered search.
export function useTransactions(filters: Filters, enabled = true) {
  const preset = isPreset(filters)
  const query = toApiQuery(filters)
  return useQuery({
    queryKey: ['transactions', preset ? 'today' : query],
    queryFn: () =>
      api<Transaction[]>(preset ? '/transactions/today' : `/transactions?${query}`),
    refetchInterval: LIVE_REFETCH_MS,
    enabled,
  })
}

export function useCategories() {
  return useQuery({
    queryKey: ['categories'],
    queryFn: () => api<string[]>('/categories'),
    staleTime: Infinity,
  })
}

export function useBanks() {
  return useQuery({ queryKey: ['banks'], queryFn: () => api<Bank[]>('/banks') })
}

export function useCards() {
  return useQuery({ queryKey: ['cards'], queryFn: () => api<Card[]>('/cards') })
}

export function useCreateBank() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      api<Bank>('/banks', { method: 'POST', body: JSON.stringify({ name }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['banks'] }),
  })
}

export function useCreateCard() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { bankId: number; name: string; last4: string | null }) =>
      api<Card>(`/banks/${input.bankId}/cards`, {
        method: 'POST',
        body: JSON.stringify({ name: input.name, last4: input.last4 }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['cards'] }),
  })
}

// Changes the category, direction and/or transfer flag of saved transactions; the lists then reload.
export function useChangeTransactions() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: {
      ids: number[]
      category?: string
      direction?: 'in' | 'out'
      is_transfer?: boolean
    }) =>
      api<TransactionsChanged>('/transactions', {
        method: 'PATCH',
        body: JSON.stringify(input),
      }),
    // The dashboard adds up the same transactions, so it reloads too.
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: ['transactions'] }),
        client.invalidateQueries({ queryKey: ['analytics'] }),
      ]),
  })
}

// The dashboard for the period containing `date` (today when null).
export function useAnalytics(period: string, date: string | null) {
  const query = new URLSearchParams({ period })
  if (date) query.set('date', date)
  return useQuery({
    queryKey: ['analytics', period, date ?? 'today'],
    queryFn: () => api<Analytics>(`/analytics?${query.toString()}`),
    refetchInterval: LIVE_REFETCH_MS,
  })
}

export function useBudgets(month: string) {
  return useQuery({
    queryKey: ['budgets', month],
    queryFn: () => api<Budgets>(`/budgets?month=${month}`),
    refetchInterval: LIVE_REFETCH_MS, // spending changes as receipts are confirmed
  })
}

// Every save adds a version; the history only loads once it is opened.
export function useBudgetHistory(category: string, month: string, enabled: boolean) {
  return useQuery({
    queryKey: ['budget-history', category, month],
    queryFn: () =>
      api<BudgetVersion[]>(
        `/budgets/history?${new URLSearchParams({ category, month })}`,
      ),
    enabled,
  })
}

export function useSetBudget() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { category: string; month: string; amount: string }) =>
      api<BudgetVersion>('/budgets', { method: 'PUT', body: JSON.stringify(input) }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: ['budgets'] }),
        client.invalidateQueries({ queryKey: ['budget-history'] }),
        client.invalidateQueries({ queryKey: ['analytics'] }),
      ]),
  })
}

// Duplicates one month's budgets into another; it never overwrites an existing one.
export function useCopyBudgets() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { from_month: string; to_month: string }) =>
      api<{ copied: number; skipped: number }>('/budgets/copy', {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: ['budgets'] }),
        client.invalidateQueries({ queryKey: ['analytics'] }),
      ]),
  })
}

export function useGoals() {
  return useQuery({ queryKey: ['goals'], queryFn: () => api<Goal[]>('/goals') })
}

export function useCreateGoal() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: GoalInput) =>
      api<Goal>('/goals', { method: 'POST', body: JSON.stringify(input) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['goals'] }),
  })
}

export function useUpdateGoal() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...changes }: { id: number } & Partial<GoalInput>) =>
      api<Goal>(`/goals/${id}`, { method: 'PATCH', body: JSON.stringify(changes) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['goals'] }),
  })
}

export function useDeleteGoal() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api<undefined>(`/goals/${id}`, { method: 'DELETE' }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['goals'] }),
  })
}
