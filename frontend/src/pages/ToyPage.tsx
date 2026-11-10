import { Fragment, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api, type BomLine, type ToyDetail } from '../api'
import { Empty, ErrorBox, FLink, Loading, STATUS_HELP, StatusBadge, fmtInt, fmtUsd, fmtUsdCompact } from '../ui'

export default function ToyPage({ finisherId }: { finisherId: string }) {
  const { toyId = '' } = useParams()
  const toy = useQuery({ queryKey: ['toy', toyId], queryFn: () => api.toy(toyId) })

  if (toy.isPending) return <Loading />
  if (toy.isError) return <ErrorBox error={toy.error} />
  return <ToyView toy={toy.data} finisherId={finisherId} />
}

function ToyView({ toy, finisherId }: { toy: ToyDetail; finisherId: string }) {
  const affectedCount = toy.bom.filter((l) => l.status !== 'clean').length
  const [onlyAffected, setOnlyAffected] = useState(affectedCount > 0)
  const lines = onlyAffected ? toy.bom.filter((l) => l.status !== 'clean') : toy.bom
  const soldByMe = toy.listings.some((l) => l.finisher_id === finisherId)

  return (
    <>
      <p className="crumbs">
        <FLink to="/toys">Toys</FLink> / {toy.toy_id}
      </p>
      <h1>
        {toy.name} <StatusBadge status={toy.status} />
      </h1>
      <p className="muted">{STATUS_HELP[toy.status]}</p>
      {!soldByMe && <div className="notice">This toy is not in the selected finisher's product line.</div>}

      <section>
        <h2>Sold by</h2>
        <table>
          <thead>
            <tr>
              <th>Finisher</th>
              <th className="num">Price</th>
              <th className="num">Units / yr</th>
              <th className="num">Revenue / yr</th>
            </tr>
          </thead>
          <tbody>
            {toy.listings.map((l) => (
              <tr key={l.finisher_id} className={l.finisher_id === finisherId ? 'row-current' : ''}>
                <td>
                  {l.finisher_name} <span className="id">{l.finisher_id}</span>
                </td>
                <td className="num">{fmtUsd(l.retail_price_usd)}</td>
                <td className="num">{fmtInt(l.units_per_year)}</td>
                <td className="num">{fmtUsdCompact(l.revenue_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <div className="section-head">
          <h2>
            Bill of materials <span className="muted">({affectedCount} of {toy.bom.length} parts affected)</span>
          </h2>
          <label className="toggle">
            <input type="checkbox" checked={onlyAffected} onChange={(e) => setOnlyAffected(e.target.checked)} /> Affected parts only
          </label>
        </div>
        {!toy.has_bom && <Empty>No bill of materials in the source data — exposure cannot be assessed for this toy.</Empty>}
        {toy.has_bom && lines.length === 0 && <Empty>No affected parts.</Empty>}
        {lines.length > 0 && (
          <table className="bom">
            <thead>
              <tr>
                <th>Part</th>
                <th className="num">Qty</th>
                <th>Status</th>
                <th>Trace: factory → supplier</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <BomRow key={l.part_id} line={l} />
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}

function BomRow({ line }: { line: BomLine }) {
  const multi = line.sources.length > 1
  const hasAlternative = line.status !== 'clean' && line.sources.some((s) => s.status === 'clean')
  return (
    <Fragment>
      {line.sources.map((s, i) => (
        <tr key={s.factory_id} className={i > 0 ? 'cont' : ''}>
          {i === 0 && (
            <>
              <td rowSpan={line.sources.length}>
                {line.part_name} <span className="id">{line.part_id}</span>
                {multi && <div className="small muted">{line.sources.length} possible sources</div>}
              </td>
              <td rowSpan={line.sources.length} className="num">
                ×{line.quantity}
              </td>
              <td rowSpan={line.sources.length}>
                <StatusBadge status={line.status} />
              </td>
            </>
          )}
          <td>
            <div className={`trace trace-${s.status}`}>
              <span>
                {s.factory_name} <span className="id">{s.factory_id}</span>
                <span className="muted small"> {[s.city, s.country].filter(Boolean).join(', ') || 'location unknown'}</span>
              </span>
              <span className="arrow">→</span>
              <FLink to={`/suppliers/${s.supplier_id}`}>{s.supplier_name}</FLink>
              <span className="id">{s.supplier_id}</span>
              <StatusBadge status={s.status} />
              {hasAlternative && s.status === 'clean' && <span className="alt">clean alternative</span>}
            </div>
          </td>
        </tr>
      ))}
    </Fragment>
  )
}
