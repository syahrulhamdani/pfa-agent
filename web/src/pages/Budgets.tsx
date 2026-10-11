import { useState } from 'react'
import type { FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  useBudgetHistory,
  useBudgets,
  useCategories,
  useCopyBudgets,
  useSetBudget,
} from '../api/hooks'
import type { BudgetItem } from '../api/types'
import {
  barWidth,
  budgetState,
  copyMessage,
  monthLabel,
  parseMonth,
  percentUsed,
  shiftMonth,
  currentMonth,
} from '../budgets'
import { formatAmount } from '../format'

const STATE_WORDS = { ok: 'On track', near: 'Nearly used', over: 'Over budget' } as const

function leftText(item: BudgetItem): string {
  const remaining = Number(item.remaining)
  return remaining < 0
    ? `Over by ${formatAmount(String(-remaining))}`
    : `${formatAmount(item.remaining)} left`
}

function History({ item, month }: { item: BudgetItem; month: string }) {
  const history = useBudgetHistory(item.category, item.set_for.slice(0, 7), true)
  if (history.isPending) return <p className="muted">Loading versions…</p>
  if (history.isError) return <p className="error">{history.error.message}</p>
  return (
    <table aria-label={`Versions of the ${item.category} budget for ${monthLabel(month)}`}>
      <thead>
        <tr>
          <th>Version</th>
          <th className="num">Amount</th>
          <th>Saved</th>
        </tr>
      </thead>
      <tbody>
        {history.data.map((v) => (
          <tr key={v.version}>
            <td>
              {v.version}
              {v.current && <span className="muted"> · current</span>}
            </td>
            <td className="num">{formatAmount(v.amount)}</td>
            <td>{new Date(v.created_at).toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function BudgetRow({ item, month }: { item: BudgetItem; month: string }) {
  const [editing, setEditing] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [amount, setAmount] = useState(item.amount)
  const setBudget = useSetBudget()
  const state = budgetState(item.used)
  const carried = item.set_for !== item.month

  function save(event: FormEvent) {
    event.preventDefault()
    setBudget.mutate(
      { category: item.category, month, amount },
      { onSuccess: () => setEditing(false) },
    )
  }

  return (
    <>
      <tr>
        <td>
          {item.category}
          {carried && (
            <div className="muted">Carried over from {monthLabel(item.set_for.slice(0, 7))}</div>
          )}
        </td>
        <td className="num">
          {editing ? (
            <form onSubmit={save} className="inline-form">
              <input
                type="number"
                min="0.01"
                step="0.01"
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                aria-label={`New budget for ${item.category}`}
                autoFocus
              />
              <button type="submit" disabled={setBudget.isPending || !amount}>
                Save
              </button>
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  setEditing(false)
                  setAmount(item.amount)
                  setBudget.reset()
                }}
              >
                Cancel
              </button>
            </form>
          ) : (
            formatAmount(item.amount)
          )}
        </td>
        <td className="num">{formatAmount(item.spent)}</td>
        <td>
          <div
            className="bar-track"
            role="img"
            aria-label={`${percentUsed(item.used)} used`}
          >
            <div
              className={`bar-fill budget-${state}`}
              style={{ width: barWidth(item.used) }}
            />
          </div>
          <span className={`budget-text budget-text-${state}`}>
            {STATE_WORDS[state]} · {percentUsed(item.used)} · {leftText(item)}
          </span>
        </td>
        <td className="num nowrap">
          {!editing && (
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setAmount(item.amount)
                setEditing(true)
              }}
            >
              Edit
            </button>
          )}
          <button
            type="button"
            className="text-button"
            aria-expanded={showHistory}
            onClick={() => setShowHistory((open) => !open)}
          >
            {showHistory ? 'Hide versions' : `Versions (${item.version})`}
          </button>
        </td>
      </tr>
      {(setBudget.isError || showHistory) && (
        <tr>
          <td colSpan={5}>
            {setBudget.isError && (
              <p className="error" role="alert">
                {setBudget.error.message}
              </p>
            )}
            {showHistory && <History item={item} month={month} />}
          </td>
        </tr>
      )}
    </>
  )
}

function AddBudgetForm({
  month,
  taken,
}: {
  month: string
  taken: Set<string>
}) {
  const categories = useCategories()
  const [category, setCategory] = useState('')
  const [amount, setAmount] = useState('')
  const setBudget = useSetBudget()
  const available = (categories.data ?? []).filter((name) => !taken.has(name))

  function submit(event: FormEvent) {
    event.preventDefault()
    setBudget.mutate(
      { category, month, amount },
      {
        onSuccess: () => {
          setCategory('')
          setAmount('')
        },
      },
    )
  }

  if (categories.isSuccess && available.length === 0) {
    return <p className="muted">Every category has a budget for this month.</p>
  }
  return (
    <form onSubmit={submit}>
      <div className="form-row">
        <label>
          Category
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Choose a category</option>
            {available.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Monthly budget
          <input
            type="number"
            min="0.01"
            step="0.01"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="e.g. 1500000"
          />
        </label>
        <button type="submit" disabled={setBudget.isPending || !category || !amount}>
          Set budget
        </button>
      </div>
      {setBudget.isError && (
        <p className="error" role="alert">
          {setBudget.error.message}
        </p>
      )}
    </form>
  )
}

export function Budgets() {
  const [params, setParams] = useSearchParams()
  const month = parseMonth(params.get('month'))
  const { data, isPending, isError, error } = useBudgets(month)
  const copy = useCopyBudgets()
  const previous = shiftMonth(month, -1)

  function go(next: string) {
    copy.reset() // the message belongs to the month it was shown for
    setParams(next === currentMonth() ? {} : { month: next })
  }

  const remaining = data ? Number(data.total_remaining) : 0
  const taken = new Set(data?.items.map((i) => i.category) ?? [])

  return (
    <>
      <div className="page-head">
        <h1>Budgets</h1>
        <p className="muted">
          A budget is set per category and month. Spending is money out; moves between
          your own accounts are not counted. Editing keeps every earlier version.
        </p>
      </div>

      <div className="stack">
      <div className="dash-toolbar card">
        <button
          type="button"
          className="secondary-button"
          disabled={copy.isPending}
          onClick={() => copy.mutate({ from_month: previous, to_month: month })}
        >
          Copy budgets from {monthLabel(previous)}
        </button>
        <div className="period-nav">
          <button
            type="button"
            className="secondary-button"
            aria-label="Previous month"
            onClick={() => go(shiftMonth(month, -1))}
          >
            ‹
          </button>
          <strong className="period-label">{monthLabel(month)}</strong>
          <button
            type="button"
            className="secondary-button"
            aria-label="Next month"
            onClick={() => go(shiftMonth(month, 1))}
          >
            ›
          </button>
          {month !== currentMonth() && (
            <button type="button" className="link-button" onClick={() => go(currentMonth())}>
              This month
            </button>
          )}
        </div>
      </div>

      {copy.isSuccess && (
        <p className="toast" role="status">
          {copyMessage(copy.data, monthLabel(previous))}
        </p>
      )}
      {copy.isError && (
        <p className="error" role="alert">
          Could not copy: {copy.error.message}
        </p>
      )}
      {isPending && <p className="state">Loading…</p>}
      {isError && (
        <p className="state error" role="alert">
          Could not load budgets: {error.message}
        </p>
      )}

      {data && (
        <>
          <div className="stat-row">
            <div className="card">
              <div className="stat-label">Budgeted</div>
              <div className="stat-value muted-value">{formatAmount(data.total_budget)}</div>
              <div className="muted">
                {data.items.length} {data.items.length === 1 ? 'category' : 'categories'}
              </div>
            </div>
            <div className="card">
              <div className="stat-label">Spent</div>
              <div className="stat-value amount-out">{formatAmount(data.total_spent)}</div>
              <div className="muted">in budgeted categories</div>
            </div>
            <div className="card">
              <div className="stat-label">{remaining < 0 ? 'Over budget by' : 'Left'}</div>
              <div
                className={`stat-value ${remaining < 0 ? 'amount-out' : 'amount-in'}`}
              >
                {formatAmount(String(Math.abs(remaining)))}
              </div>
              <div className="muted">
                {remaining < 0 ? 'across budgeted categories' : 'to spend this month'}
              </div>
            </div>
            {Number(data.unbudgeted_spent) > 0 && (
              <div className="card">
                <div className="stat-label">No budget</div>
                <div className="stat-value muted-value">
                  {formatAmount(data.unbudgeted_spent)}
                </div>
                <div className="muted">spent in other categories</div>
              </div>
            )}
          </div>

          {data.items.length === 0 ? (
            <p className="state">
              No budgets for {monthLabel(month)} yet. Set one below to see how much is left.
            </p>
          ) : (
            <div className="card table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Category</th>
                    <th className="num">Budget</th>
                    <th className="num">Spent</th>
                    <th>Used</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <BudgetRow key={item.category} item={item} month={month} />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <section className="card">
            <h2>Set a budget</h2>
            <AddBudgetForm month={month} taken={taken} />
          </section>
        </>
      )}
      </div>
    </>
  )
}
