import { useCategories } from '../api/hooks'
import { filterProblems, isPreset, NO_FILTERS } from '../filters'
import type { DateBasis, Filters } from '../filters'

interface Props {
  filters: Filters
  onChange: (filters: Filters) => void
}

export function FilterBar({ filters, onChange }: Props) {
  const categories = useCategories()
  const problems = filterProblems(filters)
  const invalid = problems.length > 0

  function set(patch: Partial<Filters>) {
    onChange({ ...filters, ...patch })
  }

  function toggleCategory(name: string) {
    const selected = filters.categories.includes(name)
      ? filters.categories.filter((c) => c !== name)
      : [...filters.categories, name]
    set({ categories: selected })
  }

  // Shared by the inputs that can be flagged, so screen readers read the problems.
  const flagged = {
    'aria-invalid': invalid || undefined,
    'aria-describedby': invalid ? 'filter-problems' : undefined,
  }

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
          From <span className="hint">YYYY-MM-DD</span>
          <input
            type="date"
            placeholder="YYYY-MM-DD"
            value={filters.from}
            onChange={(e) => set({ from: e.target.value, month: '' })}
            {...flagged}
          />
        </label>
        <label>
          To <span className="hint">YYYY-MM-DD</span>
          <input
            type="date"
            placeholder="YYYY-MM-DD"
            value={filters.to}
            onChange={(e) => set({ to: e.target.value, month: '' })}
            {...flagged}
          />
        </label>
        <label>
          Month <span className="hint">YYYY-MM</span>
          <input
            type="month"
            placeholder="YYYY-MM"
            title="Use the format YYYY-MM, for example 2026-10"
            value={filters.month}
            onChange={(e) => set({ month: e.target.value, from: '', to: '' })}
            {...flagged}
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
            {...flagged}
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
            {...flagged}
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

      {invalid && (
        <div id="filter-problems" className="error" role="alert">
          {problems.map((problem) => (
            <p key={problem}>{problem}</p>
          ))}
        </div>
      )}

      <div className="form-row">
        <button type="button" onClick={() => onChange(NO_FILTERS)}>
          {isPreset(filters) ? 'Showing today' : 'Back to today'}
        </button>
      </div>
    </section>
  )
}
