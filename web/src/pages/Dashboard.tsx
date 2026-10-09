import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useAnalytics } from '../api/hooks'
import type { Analytics, CategoryShare, PeriodName } from '../api/types'
import {
  CHART_COLORS,
  PERIODS,
  addDaysIso,
  bucketLabel,
  categoryLink,
  transfersLink,
  describeChange,
  parsePeriod,
  periodLabel,
} from '../dashboard'
import { formatAmount } from '../format'

const COMPACT = new Intl.NumberFormat(undefined, {
  notation: 'compact',
  maximumFractionDigits: 1,
})

// More money out is bad news and more money in is good news; the arrow and the words
// say so as well, so the colour is never the only signal.
function ChangeNote({
  change,
  kind,
  period,
}: {
  change: number | null
  kind: 'out' | 'in'
  period: PeriodName
}) {
  const { text, direction } = describeChange(change)
  const arrow = { up: '▲', down: '▼', flat: '–', none: '' }[direction]
  const tone =
    direction === 'up' ? (kind === 'out' ? 'bad' : 'good')
    : direction === 'down' ? (kind === 'out' ? 'good' : 'bad')
    : 'neutral'
  const wording =
    direction === 'none'
      ? `Nothing recorded in the previous ${period} to compare with`
      : direction === 'flat'
        ? `Same as the previous ${period}`
        : `${text} ${direction === 'up' ? 'more' : 'less'} than the previous ${period}`
  return (
    <div className={`change change-${tone}`}>
      {arrow && <span aria-hidden="true">{arrow} </span>}
      {wording}
    </div>
  )
}

function percent(share: number): string {
  const whole = share * 100
  return whole > 0 && whole < 1 ? '<1%' : `${Math.round(whole)}%`
}

function Breakdown({
  title,
  rows,
  direction,
  data,
}: {
  title: string
  rows: CategoryShare[]
  direction: 'in' | 'out'
  data: Analytics
}) {
  return (
    <section className="card">
      <h2>{title}</h2>
      {rows.length === 0 ? (
        <p className="muted">Nothing here for this period.</p>
      ) : (
        <ul className="breakdown">
          {rows.map((row) => {
            const link = categoryLink(data.start, data.end, row.category, direction)
            return (
              <li key={row.category}>
                <div className="breakdown-head">
                  {link ? <Link to={link}>{row.category}</Link> : <span>{row.category}</span>}
                  <span>
                    {formatAmount(row.total)} <span className="muted">· {percent(row.share)}</span>
                  </span>
                </div>
                <div
                  className="bar-track"
                  role="img"
                  aria-label={`${row.category}: ${percent(row.share)} of money ${direction}`}
                >
                  <div
                    className={`bar-fill bar-${direction}`}
                    style={{ width: `${Math.max(row.share * 100, 2)}%` }}
                  />
                </div>
                <div className="muted">
                  {row.count} {row.count === 1 ? 'transaction' : 'transactions'}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

type ChartSide = 'out' | 'in' | 'both'

const SIDES: { value: ChartSide; label: string }[] = [
  { value: 'out', label: 'Money out' },
  { value: 'in', label: 'Money in' },
  { value: 'both', label: 'Both' },
]

function SeriesChart({ data }: { data: Analytics }) {
  // One side at a time keeps spending readable (a single salary would flatten a month
  // of it); "Both" puts them side by side for the whole picture.
  const [side, setSide] = useState<ChartSide>('out')
  if (data.bucket === null) return null
  const bucket = data.bucket
  const points = data.series.map((p) => ({
    start: p.start,
    label: bucketLabel(p.start, bucket),
    out: Number(p.money_out),
    in: Number(p.money_in),
  }))
  const unit = { day: 'day', week: 'week', month: 'month' }[bucket]
  const title =
    side === 'out' ? 'Money out' : side === 'in' ? 'Money in' : 'Money out and money in'
  return (
    <section className="card">
      <div className="chart-head">
        <h2>
          {title} by {unit}
        </h2>
        <div className="period-tabs" role="group" aria-label="Which side to chart">
          {SIDES.map((option) => (
            <button
              key={option.value}
              type="button"
              className={option.value === side ? undefined : 'secondary-button'}
              aria-pressed={option.value === side}
              onClick={() => setSide(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      {side === 'both' && (
        <p className="muted">
          Money in is often much larger than money out, which makes the smaller bars hard to
          see. Use Money out or Money in to read one side closely.
        </p>
      )}
      <div style={{ width: '100%', height: 280 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" minTickGap={8} tickLine={false} />
            <YAxis width={56} tickFormatter={(v: number) => COMPACT.format(v)} tickLine={false} />
            <Tooltip formatter={(value) => formatAmount(String(value))} />
            {side !== 'in' && (
              <Bar dataKey="out" name="Money out" fill={CHART_COLORS.out} radius={[3, 3, 0, 0]} />
            )}
            {side !== 'out' && (
              <Bar dataKey="in" name="Money in" fill={CHART_COLORS.in} radius={[3, 3, 0, 0]} />
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>
      {side === 'both' && (
        <ul className="legend" aria-label="Legend">
          <li>
            <span className="swatch swatch-out" aria-hidden="true" />
            Money out
          </li>
          <li>
            <span className="swatch swatch-in" aria-hidden="true" />
            Money in
          </li>
        </ul>
      )}
      <details>
        <summary>View both as a table</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{bucket === 'day' ? 'Day' : bucket === 'week' ? 'Week from' : 'Month'}</th>
                <th className="num">Money out</th>
                <th className="num">Money in</th>
              </tr>
            </thead>
            <tbody>
              {data.series.map((p) => (
                <tr key={p.start}>
                  <td>{p.start}</td>
                  <td className="num">{formatAmount(p.money_out)}</td>
                  <td className="num">{formatAmount(p.money_in)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  )
}

export function Dashboard() {
  const [params, setParams] = useSearchParams()
  const period = parsePeriod(params.get('period'))
  const date = params.get('date')
  const { data, isPending, isError, error } = useAnalytics(period, date)

  // Leaving the date out means "today", so the view moves on by itself.
  function go(next: { period?: PeriodName; date?: string | null }) {
    const target = new URLSearchParams()
    target.set('period', next.period ?? period)
    const nextDate = next.date === undefined ? date : next.date
    if (nextDate) target.set('date', nextDate)
    setParams(target, { replace: true })
  }

  const empty =
    data !== undefined &&
    data.money_out.count === 0 &&
    data.money_in.count === 0 &&
    data.transfers.count === 0
  const net = data ? Number(data.net) : 0

  return (
    <>
      <div className="page-head">
        <h1>Dashboard</h1>
        <p className="muted">
          {data ? periodLabel(data.period, data.start, data.end) : 'Loading'}. Moves between
          your own accounts are not counted. Refreshes every few seconds.
        </p>
      </div>

      <div className="stack">
        <section className="card dash-toolbar" aria-label="Choose a period">
          <div className="period-tabs">
            {PERIODS.map((p) => (
              <button
                key={p.value}
                type="button"
                className={p.value === period ? undefined : 'secondary-button'}
                aria-pressed={p.value === period}
                onClick={() => go({ period: p.value })}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="period-nav">
            <button
              type="button"
              className="secondary-button"
              aria-label={`Previous ${period}`}
              disabled={!data}
              onClick={() => data && go({ date: data.previous.start })}
            >
              ‹
            </button>
            <span className="period-label" aria-live="polite">
              {data ? periodLabel(data.period, data.start, data.end) : '…'}
            </span>
            <button
              type="button"
              className="secondary-button"
              aria-label={`Next ${period}`}
              disabled={!data}
              onClick={() => data && go({ date: addDaysIso(data.end, 1) })}
            >
              ›
            </button>
            <button
              type="button"
              className="text-button"
              disabled={date === null}
              onClick={() => go({ date: null })}
            >
              This {period}
            </button>
          </div>
        </section>

        {isPending && <p className="state">Loading…</p>}
        {isError && (
          <p className="error" role="alert">
            Could not load the dashboard: {error.message}
          </p>
        )}

        {data && (
          <>
            <div className="stat-row">
              <div className="card">
                <div className="stat-label">Money out</div>
                <div className="stat-value amount-out">{formatAmount(data.money_out.total)}</div>
                <ChangeNote
                  change={data.previous.money_out_change}
                  kind="out"
                  period={data.period}
                />
              </div>
              <div className="card">
                <div className="stat-label">Money in</div>
                <div className="stat-value amount-in">{formatAmount(data.money_in.total)}</div>
                <ChangeNote
                  change={data.previous.money_in_change}
                  kind="in"
                  period={data.period}
                />
              </div>
              <div className="card">
                <div className="stat-label">Net</div>
                <div className={`stat-value ${net < 0 ? 'amount-negative' : 'amount-in'}`}>
                  {net > 0 ? '+' : net < 0 ? '−' : ''}
                  {formatAmount(String(Math.abs(net)))}
                </div>
                <div className="muted">money in minus out</div>
              </div>
              {data.transfers.count > 0 && (
                <div className="card">
                  <div className="stat-label">Between accounts</div>
                  <div className="stat-value muted-value">{formatAmount(data.transfers.total)}</div>
                  <div className="muted">
                    {data.transfers.count} not counted ·{' '}
                    <Link to={transfersLink(data.start, data.end)}>Review</Link>
                  </div>
                </div>
              )}
            </div>

            {empty ? (
              <p className="state">
                Nothing recorded for this period yet. Confirm a receipt or a statement in
                Telegram and it will appear here.
              </p>
            ) : (
              <>
                <SeriesChart data={data} />
                <div className="two-col">
                  <Breakdown
                    title="Where the money went"
                    rows={data.out_by_category}
                    direction="out"
                    data={data}
                  />
                  <Breakdown
                    title="Where it came from"
                    rows={data.in_by_category}
                    direction="in"
                    data={data}
                  />
                </div>
              </>
            )}
          </>
        )}
      </div>
    </>
  )
}
