import { NavLink, Outlet } from 'react-router-dom'

const LINKS = [
  { to: '/transactions/today', label: "Today's transactions" },
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/budgets', label: 'Budgets' },
  { to: '/goals', label: 'Goals' },
  { to: '/settings', label: 'Banks & cards' },
]

export function Layout() {
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
        </div>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </>
  )
}
