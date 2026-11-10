import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api, type ExposureStatus } from '../api'
import { EXPOSURE_ORDER, Empty, ErrorBox, FLink, Loading, STATUS_LABEL, StatusBadge, fmtInt, fmtUsd, fmtUsdCompact } from '../ui'

export default function ToysPage({ finisherId }: { finisherId: string }) {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const status = params.getAll('status') as ExposureStatus[]

  const toys = useQuery({
    queryKey: ['toys', finisherId, { q, status }],
    queryFn: () => api.toys(finisherId, { q, status }),
    placeholderData: (prev) => prev,
  })

  const update = (mut: (p: URLSearchParams) => void) => {
    const next = new URLSearchParams(params)
    mut(next)
    setParams(next, { replace: true })
  }
  const toggleStatus = (s: ExposureStatus) =>
    update((p) => {
      const cur = p.getAll('status')
      p.delete('status')
      const nextVals = cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]
      nextVals.forEach((v) => p.append('status', v))
    })

  return (
    <>
      <h1>Toys</h1>
      <div className="toolbar">
        <input
          type="search"
          placeholder="Search by name or id…"
          value={q}
          onChange={(e) => update((p) => (e.target.value ? p.set('q', e.target.value) : p.delete('q')))}
        />
        <div className="chips" role="group" aria-label="Filter by status">
          {EXPOSURE_ORDER.map((s) => (
            <button key={s} className={`chip ${status.includes(s) ? 'chip-on' : ''}`} onClick={() => toggleStatus(s)} aria-pressed={status.includes(s)}>
              {STATUS_LABEL[s]}
            </button>
          ))}
        </div>
      </div>

      {toys.isPending && <Loading />}
      {toys.isError && <ErrorBox error={toys.error} />}
      {toys.data && toys.data.length === 0 && <Empty>No toys match.</Empty>}
      {toys.data && toys.data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Toy</th>
              <th>Status</th>
              <th className="num">Affected / parts</th>
              <th className="num">Price</th>
              <th className="num">Units / yr</th>
              <th className="num">Revenue / yr</th>
              <th>Also sold by</th>
            </tr>
          </thead>
          <tbody>
            {toys.data.map((t) => (
              <tr key={t.toy_id}>
                <td>
                  <FLink to={`/toys/${t.toy_id}`}>{t.name}</FLink> <span className="id">{t.toy_id}</span>
                </td>
                <td>
                  <StatusBadge status={t.status} />
                  {!t.has_bom && <span className="warn-inline"> no BOM data</span>}
                </td>
                <td className="num">
                  {t.affected_part_count} / {t.part_count}
                </td>
                <td className="num">{fmtUsd(t.retail_price_usd)}</td>
                <td className="num">{fmtInt(t.units_per_year)}</td>
                <td className="num">{fmtUsdCompact(t.revenue_usd)}</td>
                <td className="muted">{t.other_finishers.join(', ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {toys.data && <p className="muted small">{toys.data.length} toys</p>}
    </>
  )
}
