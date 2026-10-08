import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useCategories, useChangeTransactions, useTransactions } from '../api/hooks'
import { FilterBar } from '../components/FilterBar'
import { filterProblems, isPreset, parseFilters, toSearchParams } from '../filters'
import type { Filters } from '../filters'
import { formatAmount, formatDate, formatSigned } from '../format'
import { summarizeTransactions } from '../totals'

export function Transactions() {
  const [params, setParams] = useSearchParams()
  const filters = parseFilters(params)
  const preset = isPreset(filters)
  const valid = filterProblems(filters).length === 0
  // Nothing is sent while the filters are invalid; the filter bar says what to fix.
  const { data, isPending, isError, error } = useTransactions(filters, valid)
  const categories = useCategories()
  const change = useChangeTransactions()

  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkCategory, setBulkCategory] = useState('')
  const [bulkDirection, setBulkDirection] = useState<'' | 'in' | 'out'>('')
  const [notice, setNotice] = useState<string | null>(null)

  function changeFilters(next: Filters) {
    setParams(toSearchParams(next), { replace: true })
  }

  // Only rows that are still on screen count as selected.
  const visibleIds = data?.map((tx) => tx.id) ?? []
  const selectedIds = visibleIds.filter((id) => selected.has(id))
  const allSelected = visibleIds.length > 0 && selectedIds.length === visibleIds.length

  function toggle(id: number) {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(visibleIds))
  }

  // One request changes the category, the direction, or both, for one row or many.
  function apply(ids: number[], changes: { category?: string; direction?: 'in' | 'out' }) {
    setNotice(null)
    change.mutate(
      { ids, ...changes },
      {
        onSuccess: (result) => {
          const noun = result.updated === 1 ? 'transaction' : 'transactions'
          const what = [
            changes.category && `category ${changes.category}`,
            changes.direction && `marked as money ${changes.direction}`,
          ].filter(Boolean)
          setNotice(`Updated ${result.updated} ${noun}: ${what.join(', ')}.`)
          setSelected(new Set())
          setBulkCategory('')
          setBulkDirection('')
        },
      },
    )
  }

  // With exactly one row ticked, offer to tick every row from the same merchant, which
  // is the usual reason to change many at once (every Indomaret line, say).
  const only = selectedIds.length === 1 ? data?.find((t) => t.id === selectedIds[0]) : undefined
  const sameMerchant = only?.merchant
    ? (data ?? []).filter((t) => t.merchant === only.merchant)
    : []

  // Money out and money in are added up apart, and moves between the user's own
  // accounts are left out of both, so a card payment never counts twice.
  const totals = summarizeTransactions(data ?? [])
  const { moneyOut, moneyIn, net, transfers } = totals

  return (
    <>
      <div className="page-head">
        <h1>Transactions</h1>
        <p className="muted">
          {preset
            ? 'Transactions you confirmed today. Refreshes every few seconds.'
            : 'Filtered transactions. Refreshes every few seconds.'}
        </p>
      </div>

      <div className="stack">
        <FilterBar filters={filters} onChange={changeFilters} />

        {valid && isPending && <p className="state">Loading…</p>}
        {valid && isError && (
          <p className="error" role="alert">
            Could not load transactions: {error.message}
          </p>
        )}

        {valid && data && data.length === 0 && (
          <p className="state">
            {preset
              ? 'Nothing confirmed today yet. Confirm a receipt in Telegram and it will appear.'
              : 'No transactions match these filters.'}
          </p>
        )}

        {valid && data && data.length > 0 && (
          <>
            <div className="stat-row">
              <div className="card">
                <div className="stat-label">Money out</div>
                <div className="stat-value amount-out">
                  {formatAmount(String(moneyOut))}
                </div>
              </div>
              <div className="card">
                <div className="stat-label">Money in</div>
                <div className="stat-value amount-in">
                  {formatAmount(String(moneyIn))}
                </div>
              </div>
              <div className="card">
                <div className="stat-label">Net</div>
                <div className={`stat-value ${net < 0 ? 'amount-negative' : 'amount-in'}`}>
                  {net > 0 ? '+' : net < 0 ? '−' : ''}
                  {formatAmount(String(Math.abs(net)))}
                </div>
              </div>
              {transfers.count > 0 && (
                <div className="card">
                  <div className="stat-label">Between your accounts</div>
                  <div className="stat-value muted-value">
                    {formatAmount(String(transfers.total))}
                  </div>
                  <div className="muted">
                    {transfers.count} not counted as spending or income
                  </div>
                </div>
              )}
              <div className="card">
                <div className="stat-label">Transactions</div>
                <div className="stat-value">{data.length}</div>
              </div>
            </div>

            {notice && (
              <p className="notice" role="status">
                {notice}
              </p>
            )}
            {change.isError && (
              <p className="error" role="alert">
                Could not save the change: {change.error.message}
              </p>
            )}

            {selectedIds.length > 0 && (
              <section className="card bulk-bar" aria-label="Change selected transactions">
                <strong>{selectedIds.length} selected</strong>
                <label>
                  Move to
                  <select
                    value={bulkCategory}
                    onChange={(e) => setBulkCategory(e.target.value)}
                  >
                    <option value="">Keep category</option>
                    {categories.data?.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Mark as
                  <select
                    value={bulkDirection}
                    onChange={(e) =>
                      setBulkDirection(e.target.value as '' | 'in' | 'out')
                    }
                  >
                    <option value="">Keep money in/out</option>
                    <option value="out">↑ Money out</option>
                    <option value="in">↓ Money in</option>
                  </select>
                </label>
                <button
                  type="button"
                  disabled={(!bulkCategory && !bulkDirection) || change.isPending}
                  onClick={() =>
                    apply(selectedIds, {
                      ...(bulkCategory && { category: bulkCategory }),
                      ...(bulkDirection && { direction: bulkDirection }),
                    })
                  }
                >
                  Apply to selected
                </button>
                {sameMerchant.length > 1 && (
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => setSelected(new Set(sameMerchant.map((t) => t.id)))}
                  >
                    Select all {sameMerchant.length} from {only?.merchant}
                  </button>
                )}
                <button
                  type="button"
                  className="link-button"
                  onClick={() => setSelected(new Set())}
                >
                  Clear selection
                </button>
              </section>
            )}

            <div className="card table-wrap">
              <table>
                <thead>
                  <tr>
                    <th className="check-col">
                      <input
                        type="checkbox"
                        aria-label="Select all transactions shown"
                        checked={allSelected}
                        ref={(el) => {
                          if (el) el.indeterminate = selectedIds.length > 0 && !allSelected
                        }}
                        onChange={toggleAll}
                      />
                    </th>
                    <th>Merchant</th>
                    <th>Type</th>
                    <th>Category</th>
                    <th>Card</th>
                    <th>Date</th>
                    <th className="num">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((tx) => (
                    <tr key={tx.id} className={`row-${tx.direction}`}>
                      <td className="check-col">
                        <input
                          type="checkbox"
                          aria-label={`Select ${tx.merchant ?? 'transaction'}`}
                          checked={selected.has(tx.id)}
                          onChange={() => toggle(tx.id)}
                        />
                      </td>
                      <td>
                        {tx.merchant ?? '—'}
                        {tx.description && (
                          <div className="muted">{tx.description}</div>
                        )}
                        {tx.is_transfer && (
                          <div className="muted">Between your accounts · not counted</div>
                        )}
                      </td>
                      <td>
                        <span className={`badge badge-${tx.direction}`}>
                          <span aria-hidden="true">
                            {tx.direction === 'in' ? '↓' : '↑'}
                          </span>
                          {tx.direction === 'in' ? 'Money in' : 'Money out'}
                        </span>
                      </td>
                      <td>{tx.category ?? '—'}</td>
                      <td>{tx.card ?? '—'}</td>
                      <td>{formatDate(tx.occurred_on)}</td>
                      <td className={`num amount-${tx.direction}`}>
                        {formatSigned(tx.amount, tx.direction)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </>
  )
}
