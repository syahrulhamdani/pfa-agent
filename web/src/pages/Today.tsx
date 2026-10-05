import { useTodayTransactions } from '../api/hooks'
import { formatAmount, formatDate } from '../format'

export function Today() {
  const { data, isPending, isError, error } = useTodayTransactions()

  const total =
    data?.reduce((sum, tx) => sum + Number(tx.amount ?? 0), 0).toString() ?? null

  return (
    <>
      <div className="page-head">
        <h1>Today's transactions</h1>
        <p className="muted">
          Transactions you confirmed today. This page refreshes every few seconds.
        </p>
      </div>

      {isPending && <p className="state">Loading…</p>}
      {isError && (
        <p className="error" role="alert">
          Could not load transactions: {error.message}
        </p>
      )}

      {data && data.length === 0 && (
        <p className="state">
          Nothing here yet. Confirm a receipt in Telegram and it will appear.
        </p>
      )}

      {data && data.length > 0 && (
        <>
          <div className="stat-row">
            <div className="card">
              <div className="stat-label">Spent today</div>
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
    </>
  )
}
