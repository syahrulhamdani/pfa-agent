import { useSearchParams } from 'react-router-dom'
import { useTransactions } from '../api/hooks'
import { FilterBar } from '../components/FilterBar'
import { isPreset, parseFilters, toSearchParams } from '../filters'
import type { Filters } from '../filters'
import { formatAmount, formatDate } from '../format'

export function Transactions() {
  const [params, setParams] = useSearchParams()
  const filters = parseFilters(params)
  const preset = isPreset(filters)
  const { data, isPending, isError, error } = useTransactions(filters)

  function changeFilters(next: Filters) {
    setParams(toSearchParams(next), { replace: true })
  }

  const total =
    data?.reduce((sum, tx) => sum + Number(tx.amount ?? 0), 0).toString() ?? null

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

        {isPending && <p className="state">Loading…</p>}
        {isError && (
          <p className="error" role="alert">
            Could not load transactions: {error.message}
          </p>
        )}

        {data && data.length === 0 && (
          <p className="state">
            {preset
              ? 'Nothing confirmed today yet. Confirm a receipt in Telegram and it will appear.'
              : 'No transactions match these filters.'}
          </p>
        )}

        {data && data.length > 0 && (
          <>
            <div className="stat-row">
              <div className="card">
                <div className="stat-label">{preset ? 'Spent today' : 'Total'}</div>
                <div className="stat-value">{formatAmount(total)}</div>
              </div>
              <div className="card">
                <div className="stat-label">Transactions</div>
                <div className="stat-value">{data.length}</div>
              </div>
            </div>

            <div className="card table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Merchant</th>
                    <th>Category</th>
                    <th>Card</th>
                    <th>Date</th>
                    <th className="num">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((tx) => (
                    <tr key={tx.id}>
                      <td>
                        {tx.merchant ?? '—'}
                        {tx.description && (
                          <div className="muted">{tx.description}</div>
                        )}
                      </td>
                      <td>{tx.category ?? '—'}</td>
                      <td>{tx.card ?? '—'}</td>
                      <td>{formatDate(tx.occurred_on)}</td>
                      <td className="num">{formatAmount(tx.amount)}</td>
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
