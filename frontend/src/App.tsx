import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { NavLink, Route, Routes, useSearchParams } from 'react-router-dom'
import { api } from './api'
import { ErrorBox, Loading, useFinisherId } from './ui'
import Overview from './pages/Overview'
import ToysPage from './pages/ToysPage'
import ToyPage from './pages/ToyPage'
import SuppliersPage from './pages/SuppliersPage'
import SupplierPage from './pages/SupplierPage'
import DataQualityPage from './pages/DataQualityPage'

const NAV = [
  ['/', 'Overview'],
  ['/toys', 'Toys'],
  ['/suppliers', 'Suppliers'],
  ['/data-quality', 'Data quality'],
] as const

export default function App() {
  const [params, setParams] = useSearchParams()
  const fid = useFinisherId()
  const finishers = useQuery({ queryKey: ['finishers'], queryFn: api.finishers })

  // Default / repair the finisher in the URL.
  useEffect(() => {
    const list = finishers.data
    if (!list?.length) return
    if (!fid || !list.some((f) => f.id === fid)) {
      const next = new URLSearchParams(params)
      next.set('finisher', list[0].id)
      setParams(next, { replace: true })
    }
  }, [finishers.data, fid, params, setParams])

  const selectFinisher = (id: string) => {
    const next = new URLSearchParams(params)
    next.set('finisher', id)
    setParams(next)
  }

  const suffix = fid ? `?finisher=${encodeURIComponent(fid)}` : ''

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          FairToy <span>Exposure</span>
        </div>
        <nav>
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to + suffix} end={to === '/'}>
              {label}
            </NavLink>
          ))}
        </nav>
        <label className="finisher-select">
          <span>Finisher</span>
          <select value={fid ?? ''} onChange={(e) => selectFinisher(e.target.value)} disabled={!finishers.data}>
            {finishers.data?.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name} ({f.id})
              </option>
            ))}
          </select>
        </label>
      </header>
      <main>
        {finishers.isPending && <Loading />}
        {finishers.isError && <ErrorBox error={finishers.error} />}
        {finishers.data && fid && (
          <Routes>
            <Route path="/" element={<Overview finisherId={fid} />} />
            <Route path="/toys" element={<ToysPage finisherId={fid} />} />
            <Route path="/toys/:toyId" element={<ToyPage finisherId={fid} />} />
            <Route path="/suppliers" element={<SuppliersPage finisherId={fid} />} />
            <Route path="/suppliers/:supplierId" element={<SupplierPage finisherId={fid} />} />
            <Route path="/data-quality" element={<DataQualityPage />} />
            <Route path="*" element={<p>Page not found.</p>} />
          </Routes>
        )}
      </main>
    </div>
  )
}
