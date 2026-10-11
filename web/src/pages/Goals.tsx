import { useState } from 'react'
import type { FormEvent } from 'react'
import { useCreateGoal, useDeleteGoal, useGoals, useUpdateGoal } from '../api/hooks'
import type { Goal } from '../api/types'
import { barWidth, goalStatus, percentUsed } from '../budgets'
import { formatAmount, formatDate } from '../format'

function AddGoalForm() {
  const [name, setName] = useState('')
  const [target, setTarget] = useState('')
  const [date, setDate] = useState('')
  const [saved, setSaved] = useState('')
  const createGoal = useCreateGoal()

  function submit(event: FormEvent) {
    event.preventDefault()
    createGoal.mutate(
      {
        name: name.trim(),
        target_amount: target,
        target_date: date,
        ...(saved && { saved_amount: saved }),
      },
      {
        onSuccess: () => {
          setName('')
          setTarget('')
          setDate('')
          setSaved('')
        },
      },
    )
  }

  return (
    <form onSubmit={submit}>
      <div className="form-row">
        <label>
          Goal
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Trip to Japan"
            maxLength={100}
          />
        </label>
        <label>
          Target amount
          <input
            type="number"
            min="0.01"
            step="0.01"
            inputMode="decimal"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="e.g. 25000000"
          />
        </label>
        <label>
          Target date
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label>
          Already saved (optional)
          <input
            type="number"
            min="0"
            step="0.01"
            inputMode="decimal"
            value={saved}
            onChange={(e) => setSaved(e.target.value)}
          />
        </label>
        <button
          type="submit"
          disabled={createGoal.isPending || !name.trim() || !target || !date}
        >
          Add goal
        </button>
      </div>
      {createGoal.isError && (
        <p className="error" role="alert">
          {createGoal.error.message}
        </p>
      )}
    </form>
  )
}

function GoalCard({ goal }: { goal: Goal }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(goal.name)
  const [target, setTarget] = useState(goal.target_amount)
  const [date, setDate] = useState(goal.target_date)
  const [saved, setSaved] = useState(goal.saved_amount)
  const update = useUpdateGoal()
  const remove = useDeleteGoal()
  const reached = goal.progress >= 1

  function open() {
    setName(goal.name)
    setTarget(goal.target_amount)
    setDate(goal.target_date)
    setSaved(goal.saved_amount)
    setEditing(true)
  }

  function save(event: FormEvent) {
    event.preventDefault()
    update.mutate(
      { id: goal.id, name: name.trim(), target_amount: target, target_date: date, saved_amount: saved },
      { onSuccess: () => setEditing(false) },
    )
  }

  function confirmDelete() {
    if (window.confirm(`Delete the goal “${goal.name}”? This cannot be undone.`)) {
      remove.mutate(goal.id)
    }
  }

  return (
    <section className="card goal">
      {editing ? (
        <form onSubmit={save}>
          <div className="form-row">
            <label>
              Goal
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} />
            </label>
            <label>
              Target amount
              <input
                type="number"
                min="0.01"
                step="0.01"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
              />
            </label>
            <label>
              Target date
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </label>
            <label>
              Saved so far
              <input
                type="number"
                min="0"
                step="0.01"
                value={saved}
                onChange={(e) => setSaved(e.target.value)}
              />
            </label>
          </div>
          <div className="form-row">
            <button type="submit" disabled={update.isPending || !name.trim() || !target || !date || saved === ''}>
              Save changes
            </button>
            <button
              type="button"
              className="link-button"
              onClick={() => {
                setEditing(false)
                update.reset()
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          <div className="goal-head">
            <h2>{goal.name}</h2>
            <span className={reached ? 'goal-reached' : 'muted'}>
              {goalStatus(goal.days_left, goal.progress)}
            </span>
          </div>
          <p>
            <strong>{formatAmount(goal.saved_amount)}</strong> saved of{' '}
            {formatAmount(goal.target_amount)} · {percentUsed(goal.progress)}
          </p>
          <div className="bar-track" role="img" aria-label={`${percentUsed(goal.progress)} saved`}>
            <div className="bar-fill bar-in" style={{ width: barWidth(goal.progress) }} />
          </div>
          <p className="muted">
            {reached
              ? `Target ${formatAmount(goal.target_amount)} reached`
              : `${formatAmount(goal.remaining)} to go`}{' '}
            · by {formatDate(goal.target_date)}
          </p>
          <div className="form-row">
            <button type="button" className="text-button" onClick={open}>
              Edit or update saved amount
            </button>
            <button
              type="button"
              className="link-button"
              onClick={confirmDelete}
              disabled={remove.isPending}
            >
              Delete
            </button>
          </div>
        </>
      )}
      {(update.isError || remove.isError) && (
        <p className="error" role="alert">
          {update.error?.message ?? remove.error?.message}
        </p>
      )}
    </section>
  )
}

export function Goals() {
  const { data, isPending, isError, error } = useGoals()
  return (
    <>
      <div className="page-head">
        <h1>Goals</h1>
        <p className="muted">
          Progress is the amount you have saved against the target. Update the saved
          amount whenever you set money aside.
        </p>
      </div>

      <div className="stack">
      {isPending && <p className="state">Loading…</p>}
      {isError && (
        <p className="state error" role="alert">
          Could not load goals: {error.message}
        </p>
      )}
      {data && data.length === 0 && (
        <p className="state">No goals yet. Add one below.</p>
      )}
      {data?.map((goal) => <GoalCard key={goal.id} goal={goal} />)}

      <section className="card">
        <h2>Add a goal</h2>
        <AddGoalForm />
      </section>
      </div>
    </>
  )
}
