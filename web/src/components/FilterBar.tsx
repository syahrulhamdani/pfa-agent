import { useCategories } from '../api/hooks'
import { isPreset, NO_FILTERS } from '../filters'
import type { DateBasis, Filters } from '../filters'

interface Props {
  filters: Filters
  onChange: (filters: Filters) => void
}

export function FilterBar({ filters, onChange }: Props) {
  const categories = useCategories()

  function set(patch: Partial<Filters>) {
    onChange({ ...filters, ...patch })
  }

  function toggleCategory(name: string) {
    const selected = filters.categories.includes(name)
      ? filters.categories.filter((c) => c !== name)
      : [...filters.categories, name]
    set({ categories: selected })
  }

  const rangeInvalid = filters.from && filters.to && filters.from > filters.to
  const amountInvalid =
    filters.min && filters.max && Number(filters.min) > Number(filters.max)

  return (
    <section className="card filters" aria-label="Filters">
      <div className="form-row">
        <label>
          Date field
          <select
            value={filters.basis}
            onChange={(e) => set({ basis: e.target.value as DateBasis })}
          >
            <option value="occurred">Receipt date</option>
            <option value="confirmed">Confirmed date</option>
          </select>
        </label>
        <label>
          From
          <input
            type="date"
            value={filters.from}
            onChange={(e) => set({ from: e.target.value, month: '' })}
          />
        </label>
        <label>
          To
          <input
            type="date"
            value={filters.to}
            onChange={(e) => set({ to: e.target.value, month: '' })}
          />
        </label>
        <label>
          Month
          <input
            type="month"
            value={filters.month}
            onChange={(e) => set({ month: e.target.value, from: '', to: '' })}
          />
        </label>
      </div>

      <div className="form-row">
        <label>
          Min amount
          <input
            type="number"
            min="0"
            inputMode="decimal"
            value={filters.min}
            onChange={(e) => set({ min: e.target.value })}
          />
        </label>
        <label>
          Max amount
          <input
            type="number"
            min="0"
            inputMode="decimal"
            value={filters.max}
            onChange={(e) => set({ max: e.target.value })}
          />
        </label>
      </div>

      {categories.data && categories.data.length > 0 && (
        <fieldset className="chips">
          <legend>Categories</legend>
          {categories.data.map((name) => (
            <label key={name} className="chip">
              <input
                type="checkbox"
                checked={filters.categories.includes(name)}
                onChange={() => toggleCategory(name)}
              />
              {name}
            </label>
          ))}
        </fieldset>
      )}

      {rangeInvalid && <p className="error">“From” is after “To”.</p>}
      {amountInvalid && <p className="error">Min amount is above max amount.</p>}

      <div className="form-row">
        <button type="button" onClick={() => onChange(NO_FILTERS)}>
          {isPreset(filters) ? 'Showing today' : 'Back to today'}
        </button>
      </div>
    </section>
  )
}
