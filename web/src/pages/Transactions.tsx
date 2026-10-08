import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useCategories, useChangeCategory, useTransactions } from '../api/hooks'
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
  const changeCategory = useChangeCategory()

  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [bulkCategory, setBulkCategory] = useState('')
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

  function moveTo(ids: number[], category: string) {
    setNotice(null)
    changeCategory.mutate(
      { ids, category },
      {
        onSuccess: (result) => {
          const noun = result.updated === 1 ? 'transaction' : 'transactions'
          setNotice(`Moved ${result.updated} ${noun} to ${category}.`)
          setSelected(new Set())
          setBulkCategory('')
        },
      },
    )
  }

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
                <div className="stat-value">{formatAmount(String(moneyOut))}</div>
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
            {changeCategory.isError && (
              <p className="error" role="alert">
                Could not change the category: {changeCategory.error.message}
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
                    <option value="">Choose a category</option>
                    {categories.data?.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  disabled={!bulkCategory || changeCategory.isPending}
                  onClick={() => moveTo(selectedIds, bulkCategory)}
                >
                  Change category
                </button>
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
                    <tr key={tx.id}>
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
                          {tx.direction === 'in' ? 'In' : 'Out'}
                        </span>
                      </td>
                      <td>
                        <select
                          className="table-select"
                          aria-label={`Category for ${tx.merchant ?? 'transaction'}`}
                          value={tx.category ?? ''}
                          disabled={changeCategory.isPending}
                          onChange={(e) => moveTo([tx.id], e.target.value)}
                        >
                          {tx.category === null && <option value="">No category</option>}
                          {categories.data?.map((name) => (
                            <option key={name} value={name}>
                              {name}
                            </option>
                          ))}
                        </select>
                      </td>
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
