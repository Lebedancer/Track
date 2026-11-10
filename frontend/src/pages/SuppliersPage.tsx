import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { Empty, ErrorBox, FLink, Loading } from '../ui'

export default function SuppliersPage({ finisherId }: { finisherId: string }) {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const onlyMine = params.get('mine') === '1'
  const onlyFlagged = params.get('flagged') === '1'

  const suppliers = useQuery({
    queryKey: ['suppliers', finisherId, { q, onlyFlagged }],
    queryFn: () => api.suppliers({ finisher_id: finisherId, q, flagged: onlyFlagged ? true : undefined }),
    placeholderData: (prev) => prev,
  })

  const set = (k: string, v: string | null) => {
    const next = new URLSearchParams(params)
    if (v) next.set(k, v)
    else next.delete(k)
    setParams(next, { replace: true })
  }

  const rows = (suppliers.data ?? [])
    .filter((s) => !onlyMine || s.toy_count > 0)
    .sort(
      (a, b) =>
        Number(!!b.active_flag) - Number(!!a.active_flag) ||
        b.affected_toy_count - a.affected_toy_count ||
        b.toy_count - a.toy_count ||
        a.id.localeCompare(b.id),
    )

  return (
    <>
      <h1>Suppliers</h1>
      <div className="toolbar">
        <input type="search" placeholder="Search by name or id…" value={q} onChange={(e) => set('q', e.target.value || null)} />
        <label className="toggle">
          <input type="checkbox" checked={onlyMine} onChange={(e) => set('mine', e.target.checked ? '1' : null)} /> Only in my supply chain
        </label>
        <label className="toggle">
          <input type="checkbox" checked={onlyFlagged} onChange={(e) => set('flagged', e.target.checked ? '1' : null)} /> Only flagged
        </label>
      </div>

      {suppliers.isPending && <Loading />}
      {suppliers.isError && <ErrorBox error={suppliers.error} />}
      {suppliers.data && rows.length === 0 && <Empty>No suppliers match.</Empty>}
      {rows.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Supplier</th>
              <th>HQ</th>
              <th className="num">Factories</th>
              <th className="num">Parts</th>
              <th className="num">Your toys using</th>
              <th className="num">Your toys affected</th>
              <th>Flag</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} className={s.active_flag ? 'row-flagged' : ''}>
                <td>
                  <FLink to={`/suppliers/${s.id}`}>{s.name}</FLink> <span className="id">{s.id}</span>
                </td>
                <td>{s.hq_country ?? '—'}</td>
                <td className="num">{s.factory_count}</td>
                <td className="num">{s.part_count}</td>
                <td className="num">{s.toy_count}</td>
                <td className="num">{s.affected_toy_count || '—'}</td>
                <td>
                  {s.active_flag ? (
                    <span className="badge badge-flagged">
                      {s.active_flag.scope === 'supplier' ? 'Flagged' : `Flagged · ${s.active_flag.factory_ids.length} factories`}
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}
