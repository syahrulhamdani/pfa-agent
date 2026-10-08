import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import { isPreset, toApiQuery } from '../filters'
import type { Filters } from '../filters'
import type { Bank, Card, Transaction, TransactionsChanged } from './types'

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

// Changes the category and/or direction of saved transactions; the lists then reload.
export function useChangeTransactions() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: {
      ids: number[]
      category?: string
      direction?: 'in' | 'out'
    }) =>
      api<TransactionsChanged>('/transactions', {
        method: 'PATCH',
        body: JSON.stringify(input),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['transactions'] }),
  })
}
