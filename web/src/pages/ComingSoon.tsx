export function ComingSoon({ title }: { title: string }) {
  return (
    <>
      <div className="page-head">
        <h1>{title}</h1>
      </div>
      <p className="state">This section arrives in a later step of the build.</p>
    </>
  )
}
