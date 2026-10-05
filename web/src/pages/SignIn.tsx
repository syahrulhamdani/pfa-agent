import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { exchangeToken, safeNextPath } from '../api/auth'
import { SignInRequired } from '../components/SignInRequired'

// The link from Telegram lands here. The token is exchanged by this page's script
// (a POST), so a link-preview bot that only fetches the URL cannot use it up.
export function SignIn() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  const token = params.get('token')
  const next = safeNextPath(params.get('next'))

  useEffect(() => {
    if (!token) return
    // Take the credential out of the address bar and browser history right away.
    window.history.replaceState(null, '', '/auth')
    exchangeToken(token)
      .then(() => {
        queryClient.setQueryData(['auth', 'me'], { authenticated: true })
        navigate(next, { replace: true })
      })
      .catch((e: Error) => setError(e.message))
  }, [token, next, navigate, queryClient])

  if (!token) return <SignInRequired message="This page needs a sign-in link from Telegram." />
  if (error) return <SignInRequired message={error} />
  return (
    <main className="page centered">
      <p className="state">Signing you in…</p>
    </main>
  )
}
