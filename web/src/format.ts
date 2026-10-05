export function formatAmount(value: string | null): string {
  if (value === null) return '—'
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

export function formatDate(value: string | null): string {
  if (value === null) return '—'
  // Dates arrive as YYYY-MM-DD; parse as local to avoid a timezone day shift.
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}
