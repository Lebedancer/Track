// Typed client for the FastAPI backend. Types mirror backend/app/schemas.py.

export type ExposureStatus = 'confirmed' | 'potential' | 'supplier_risk' | 'clean'
export type SourceStatus = 'flagged' | 'supplier_risk' | 'clean'
export type Severity = 'error' | 'warning' | 'info'

export interface Finisher {
  id: string
  name: string
  hq_country: string | null
  toy_count: number
}

export interface Flag {
  id: number
  supplier_id: string
  scope: 'supplier' | 'factories'
  factory_ids: string[]
  reason: string | null
  flagged_by: string | null
  created_at: string
  active: boolean
  lifted_at: string | null
  lifted_by: string | null
  lift_reason: string | null
}

export interface Totals {
  toy_count: number
  units_per_year: number
  revenue_usd: number
}

export interface Exposure {
  finisher: Finisher
  total: Totals
  affected: Totals
  by_status: (Totals & { status: ExposureStatus })[]
  suppliers: (Totals & { supplier_id: string; supplier_name: string; flag: Flag })[]
}

export interface ToyRow {
  toy_id: string
  name: string
  status: ExposureStatus
  retail_price_usd: number
  units_per_year: number
  revenue_usd: number
  part_count: number
  affected_part_count: number
  has_bom: boolean
  other_finishers: string[]
}

export interface Source {
  factory_id: string
  factory_name: string
  city: string | null
  country: string | null
  supplier_id: string
  supplier_name: string
  unit_cost_usd: number
  status: SourceStatus
  flag_id: number | null
}

export interface BomLine {
  part_id: string
  part_name: string
  quantity: number
  status: ExposureStatus
  sources: Source[]
}

export interface ToyDetail {
  toy_id: string
  name: string
  status: ExposureStatus
  has_bom: boolean
  listings: { finisher_id: string; finisher_name: string; retail_price_usd: number; units_per_year: number; revenue_usd: number }[]
  bom: BomLine[]
}

export interface SupplierRow {
  id: string
  name: string
  hq_country: string | null
  factory_count: number
  part_count: number
  toy_count: number
  affected_toy_count: number
  active_flag: Flag | null
}

export interface SupplierDetail {
  id: string
  name: string
  hq_country: string | null
  active_flag: Flag | null
  factories: {
    id: string
    name: string
    address_line: string | null
    city: string | null
    country: string | null
    part_count: number
    status: SourceStatus
  }[]
  parts: { part_id: string; part_name: string; factory_id: string; unit_cost_usd: number; source_count: number; status: ExposureStatus }[]
  toys: { toy_id: string; name: string; status: ExposureStatus; finisher_ids: string[]; via_parts: string[] }[]
}

export interface DataQuality {
  summary: { code: string; severity: Severity; count: number }[]
  issues: { code: string; severity: Severity; entity: string; entity_id: string | null; message: string }[]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

const qs = (params: Record<string, string | string[] | boolean | undefined | null>) => {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => p.append(k, x))
    else p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const api = {
  finishers: () => request<Finisher[]>('/finishers'),
  exposure: (fid: string) => request<Exposure>(`/finishers/${fid}/exposure`),
  toys: (fid: string, params: { status?: ExposureStatus[]; q?: string } = {}) =>
    request<ToyRow[]>(`/finishers/${fid}/toys${qs(params)}`),
  toy: (tid: string) => request<ToyDetail>(`/toys/${tid}`),
  suppliers: (params: { finisher_id?: string; q?: string; flagged?: boolean } = {}) =>
    request<SupplierRow[]>(`/suppliers${qs(params)}`),
  supplier: (sid: string, finisherId?: string) => request<SupplierDetail>(`/suppliers/${sid}${qs({ finisher_id: finisherId })}`),
  flagHistory: (sid: string) => request<Flag[]>(`/suppliers/${sid}/flags`),
  createFlag: (sid: string, body: { reason?: string; factory_ids?: string[]; flagged_by?: string }) =>
    request<Flag>(`/suppliers/${sid}/flags`, { method: 'POST', body: JSON.stringify(body) }),
  liftFlag: (flagId: number, body: { reason?: string; lifted_by?: string }) =>
    request<Flag>(`/flags/${flagId}/lift`, { method: 'POST', body: JSON.stringify(body) }),
  dataQuality: () => request<DataQuality>('/data-quality'),
}
