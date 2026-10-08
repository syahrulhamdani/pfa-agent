export interface Transaction {
  id: number
  merchant: string | null
  // Decimals are serialized as strings by the API.
  amount: string | null
  occurred_on: string | null
  category: string | null
  card: string | null
  description: string | null
  // Which way the money moved: out is an expense, in is income. Amounts are positive.
  direction: 'in' | 'out'
  // True for a move between the user's own accounts, which totals do not count.
  is_transfer: boolean
  confirmed_at: string | null
}

export interface Bank {
  id: number
  name: string
}

export interface Card {
  id: number
  bank_id: number
  name: string
  last4: string | null
}

export interface CategoryChanged {
  updated: number
}
