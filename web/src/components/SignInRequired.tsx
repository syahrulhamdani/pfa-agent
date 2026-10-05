export function SignInRequired({ message }: { message?: string }) {
  return (
    <main className="page centered">
      <div className="card narrow">
        <div className="brand-lockup">
          pfa<span>.</span>
        </div>
        <h1>Sign in required</h1>
        <p>
          Open Telegram and send <strong>/login</strong> to pfa. It replies with a
          sign-in link. Each link works once and expires after a few minutes.
        </p>
        {message && <p className="error">{message}</p>}
      </div>
    </main>
  )
}
