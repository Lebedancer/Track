import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { Empty, ErrorBox, FLink, Loading, STATUS_HELP, StatusBadge, fmtInt, fmtUsdCompact } from '../ui'

export default function Overview({ finisherId }: { finisherId: string }) {
  const exposure = useQuery({ queryKey: ['exposure', finisherId], queryFn: () => api.exposure(finisherId) })
  const affected = useQuery({
    queryKey: ['toys', finisherId, 'affected'],
    queryFn: () => api.toys(finisherId, { status: ['confirmed', 'potential', 'supplier_risk'] }),
  })

  if (exposure.isPending) return <Loading />
  if (exposure.isError) return <ErrorBox error={exposure.error} />
  const ex = exposure.data
  const pct = ex.total.revenue_usd ? (ex.affected.revenue_usd / ex.total.revenue_usd) * 100 : 0

  return (
    <>
      <h1>{ex.finisher.name}</h1>
      <p className="muted">
        {ex.finisher.id} · {ex.finisher.hq_country ?? 'HQ unknown'} · {fmtInt(ex.total.toy_count)} toys
      </p>

      <section className="kpis">
        <div className={`kpi ${ex.affected.toy_count ? 'kpi-alert' : ''}`}>
          <div className="kpi-label">Toys exposed</div>
          <div className="kpi-value">
            {fmtInt(ex.affected.toy_count)} <small>/ {fmtInt(ex.total.toy_count)}</small>
          </div>
        </div>
        <div className={`kpi ${ex.affected.toy_count ? 'kpi-alert' : ''}`}>
          <div className="kpi-label">Revenue at risk / yr</div>
          <div className="kpi-value">
            {fmtUsdCompact(ex.affected.revenue_usd)} <small>{pct.toFixed(1)}%</small>
          </div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Units at risk / yr</div>
          <div className="kpi-value">{fmtInt(ex.affected.units_per_year)}</div>
        </div>
        <div className="kpi">
          <div className="kpi-label">Flagged suppliers in chain</div>
          <div className="kpi-value">{ex.suppliers.filter((s) => s.toy_count > 0).length}</div>
        </div>
      </section>

      <section>
        <h2>By status</h2>
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Meaning</th>
              <th className="num">Toys</th>
              <th className="num">Units / yr</th>
              <th className="num">Revenue / yr</th>
            </tr>
          </thead>
          <tbody>
            {ex.by_status.map((s) => (
              <tr key={s.status}>
                <td>
                  <FLink to="/toys" query={{ status: s.status }}>
                    <StatusBadge status={s.status} />
                  </FLink>
                </td>
                <td className="muted">{STATUS_HELP[s.status]}</td>
                <td className="num">{fmtInt(s.toy_count)}</td>
                <td className="num">{fmtInt(s.units_per_year)}</td>
                <td className="num">{fmtUsdCompact(s.revenue_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Impact by flagged supplier</h2>
        {ex.suppliers.length === 0 ? (
          <Empty>
            No supplier is flagged yet. Go to <FLink to="/suppliers">Suppliers</FLink> to flag one.
          </Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Supplier</th>
                <th>Flag scope</th>
                <th className="num">Your toys affected</th>
                <th className="num">Revenue / yr</th>
              </tr>
            </thead>
            <tbody>
              {ex.suppliers.map((s) => (
                <tr key={s.supplier_id}>
                  <td>
                    <FLink to={`/suppliers/${s.supplier_id}`}>{s.supplier_name}</FLink> <span className="id">{s.supplier_id}</span>
                  </td>
                  <td>{s.flag.scope === 'supplier' ? 'Whole supplier' : `Factories: ${s.flag.factory_ids.join(', ')}`}</td>
                  <td className="num">{fmtInt(s.toy_count)}</td>
                  <td className="num">{fmtUsdCompact(s.revenue_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>Affected toys</h2>
        {affected.isPending && <Loading />}
        {affected.isError && <ErrorBox error={affected.error} />}
        {affected.data && affected.data.length === 0 && <Empty>None of your toys trace back to a flagged supplier.</Empty>}
        {affected.data && affected.data.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Toy</th>
                <th>Status</th>
                <th className="num">Affected parts</th>
                <th className="num">Revenue / yr</th>
              </tr>
            </thead>
            <tbody>
              {affected.data.map((t) => (
                <tr key={t.toy_id}>
                  <td>
                    <FLink to={`/toys/${t.toy_id}`}>{t.name}</FLink> <span className="id">{t.toy_id}</span>
                  </td>
                  <td>
                    <StatusBadge status={t.status} />
                  </td>
                  <td className="num">
                    {t.affected_part_count} / {t.part_count}
                  </td>
                  <td className="num">{fmtUsdCompact(t.revenue_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}
