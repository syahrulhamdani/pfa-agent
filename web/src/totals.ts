import type { Transaction } from './api/types'

export interface Totals {
  moneyOut: number
  moneyIn: number
  net: number
  // Moves between the user's own accounts: listed, but neither spending nor income.
  transfers: { count: number; total: number }
}

// Amounts arrive as decimal strings. They are added up in whole cents so that
// floating-point error can never creep into a money total.
function toCents(amount: string | null): number {
  return amount === null ? 0 : Math.round(Number(amount) * 100)
}

export function summarizeTransactions(transactions: Transaction[]): Totals {
  let out = 0
  let received = 0
  let moved = 0
  let movedCount = 0
  for (const tx of transactions) {
    const cents = toCents(tx.amount)
    if (tx.is_transfer) {
      moved += cents
      movedCount += 1
    } else if (tx.direction === 'in') {
      received += cents
    } else {
      out += cents
    }
  }
  return {
    moneyOut: out / 100,
    moneyIn: received / 100,
    net: (received - out) / 100,
    transfers: { count: movedCount, total: moved / 100 },
  }
}
