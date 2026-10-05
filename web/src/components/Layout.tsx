import { useQueryClient } from '@tanstack/react-query'
import { NavLink, Outlet } from 'react-router-dom'
import { useLogout } from '../api/hooks'

const LINKS = [
  { to: '/transactions', label: 'Transactions' },
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/budgets', label: 'Budgets' },
  { to: '/goals', label: 'Goals' },
  { to: '/settings', label: 'Banks & cards' },
]

export function Layout() {
  const logout = useLogout()
  const queryClient = useQueryClient()

  function signOut() {
    logout.mutate(undefined, {
      // Re-check the session so the gate shows the sign-in screen at once.
      onSettled: () => void queryClient.invalidateQueries({ queryKey: ['auth'] }),
    })
  }

  return (
    <>
      <header className="header">
        <div className="header-inner">
          <NavLink to="/" className="brand" aria-label="pfa home">
            pfa<span>.</span>
          </NavLink>
          <nav className="nav" aria-label="Main">
            {LINKS.map((link) => (
              <NavLink key={link.to} to={link.to}>
                {link.label}
              </NavLink>
            ))}
          </nav>
          <button type="button" className="link-button" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  )
}
