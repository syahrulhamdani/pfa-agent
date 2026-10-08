export function formatAmount(value: string | null): string {
  if (value === null) return '—'
  return Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

// Amounts are stored positive; the sign and the word say which way the money moved.
export function formatSigned(value: string | null, direction: 'in' | 'out'): string {
  if (value === null) return '—'
  return `${direction === 'in' ? '+' : '−'}${formatAmount(value)}`
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
