import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  useBanks,
  useCards,
  useCreateBank,
  useCreateCard,
} from '../api/hooks'

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

function AddCardForm({ bankId }: { bankId: number }) {
  const [name, setName] = useState('')
  const [last4, setLast4] = useState('')
  const createCard = useCreateCard()
  const last4Valid = last4 === '' || /^\d{4}$/.test(last4)

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim() || !last4Valid) return
    createCard.mutate(
      { bankId, name: name.trim(), last4: last4 || null },
      {
        onSuccess: () => {
          setName('')
          setLast4('')
        },
      },
    )
  }

  return (
    <form onSubmit={submit}>
      <div className="form-row">
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
        <button
          type="submit"
          disabled={createCard.isPending || !name.trim() || !last4Valid}
        >
          Add card
        </button>
      </div>
      {!last4Valid && <p className="error">Enter exactly four digits, or leave blank.</p>}
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

  return (
    <>
      <div className="page-head">
        <h1>Banks &amp; cards</h1>
        <p className="muted">
          pfa matches receipts to these cards. Add each bank, then the cards under it.
        </p>
      </div>

      <div className="stack">
        <section className="card">
          <h2>Add a bank</h2>
          <AddBankForm />
        </section>

        {(banks.isPending || cards.isPending) && <p className="state">Loading…</p>}
        {(banks.isError || cards.isError) && (
          <p className="error" role="alert">
            Could not load banks and cards.
          </p>
        )}
        {banks.data?.length === 0 && (
          <p className="state">No banks yet. Add your first one above.</p>
        )}

        {banks.data?.map((bank) => {
          const bankCards = cards.data?.filter((c) => c.bank_id === bank.id) ?? []
          return (
            <section className="card" key={bank.id}>
              <h2>{bank.name}</h2>
              {bankCards.length === 0 ? (
                <p className="muted">No cards under this bank yet.</p>
              ) : (
                <ul className="cards-list">
                  {bankCards.map((card) => (
                    <li key={card.id}>
                      {card.name}
                      {card.last4 && <span className="muted"> · •••• {card.last4}</span>}
                    </li>
                  ))}
                </ul>
              )}
              <div style={{ marginTop: 16 }}>
                <AddCardForm bankId={bank.id} />
              </div>
            </section>
          )
        })}
      </div>
    </>
  )
}
