import { useSearchParams } from 'react-router-dom'
import { useTransactions } from '../api/hooks'
import { FilterBar } from '../components/FilterBar'
import { filterProblems, isPreset, parseFilters, toSearchParams } from '../filters'
import type { Filters } from '../filters'
import { formatAmount, formatDate, formatSigned } from '../format'

export function Transactions() {
  const [params, setParams] = useSearchParams()
  const filters = parseFilters(params)
  const preset = isPreset(filters)
  const valid = filterProblems(filters).length === 0
  // Nothing is sent while the filters are invalid; the filter bar says what to fix.
  const { data, isPending, isError, error } = useTransactions(filters, valid)

  function changeFilters(next: Filters) {
    setParams(toSearchParams(next), { replace: true })
  }

  // Money out and money in are added up apart, so an expense never hides income.
  const sumOf = (direction: 'in' | 'out') =>
    data
      ?.filter((tx) => tx.direction === direction)
      .reduce((sum, tx) => sum + Number(tx.amount ?? 0), 0) ?? 0
  const moneyOut = sumOf('out')
  const moneyIn = sumOf('in')
  const net = moneyIn - moneyOut

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
                      <td>
                        {tx.merchant ?? '—'}
                        {tx.description && (
                          <div className="muted">{tx.description}</div>
                        )}
                      </td>
                      <td>
                        <span className={`badge badge-${tx.direction}`}>
                          {tx.direction === 'in' ? 'In' : 'Out'}
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
