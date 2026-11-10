import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api, type Flag, type SupplierDetail } from '../api'
import { Empty, ErrorBox, FLink, Loading, StatusBadge, fmtDate, fmtUsd } from '../ui'

export default function SupplierPage({ finisherId }: { finisherId: string }) {
  const { supplierId = '' } = useParams()
  const supplier = useQuery({
    queryKey: ['supplier', supplierId, finisherId],
    queryFn: () => api.supplier(supplierId, finisherId),
  })
  const history = useQuery({ queryKey: ['flags', supplierId], queryFn: () => api.flagHistory(supplierId) })

  if (supplier.isPending) return <Loading />
  if (supplier.isError) return <ErrorBox error={supplier.error} />
  const s = supplier.data
  const affectedToys = s.toys.filter((t) => t.status !== 'clean')

  return (
    <>
      <p className="crumbs">
        <FLink to="/suppliers">Suppliers</FLink> / {s.id}
      </p>
      <h1>
        {s.name} {s.active_flag && <span className="badge badge-flagged">Flagged</span>}
      </h1>
      <p className="muted">
        {s.id} · HQ {s.hq_country ?? 'unknown'} · {s.factories.length} factories · {new Set(s.parts.map((p) => p.part_id)).size} parts
      </p>

      <section className="panel">
        {s.active_flag ? (
          <ActiveFlagPanel flag={s.active_flag} finisherId={finisherId} />
        ) : (
          <FlagForm supplier={s} finisherId={finisherId} />
        )}
      </section>

      <section>
        <h2>
          Your toys using this supplier{' '}
          <span className="muted">
            ({s.toys.length} toys; {affectedToys.length} exposed via any flagged supplier)
          </span>
        </h2>
        {s.toys.length === 0 ? (
          <Empty>None of your toys use parts from this supplier.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Toy</th>
                <th title="Overall toy status, considering every flagged supplier in its BOM">Overall status</th>
                <th>Via parts</th>
              </tr>
            </thead>
            <tbody>
              {s.toys.map((t) => (
                <tr key={t.toy_id}>
                  <td>
                    <FLink to={`/toys/${t.toy_id}`}>{t.name}</FLink> <span className="id">{t.toy_id}</span>
                  </td>
                  <td>
                    <StatusBadge status={t.status} />
                  </td>
                  <td className="muted">{t.via_parts.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>Factories</h2>
        {s.factories.length === 0 ? (
          <Empty>No factories on record for this supplier.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Factory</th>
                <th>Location</th>
                <th className="num">Parts</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {s.factories.map((f) => (
                <tr key={f.id}>
                  <td>
                    {f.name} <span className="id">{f.id}</span>
                  </td>
                  <td>{[f.address_line, f.city, f.country].filter(Boolean).join(', ') || <span className="muted">unknown</span>}</td>
                  <td className="num">{f.part_count}</td>
                  <td>
                    <StatusBadge status={f.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>Parts supplied</h2>
        {s.parts.length === 0 ? (
          <Empty>No parts on record.</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Part</th>
                <th>Factory</th>
                <th className="num">Unit cost</th>
                <th>Sources</th>
                <th>Part status</th>
              </tr>
            </thead>
            <tbody>
              {s.parts.map((p) => (
                <tr key={`${p.part_id}/${p.factory_id}`}>
                  <td>
                    {p.part_name} <span className="id">{p.part_id}</span>
                  </td>
                  <td className="id">{p.factory_id}</td>
                  <td className="num">{fmtUsd(p.unit_cost_usd)}</td>
                  <td>{p.source_count > 1 ? `${p.source_count} (multi-sourced)` : 'single'}</td>
                  <td>
                    <StatusBadge status={p.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>Flag history</h2>
        {history.isPending && <Loading />}
        {history.isError && <ErrorBox error={history.error} />}
        {history.data && history.data.length === 0 && <Empty>Never flagged.</Empty>}
        {history.data && history.data.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Scope</th>
                <th>Flagged</th>
                <th>Reason</th>
                <th>Lifted</th>
              </tr>
            </thead>
            <tbody>
              {history.data.map((f) => (
                <tr key={f.id}>
                  <td>{f.id}</td>
                  <td>{scopeText(f)}</td>
                  <td>
                    {fmtDate(f.created_at)}
                    {f.flagged_by && <div className="small muted">by {f.flagged_by}</div>}
                  </td>
                  <td>{f.reason ?? <span className="muted">—</span>}</td>
                  <td>
                    {f.active ? (
                      <span className="badge badge-flagged">Active</span>
                    ) : (
                      <>
                        {fmtDate(f.lifted_at!)}
                        {f.lifted_by && <span className="small muted"> by {f.lifted_by}</span>}
                        {f.lift_reason && <div className="small">{f.lift_reason}</div>}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}

const scopeText = (f: Flag) => (f.scope === 'supplier' ? 'Whole supplier' : `Factories: ${f.factory_ids.join(', ')}`)

function FlagForm({ supplier, finisherId }: { supplier: SupplierDetail; finisherId: string }) {
  const qc = useQueryClient()
  const [scope, setScope] = useState<'supplier' | 'factories'>('supplier')
  const [factories, setFactories] = useState<string[]>([])
  const [reason, setReason] = useState('')

  const mutation = useMutation({
    mutationFn: () =>
      api.createFlag(supplier.id, {
        reason: reason.trim() || undefined,
        factory_ids: scope === 'factories' ? factories : [],
        flagged_by: finisherId,
      }),
    onSuccess: () => qc.invalidateQueries(), // every view depends on the flag set
  })

  const noFactories = supplier.factories.length === 0
  const invalid = scope === 'factories' && factories.length === 0

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!invalid) mutation.mutate()
  }
  const toggle = (id: string) => setFactories((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]))

  return (
    <form onSubmit={submit}>
      <h2>Flag as using child labour</h2>
      <fieldset>
        <label className="radio">
          <input type="radio" checked={scope === 'supplier'} onChange={() => setScope('supplier')} />
          <span>
            <strong>Whole supplier</strong> — all parts from every factory are treated as affected. Use when the site is unknown.
          </span>
        </label>
        <label className={`radio ${noFactories ? 'disabled' : ''}`}>
          <input type="radio" checked={scope === 'factories'} onChange={() => setScope('factories')} disabled={noFactories} />
          <span>
            <strong>Specific factories</strong> — parts from these sites are <em>confirmed</em>; other sites of this supplier become{' '}
            <em>supplier risk</em>.
          </span>
        </label>
        {scope === 'factories' && (
          <div className="factory-picks">
            {supplier.factories.map((f) => (
              <label key={f.id} className="check">
                <input type="checkbox" checked={factories.includes(f.id)} onChange={() => toggle(f.id)} />
                {f.name} <span className="id">{f.id}</span> <span className="muted small">{[f.city, f.country].filter(Boolean).join(', ')}</span>
              </label>
            ))}
          </div>
        )}
      </fieldset>
      <label className="field">
        Reason / evidence (optional)
        <textarea value={reason} maxLength={1000} rows={2} onChange={(e) => setReason(e.target.value)} placeholder="e.g. NGO audit report, 2026-10" />
      </label>
      {invalid && <p className="small warn-inline">Select at least one factory.</p>}
      {mutation.isError && <ErrorBox error={mutation.error} />}
      <button type="submit" className="danger" disabled={invalid || mutation.isPending}>
        {mutation.isPending ? 'Flagging…' : 'Flag supplier'}
      </button>
    </form>
  )
}

function ActiveFlagPanel({ flag, finisherId }: { flag: Flag; finisherId: string }) {
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
  const mutation = useMutation({
    mutationFn: () => api.liftFlag(flag.id, { reason: reason.trim() || undefined, lifted_by: finisherId }),
    onSuccess: () => qc.invalidateQueries(),
  })

  return (
    <div>
      <h2>Active child-labour flag</h2>
      <dl className="facts">
        <dt>Scope</dt>
        <dd>{scopeText(flag)}</dd>
        <dt>Flagged</dt>
        <dd>
          {fmtDate(flag.created_at)}
          {flag.flagged_by && ` by ${flag.flagged_by}`}
        </dd>
        <dt>Reason</dt>
        <dd>{flag.reason ?? '—'}</dd>
      </dl>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault()
          mutation.mutate()
        }}
      >
        <input value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} placeholder="Reason for lifting (e.g. remediation verified)" />
        <button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Lifting…' : 'Lift flag'}
        </button>
      </form>
      <p className="small muted">To change the scope, lift this flag and create a new one — history keeps both.</p>
      {mutation.isError && <ErrorBox error={mutation.error} />}
    </div>
  )
}
