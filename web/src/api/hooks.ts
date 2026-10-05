import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { Bank, Card, Transaction } from './types'

// New confirmations should appear without a reload.
const LIVE_REFETCH_MS = 5000

export function useTodayTransactions() {
  return useQuery({
    queryKey: ['transactions', 'today'],
    queryFn: () => api<Transaction[]>('/transactions/today'),
    refetchInterval: LIVE_REFETCH_MS,
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
