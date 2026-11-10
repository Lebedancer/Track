import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { Empty, ErrorBox, Loading } from '../ui'

export default function DataQualityPage() {
  const dq = useQuery({ queryKey: ['data-quality'], queryFn: api.dataQuality })
  const [code, setCode] = useState<string | null>(null)

  if (dq.isPending) return <Loading />
  if (dq.isError) return <ErrorBox error={dq.error} />
  const issues = code ? dq.data.issues.filter((i) => i.code === code) : dq.data.issues

  return (
    <>
      <h1>Data quality</h1>
      <p className="muted">
        Findings from importing the source CSVs. Errors are rows that were skipped; warnings were auto-resolved; info notes
        shapes of the data the app handles explicitly.
      </p>
      {dq.data.summary.length === 0 ? (
        <Empty>No issues found.</Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Code</th>
              <th>Severity</th>
              <th className="num">Count</th>
            </tr>
          </thead>
          <tbody>
            {dq.data.summary.map((s) => (
              <tr key={`${s.code}/${s.severity}`} className={code === s.code ? 'row-current' : ''}>
                <td>
                  <button className="link" onClick={() => setCode(code === s.code ? null : s.code)}>
                    {s.code}
                  </button>
                </td>
                <td>
                  <span className={`sev sev-${s.severity}`}>{s.severity}</span>
                </td>
                <td className="num">{s.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {issues.length > 0 && (
        <section>
          <h2>{code ? `Issues: ${code}` : 'All issues'}</h2>
          <table>
            <thead>
              <tr>
                <th>Severity</th>
                <th>Entity</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {issues.map((i, idx) => (
                <tr key={idx}>
                  <td>
                    <span className={`sev sev-${i.severity}`}>{i.severity}</span>
                  </td>
                  <td className="id">
                    {i.entity}
                    {i.entity_id && ` / ${i.entity_id}`}
                  </td>
                  <td>{i.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  )
}
