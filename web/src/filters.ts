// Transaction filters, kept in the URL so a filtered view survives a refresh.
export type DateBasis = 'occurred' | 'confirmed'
export type DirectionFilter = '' | 'in' | 'out' // '' means both

export interface Filters {
  basis: DateBasis
  from: string
  to: string
  month: string
  min: string
  max: string
  direction: DirectionFilter
  categories: string[]
}

export const NO_FILTERS: Filters = {
  basis: 'occurred',
  from: '',
  to: '',
  month: '',
  min: '',
  max: '',
  direction: '',
  categories: [],
}

function toDirection(value: string | null): DirectionFilter {
  return value === 'in' || value === 'out' ? value : ''
}

export function parseFilters(params: URLSearchParams): Filters {
  return {
    basis: params.get('basis') === 'confirmed' ? 'confirmed' : 'occurred',
    from: params.get('from') ?? '',
    to: params.get('to') ?? '',
    month: params.get('month') ?? '',
    min: params.get('min') ?? '',
    max: params.get('max') ?? '',
    direction: toDirection(params.get('direction')),
    categories: params.getAll('category'),
  }
}

export function toSearchParams(filters: Filters): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.basis === 'confirmed') params.set('basis', 'confirmed')
  if (filters.from) params.set('from', filters.from)
  if (filters.to) params.set('to', filters.to)
  if (filters.month) params.set('month', filters.month)
  if (filters.min) params.set('min', filters.min)
  if (filters.max) params.set('max', filters.max)
  if (filters.direction) params.set('direction', filters.direction)
  filters.categories.forEach((name) => params.append('category', name))
  return params
}

// With nothing set, the page shows the "confirmed today" preset. The date basis
// alone does not count: it changes nothing until a date is chosen.
export function isPreset(filters: Filters): boolean {
  return (
    !filters.from &&
    !filters.to &&
    !filters.month &&
    !filters.min &&
    !filters.max &&
    !filters.direction &&
    filters.categories.length === 0
  )
}

// Translates the UI's field names into the API's query string.
export function toApiQuery(filters: Filters): string {
  const params = new URLSearchParams()
  params.set('basis', filters.basis)
  if (filters.from) params.set('date_from', filters.from)
  if (filters.to) params.set('date_to', filters.to)
  if (filters.month) params.set('month', filters.month)
  if (filters.min) params.set('min_amount', filters.min)
  if (filters.max) params.set('max_amount', filters.max)
  if (filters.direction) params.set('direction', filters.direction)
  filters.categories.forEach((name) => params.append('category', name))
  return params.toString()
}

const MONTH_FORMAT = /^\d{4}-(0[1-9]|1[0-2])$/

function isRealDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return false
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])]
  const date = new Date(year, month - 1, day)
  return (
    date.getFullYear() === year &&
    date.getMonth() === month - 1 &&
    date.getDate() === day
  )
}

function isAmount(value: string): boolean {
  return value.trim() !== '' && Number.isFinite(Number(value)) && Number(value) >= 0
}

// What is wrong with the filters, in words a person can act on. An empty list means
// the filters can be sent. Some browsers show month and date pickers as plain text
// boxes, so the formats are checked here instead of leaving it to the server.
export function filterProblems(filters: Filters): string[] {
  const problems: string[] = []
  if (filters.month && !MONTH_FORMAT.test(filters.month)) {
    problems.push('Month must look like 2026-10 (YYYY-MM).')
  }
  const fromOk = !filters.from || isRealDate(filters.from)
  const toOk = !filters.to || isRealDate(filters.to)
  if (!fromOk) problems.push('“From” must be a real date like 2026-10-05 (YYYY-MM-DD).')
  if (!toOk) problems.push('“To” must be a real date like 2026-10-05 (YYYY-MM-DD).')
  if (fromOk && toOk && filters.from && filters.to && filters.from > filters.to) {
    problems.push('“From” is after “To”.')
  }
  const minOk = !filters.min || isAmount(filters.min)
  const maxOk = !filters.max || isAmount(filters.max)
  if (!minOk) problems.push('Min amount must be a number that is not negative, for example 25000.')
  if (!maxOk) problems.push('Max amount must be a number that is not negative, for example 25000.')
  if (minOk && maxOk && filters.min && filters.max && Number(filters.min) > Number(filters.max)) {
    problems.push('Min amount is above max amount.')
  }
  return problems
}
