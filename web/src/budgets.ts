// Months travel as YYYY-MM. They are read and written as local calendar months, so no
// timezone can move a budget into the wrong month.
const MONTH_FORMAT = /^\d{4}-(0[1-9]|1[0-2])$/

export function currentMonth(now: Date = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

export function parseMonth(value: string | null): string {
  return value && MONTH_FORMAT.test(value) ? value : currentMonth()
}

export function shiftMonth(month: string, by: number): string {
  const [year, number] = month.split('-').map(Number)
  return currentMonth(new Date(year, number - 1 + by, 1))
}

export function monthLabel(month: string): string {
  const [year, number] = month.split('-').map(Number)
  return new Date(year, number - 1, 1).toLocaleDateString(undefined, {
    month: 'long',
    year: 'numeric',
  })
}

// What a copy did, in words. It never overwrites, so skipped ones are said out loud.
export function copyMessage(
  result: { copied: number; skipped: number },
  fromLabel: string,
): string {
  if (result.copied === 0 && result.skipped === 0) {
    return `${fromLabel} has no budgets to copy.`
  }
  const budgets = (n: number) => `${n} ${n === 1 ? 'budget' : 'budgets'}`
  if (result.copied === 0) {
    return `Nothing copied: every budget from ${fromLabel} is already set this month.`
  }
  const one = result.skipped === 1
  const left =
    result.skipped > 0
      ? ` ${budgets(result.skipped)} already set this month ${one ? 'was' : 'were'} left as ${one ? 'it is' : 'they are'}.`
      : ''
  return `Copied ${budgets(result.copied)} from ${fromLabel}.${left}`
}

export type BudgetState = 'ok' | 'near' | 'over'

// Said in words as well as colour: "near" starts at 85% used.
export function budgetState(used: number): BudgetState {
  if (used > 1) return 'over'
  if (used >= 0.85) return 'near'
  return 'ok'
}

export function percentUsed(used: number): string {
  return `${Math.round(used * 100)}%`
}

// The bar never grows past its track, even when the budget is far exceeded.
export function barWidth(used: number): string {
  return `${Math.min(Math.max(used, 0), 1) * 100}%`
}

export function goalStatus(daysLeft: number, progress: number): string {
  if (progress >= 1) return 'Goal reached'
  if (daysLeft < 0) {
    const days = -daysLeft
    return `Target date passed ${days} ${days === 1 ? 'day' : 'days'} ago`
  }
  if (daysLeft === 0) return 'Target date is today'
  return `${daysLeft} ${daysLeft === 1 ? 'day' : 'days'} left`
}
