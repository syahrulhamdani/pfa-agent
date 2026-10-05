// Transaction filters, kept in the URL so a filtered view survives a refresh.
export type DateBasis = 'occurred' | 'confirmed'

export interface Filters {
  basis: DateBasis
  from: string
  to: string
  month: string
  min: string
  max: string
  categories: string[]
}

export const NO_FILTERS: Filters = {
  basis: 'occurred',
  from: '',
  to: '',
  month: '',
  min: '',
  max: '',
  categories: [],
}

export function parseFilters(params: URLSearchParams): Filters {
  return {
    basis: params.get('basis') === 'confirmed' ? 'confirmed' : 'occurred',
    from: params.get('from') ?? '',
    to: params.get('to') ?? '',
    month: params.get('month') ?? '',
    min: params.get('min') ?? '',
    max: params.get('max') ?? '',
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
  filters.categories.forEach((name) => params.append('category', name))
  return params.toString()
}
