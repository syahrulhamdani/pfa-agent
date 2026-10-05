import { Outlet } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useSession } from '../api/hooks'
import { SignInRequired } from './SignInRequired'

// Everything except /auth sits behind this gate.
export function RequireAuth() {
  const session = useSession()

  if (session.isPending) {
    return (
      <main className="page centered">
        <p className="state">Checking your session…</p>
      </main>
    )
  }
  if (session.isError) {
    const unauthorized = session.error instanceof ApiError && session.error.status === 401
    return (
      <SignInRequired
        message={unauthorized ? undefined : `Could not reach pfa: ${session.error.message}`}
      />
    )
  }
  return <Outlet />
}
