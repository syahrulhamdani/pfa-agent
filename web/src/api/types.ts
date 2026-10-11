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

export interface TransactionsChanged {
  updated: number
}

export type PeriodName = 'day' | 'week' | 'month' | 'quarter' | 'year'

export interface MoneyTotal {
  total: string
  count: number
}

export interface CategoryShare {
  category: string
  total: string
  count: number
  // A fraction of that side's total: 0.25 is a quarter.
  share: number
}

export interface SeriesPoint {
  start: string
  money_out: string
  money_in: string
}

export interface Analytics {
  period: PeriodName
  start: string
  end: string
  bucket: 'day' | 'week' | 'month' | null
  money_out: MoneyTotal
  money_in: MoneyTotal
  net: string
  // Moves between the user's own accounts: reported apart, in neither total.
  transfers: MoneyTotal
  out_by_category: CategoryShare[]
  in_by_category: CategoryShare[]
  series: SeriesPoint[]
  previous: {
    start: string
    end: string
    money_out: string
    money_in: string
    money_out_change: number | null
    money_in_change: number | null
  }
  // Only for a month, the unit budgets are set in.
  budgets: Budgets | null
}

export interface BudgetItem {
  category: string
  month: string
  set_for: string
  amount: string
  version: number
  spent: string
  remaining: string
  used: number
}

export interface Budgets {
  month: string
  items: BudgetItem[]
  total_budget: string
  total_spent: string
  total_remaining: string
  unbudgeted_spent: string
}

export interface BudgetVersion {
  version: number
  amount: string
  created_at: string
  current: boolean
}

export interface Goal {
  id: number
  name: string
  target_amount: string
  target_date: string
  saved_amount: string
  progress: number
  remaining: string
  days_left: number
}

export interface GoalInput {
  name: string
  target_amount: string
  target_date: string
  saved_amount?: string
}

export interface BudgetItem {
  category: string
  month: string
  set_for: string
  amount: string
  version: number
  spent: string
  remaining: string
  used: number
}

export interface Budgets {
  month: string
  items: BudgetItem[]
  total_budget: string
  total_spent: string
  total_remaining: string
  unbudgeted_spent: string
}

export interface BudgetVersion {
  version: number
  amount: string
  created_at: string
  current: boolean
}

export interface Goal {
  id: number
  name: string
  target_amount: string
  target_date: string
  saved_amount: string
  progress: number
  remaining: string
  days_left: number
}

export interface GoalInput {
  name: string
  target_amount: string
  target_date: string
  saved_amount?: string
}
