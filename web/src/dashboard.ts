import type { PeriodName } from './api/types'

export const PERIODS: { value: PeriodName; label: string }[] = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: 'quarter', label: 'Quarter' },
  { value: 'year', label: 'Year' },
]

export function parsePeriod(value: string | null): PeriodName {
  return PERIODS.some((p) => p.value === value) ? (value as PeriodName) : 'month'
}

// Dates travel as YYYY-MM-DD strings. They are read and written as local calendar
// dates, so no timezone can shift a day.
function parseIso(iso: string): Date {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day)
}

function toIso(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function addDaysIso(iso: string, days: number): string {
  const date = parseIso(iso)
  date.setDate(date.getDate() + days)
  return toIso(date)
}

const MONTH_SHORT = { month: 'short' } as const

export function periodLabel(period: PeriodName, start: string, end: string): string {
  const from = parseIso(start)
  const to = parseIso(end)
  const short = (d: Date) => d.toLocaleDateString(undefined, { day: 'numeric', ...MONTH_SHORT })
  switch (period) {
    case 'day':
      return from.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
    case 'week':
      return `${short(from)} – ${short(to)} ${to.getFullYear()}`
    case 'month':
      return from.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
    case 'quarter':
      return `Q${Math.floor(from.getMonth() / 3) + 1} ${from.getFullYear()}`
    case 'year':
      return String(from.getFullYear())
  }
}

export function bucketLabel(start: string, bucket: 'day' | 'week' | 'month'): string {
  const date = parseIso(start)
  if (bucket === 'day') return String(date.getDate())
  if (bucket === 'week') {
    return date.toLocaleDateString(undefined, { day: 'numeric', ...MONTH_SHORT })
  }
  return date.toLocaleDateString(undefined, MONTH_SHORT)
}

export interface Change {
  text: string
  direction: 'up' | 'down' | 'flat' | 'none'
}

// How a fraction such as 0.25 reads on the page. The arrow and the word carry the
// meaning, so it never depends on colour alone.
export function describeChange(change: number | null): Change {
  if (change === null) return { text: 'nothing to compare with', direction: 'none' }
  const percent = Math.round(Math.abs(change) * 100)
  if (percent === 0) return { text: 'no change', direction: 'flat' }
  const shown = percent > 999 ? '999%+' : `${percent.toLocaleString()}%`
  return { text: shown, direction: change > 0 ? 'up' : 'down' }
}

// A link to the transactions behind a category, for the same dates (by receipt date).
// "Uncategorised" has no filter to link to.
export function categoryLink(
  start: string,
  end: string,
  category: string,
  direction: 'in' | 'out',
): string | null {
  if (category === 'Uncategorised') return null
  const params = new URLSearchParams({ from: start, to: end, direction })
  params.append('category', category)
  return `/transactions?${params.toString()}`
}

// The moves between the user's own accounts in a period, which the totals leave out.
export function transfersLink(start: string, end: string): string {
  return `/transactions?${new URLSearchParams({ from: start, to: end, counting: 'transfer' })}`
}

export const CHART_COLORS = { out: '#a8201a', in: '#1b6e09' } as const
