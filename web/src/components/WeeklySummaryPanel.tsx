import { Link } from 'react-router-dom'
import { useSummary } from '../api/hooks'
import type { WeeklySummary } from '../api/types'
import { describeChange } from '../dashboard'
import { formatAmount } from '../format'

function changeWords(change: number | null, unit: string): string {
  const { text, direction } = describeChange(change)
  if (direction === 'none') return `nothing recorded the previous ${unit} to compare with`
  if (direction === 'flat') return `the same as the previous ${unit}`
  return `${text} ${direction === 'up' ? 'more' : 'less'} than the previous ${unit}`
}

function SummaryBody({ summary }: { summary: WeeklySummary }) {
  const { facts } = summary
  const net = Number(facts.net)
  return (
    <>
      <div className="chart-head">
        <h2>{facts.partial ? 'This week so far' : 'Last week'}</h2>
        <span className="muted">{facts.label}</span>
      </div>
      <p>
        <strong className="amount-out">{formatAmount(facts.money_out)}</strong> money out (
        {facts.out_count} {facts.out_count === 1 ? 'transaction' : 'transactions'},{' '}
        {changeWords(facts.money_out_change, 'week')}) ·{' '}
        <strong className="amount-in">{formatAmount(facts.money_in)}</strong> money in · net{' '}
        <strong className={net < 0 ? 'amount-negative' : 'amount-in'}>
          {net > 0 ? '+' : net < 0 ? '−' : ''}
          {formatAmount(String(Math.abs(net)))}
        </strong>
      </p>
      {facts.transfers.count > 0 && (
        <p className="muted">
          Not counted: {facts.transfers.count}{' '}
          {facts.transfers.count === 1 ? 'move' : 'moves'} between your own accounts,{' '}
          {formatAmount(facts.transfers.total)}.
        </p>
      )}
      {facts.top_out.length > 0 && (
        <p>
          <strong>Top spending:</strong>{' '}
          {facts.top_out
            .slice(0, 3)
            .map((c) => `${c.category} ${formatAmount(c.total)} (${Math.round(c.share * 100)}%)`)
            .join(', ')}
        </p>
      )}
      {facts.flags.length > 0 && (
        <p>
          <strong>Budgets to watch:</strong>{' '}
          {facts.flags
            .map((b) =>
              Number(b.remaining) < 0
                ? `${b.category} is over budget by ${formatAmount(String(-Number(b.remaining)))}`
                : `${b.category} has ${formatAmount(b.remaining)} left`,
            )
            .join('; ')}
          . <Link to="/budgets">Open budgets</Link>
        </p>
      )}
      <h3>What I&apos;d do</h3>
      <ul className="advice">
        {summary.recommendations.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <p className="muted">
        Written {new Date(summary.created_at).toLocaleString()}. Figures come from your
        confirmed transactions; moves between your own accounts are left out.
      </p>
    </>
  )
}

// Last week's summary, as it was sent to Telegram. Nothing here when there is none yet.
export function WeeklySummaryPanel() {
  const { data, isError } = useSummary()
  if (isError) return null
  if (data === undefined) return null
  if (data === null) {
    return (
      <section className="card">
        <h2>Weekly summary</h2>
        <p className="muted">
          Your first summary will arrive on Monday morning, and it will appear here too. It
          covers the week that just ended: what you spent, what came in, and how your
          budgets and goals are doing.
        </p>
      </section>
    )
  }
  return (
    <section className="card">
      <SummaryBody summary={data} />
    </section>
  )
}
