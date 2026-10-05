import { useState } from 'react'
import type { FormEvent } from 'react'
import type { Card } from '../api/types'
import {
  useBanks,
  useCards,
  useCreateBank,
  useCreateCard,
} from '../api/hooks'

interface Row {
  key: string
  bank: string
  card: Card | null
}

function AddBankForm() {
  const [name, setName] = useState('')
  const createBank = useCreateBank()

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return
    createBank.mutate(name.trim(), { onSuccess: () => setName('') })
  }

  return (
    <form onSubmit={submit}>
      <div className="form-row">
        <label>
          Bank name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. BCA"
            maxLength={100}
          />
        </label>
        <button type="submit" disabled={createBank.isPending || !name.trim()}>
          Add bank
        </button>
      </div>
      {createBank.isError && (
        <p className="error" role="alert">
          {createBank.error.message}
        </p>
      )}
    </form>
  )
}

function AddCardForm({ banks }: { banks: { id: number; name: string }[] }) {
  const [bankId, setBankId] = useState('')
  const [name, setName] = useState('')
  const [last4, setLast4] = useState('')
  const createCard = useCreateCard()
  const last4Valid = last4 === '' || /^\d{4}$/.test(last4)
  const ready = bankId !== '' && name.trim() !== '' && last4Valid

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!ready) return
    createCard.mutate(
      { bankId: Number(bankId), name: name.trim(), last4: last4 || null },
      {
        onSuccess: () => {
          setName('')
          setLast4('')
        },
      },
    )
  }

  if (banks.length === 0) {
    return <p className="muted">Add a bank first, then you can add cards to it.</p>
  }

  return (
    <form onSubmit={submit}>
      <div className="form-row">
        <label>
          Bank
          <select value={bankId} onChange={(e) => setBankId(e.target.value)}>
            <option value="">Select a bank</option>
            {banks.map((bank) => (
              <option key={bank.id} value={bank.id}>
                {bank.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Card name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Visa"
            maxLength={100}
          />
        </label>
        <label>
          Last 4 digits (optional)
          <input
            value={last4}
            onChange={(e) => setLast4(e.target.value)}
            placeholder="1234"
            inputMode="numeric"
            maxLength={4}
          />
        </label>
        <button type="submit" disabled={createCard.isPending || !ready}>
          Add card
        </button>
      </div>
      {!last4Valid && (
        <p className="error">Enter exactly four digits, or leave blank.</p>
      )}
      {createCard.isError && (
        <p className="error" role="alert">
          {createCard.error.message}
        </p>
      )}
    </form>
  )
}

export function Settings() {
  const banks = useBanks()
  const cards = useCards()

  // One row per card; a bank with no cards still gets a row so it is visible.
  const rows: Row[] =
    banks.data?.flatMap((bank): Row[] => {
      const own = cards.data?.filter((card) => card.bank_id === bank.id) ?? []
      return own.length > 0
        ? own.map((card) => ({ key: `c${card.id}`, bank: bank.name, card }))
        : [{ key: `b${bank.id}`, bank: bank.name, card: null }]
    }) ?? []

  return (
    <>
      <div className="page-head">
        <h1>Banks &amp; cards</h1>
        <p className="muted">
          pfa matches receipts to these cards. Add each bank, then the cards under it.
        </p>
      </div>

      <div className="stack">
        {(banks.isPending || cards.isPending) && <p className="state">Loading…</p>}
        {(banks.isError || cards.isError) && (
          <p className="error" role="alert">
            Could not load banks and cards.
          </p>
        )}

        {banks.data && cards.data && (
          <div className="card table-wrap">
            {rows.length === 0 ? (
              <p className="state">No banks yet. Add your first one below.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Bank</th>
                    <th>Card</th>
                    <th className="num">Last 4</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ key, bank, card }) => (
                    <tr key={key}>
                      <td>{bank}</td>
                      <td>{card ? card.name : <span className="muted">No cards yet</span>}</td>
                      <td className="num">{card?.last4 ? `•••• ${card.last4}` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        <section className="card">
          <h2>Add a bank</h2>
          <AddBankForm />
        </section>

        <section className="card">
          <h2>Add a card</h2>
          <AddCardForm banks={banks.data ?? []} />
        </section>
      </div>
    </>
  )
}
