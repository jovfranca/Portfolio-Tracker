import { useEffect, useState } from 'react'
import { api, type BenchmarkObservations } from './api'

const dateLabel = (value: string | null) => value ? value.slice(0, 10).split('-').reverse().join('/') : '—'
const pageSize = 100

export default function BenchmarkInspection() {
  const [code, setCode] = useState<'CDI' | 'IPCA'>('CDI')
  const [data, setData] = useState<BenchmarkObservations | null>(null)
  const [error, setError] = useState('')
  const [page, setPage] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError(''); setPage(0)
    api<BenchmarkObservations>(`/benchmarks/${code}/observations`, 'GET', undefined, controller.signal)
      .then(setData)
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Falha ao carregar observações.') })
    return () => controller.abort()
  }, [code])

  const rows = data ? [...data.observations].reverse().slice(page * pageSize, (page + 1) * pageSize) : []
  return <section className="panel">
    <div className="section-heading"><div><h2>Dados dos indexadores</h2><p>Observações canônicas armazenadas no banco, sem consulta ao provedor nesta tela.</p></div>
      <label>Indexador<select value={code} onChange={event => setCode(event.target.value as 'CDI' | 'IPCA')}><option value="CDI">CDI</option><option value="IPCA">IPCA</option></select></label></div>
    {error && <div role="alert" className="alert error">{error}</div>}
    {!data && !error && <p>Carregando observações…</p>}
    {data && <><p className="method-note">{data.count} observações · de {dateLabel(data.earliest)} até {dateLabel(data.latest)} · {data.unit}</p>
      {!data.count ? <div className="empty">Ainda não há observações armazenadas para {code}.</div>
        : <><div className="table-wrap"><table><thead><tr><th>Data / referência</th><th>Valor</th><th>Unidade</th><th>Fonte</th></tr></thead><tbody>
          {rows.map(row => <tr key={row.reference_date}><td>{dateLabel(row.reference_date)}</td><td>{row.value}</td><td>{row.unit}</td><td>{row.source}</td></tr>)}
        </tbody></table></div><div className="row-actions"><button className="button quiet" disabled={page === 0} onClick={() => setPage(page - 1)}>Mais recentes</button>
          <span>{page * pageSize + 1}–{Math.min((page + 1) * pageSize, data.count)} de {data.count}</span>
          <button className="button quiet" disabled={(page + 1) * pageSize >= data.count} onClick={() => setPage(page + 1)}>Mais antigas</button></div></>}
    </>}
  </section>
}
