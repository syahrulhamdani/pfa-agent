import { useState } from 'react'
import { useCategories } from '../api/hooks'
import { describeFilters, filterProblems, isPreset, NO_FILTERS } from '../filters'
import type { DateBasis, DirectionFilter, Filters } from '../filters'

interface Props {
  filters: Filters
  onChange: (filters: Filters) => void
}

export function FilterBar({ filters, onChange }: Props) {
  const categories = useCategories()
  const problems = filterProblems(filters)
  const invalid = problems.length > 0
  const [open, setOpen] = useState(false)

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
    <div className="filter-toolbar">
      <div className="filter-summary">
        <span className="muted">Showing</span>
        {describeFilters(filters).map((part) => (
          <span key={part} className="filter-chip">
            {part}
          </span>
        ))}
        <span className="filter-actions">
          <button
            type="button"
            className="secondary-button"
            aria-expanded={open}
            aria-controls="filter-panel"
            onClick={() => setOpen(!open)}
          >
            {open ? 'Hide filters' : 'Filters'}
          </button>
          {!isPreset(filters) && (
            <button
              type="button"
              className="text-button"
              onClick={() => onChange(NO_FILTERS)}
            >
              Back to today
            </button>
          )}
        </span>
      </div>
      {invalid && !open && (
        <p className="error" role="alert">
          {problems[0]} Open the filters to fix it.
        </p>
      )}
      {open && (
    <section id="filter-panel" className="card filters filter-panel" aria-label="Filters">
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
            placeholder="YYYY-MM-DD"
            value={filters.from}
            onChange={(e) => set({ from: e.target.value, month: '' })}
            {...flagged}
          />
        </label>
        <label>
          To
          <input
            type="date"
            placeholder="YYYY-MM-DD"
            value={filters.to}
            onChange={(e) => set({ to: e.target.value, month: '' })}
            {...flagged}
          />
        </label>
        <label>
          Month
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
          Type
          <select
            value={filters.direction}
            onChange={(e) => set({ direction: e.target.value as DirectionFilter })}
          >
            <option value="">Money in and out</option>
            <option value="out">Money out</option>
            <option value="in">Money in</option>
          </select>
        </label>
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

    </section>
      )}
    </div>
  )
}
