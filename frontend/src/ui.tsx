import type { ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { ExposureStatus, SourceStatus } from './api'

// --- finisher context lives in the URL (?finisher=FIN-001) -------------------

export function useFinisherId(): string | null {
  const [params] = useSearchParams()
  return params.get('finisher')
}

/** Link that keeps the selected finisher in the query string. */
export function FLink({
  to,
  children,
  className,
  query,
}: {
  to: string
  children: ReactNode
  className?: string
  query?: Record<string, string>
}) {
  const fid = useFinisherId()
  const p = new URLSearchParams(query)
  if (fid) p.set('finisher', fid)
  const s = p.toString()
  const href = s ? `${to}?${s}` : to
  return (
    <Link to={href} className={className}>
      {children}
    </Link>
  )
}

// --- status ---------------------------------------------------------------------

export const STATUS_LABEL: Record<ExposureStatus | SourceStatus, string> = {
  confirmed: 'Confirmed',
  potential: 'Potential',
  supplier_risk: 'Supplier risk',
  clean: 'Clean',
  flagged: 'Flagged',
}

export const STATUS_HELP: Record<ExposureStatus | SourceStatus, string> = {
  confirmed: 'Every possible source of an affected part is flagged.',
  potential: 'A part may come from a flagged source; the BOM does not say which source is used.',
  supplier_risk: 'Comes from a flagged supplier, but from a factory not named in the flag.',
  clean: 'No flagged supplier in the chain.',
  flagged: 'This source is covered by an active child-labour flag.',
}

export const EXPOSURE_ORDER: ExposureStatus[] = ['confirmed', 'potential', 'supplier_risk', 'clean']

export function StatusBadge({ status }: { status: ExposureStatus | SourceStatus }) {
  return (
    <span className={`badge badge-${status}`} title={STATUS_HELP[status]}>
      {STATUS_LABEL[status]}
    </span>
  )
}

// --- formatting -----------------------------------------------------------------

const int = new Intl.NumberFormat('en-US')
const compactUsd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 })
const usd = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

export const fmtInt = (n: number) => int.format(n)
export const fmtUsd = (n: number) => usd.format(n)
export const fmtUsdCompact = (n: number) => compactUsd.format(n)
export const fmtDate = (iso: string) => new Date(iso).toLocaleString()

// --- states ---------------------------------------------------------------------

export function Loading() {
  return <p className="muted">Loading…</p>
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error)
  return (
    <div className="error" role="alert">
      {msg}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>
}
