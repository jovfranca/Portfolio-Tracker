import { useState } from 'react'
import type { CatalogInstrument, FixedIncomeProduct, Overview, Transaction, FixedIncomeLot } from './api'
import { Link } from './navigation'
import { useResource } from './useResource'
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from './ui'
import { typeLabels } from './text'

export default function InstrumentsPage({ instrumentId, overview, lots }: { lots: FixedIncomeLot[]; instrumentId?: number; overview: Overview | null; transactions: Transaction[] }) {
  const resource = useResource<CatalogInstrument[]>('/instruments')
  const products = useResource<FixedIncomeProduct[]>('/fixed-income/products')
  const [tab, setTab] = useState('market'), [query, setQuery] = useState('')
  if (resource.error) return <ErrorState error={resource.error} retry={resource.retry} />
  if (resource.loading) return <LoadingState />
  const item = resource.data?.find(i => i.id === instrumentId)
  if (instrumentId !== undefined) return item ? <><PageHeader title={item.symbol} description={item.name}><Link className="button outline" href="/instruments">← Instrumentos</Link></PageHeader><section className="panel settings-section"><StatusBadge status={item.status} /><p>{typeLabels[item.asset_type]} · {item.exchange ?? 'Global'} · Moeda: {item.currency ?? 'Variável'} · {typeLabels[item.origin ?? '']}</p><h2>Aliases</h2><p>{item.aliases?.join(' · ') || 'Nenhum alias'}</p><h2>Provedores</h2><ul>{item.mappings.map(m => <li key={m.provider + m.provider_symbol + m.quote_currency}>{m.provider} · {m.provider_symbol} · {m.quote_currency} · {m.active ? 'Ativo' : 'Inativo'}{m.is_primary && ' · Principal'}</li>)}</ul><h2>Posições nesta carteira</h2>{lots.filter(l => l.instrument_id === item.id).map(l => <Link key={l.id} href={'/fixed-income/' + l.id}>{l.instrument_symbol} · {l.issuer} →</Link>)}{overview?.positions.filter(p => p.instrument_id === item.id && p.position_type !== 'FIXED_INCOME').map(p => <Link key={p.asset_id} href={'/positions/' + p.asset_id}>{p.asset} →</Link>)}</section></> : <EmptyState>Instrumento não encontrado neste espaço financeiro.</EmptyState>
  const items = (resource.data ?? []).filter(i => (tab === 'custom' ? i.origin !== 'CATALOG' : i.origin === 'CATALOG' && (tab === 'fixed' ? i.asset_type === 'FIXED_INCOME' : i.asset_type !== 'FIXED_INCOME')) && [i.symbol, i.name, ...(i.aliases ?? [])].join(' ').toLowerCase().includes(query.toLowerCase()))
  return <><PageHeader title="Instrumentos" description="Identidades canônicas de mercado e instrumentos privados do espaço financeiro." /><nav className="tabs" aria-label="Categorias de instrumentos">{[['market', 'Mercado'], ['fixed', 'Renda fixa'], ['custom', 'Meus instrumentos']].map(([key, label]) => <button key={key} className="button quiet" aria-pressed={key === tab} onClick={() => setTab(key)}>{label}</button>)}</nav><section className="panel"><div className="filter-bar"><label>Buscar instrumentos<input value={query} onChange={e => setQuery(e.target.value)} /></label></div><div className="table-wrap"><table aria-label="Instrumentos"><thead><tr><th>Instrumento</th><th>Tipo</th><th>Mercado</th><th>Moeda</th><th>Status</th></tr></thead><tbody>{items.map(i => <tr key={i.id}><td><Link href={'/instruments/' + i.id}><strong>{i.symbol}</strong></Link><small>{i.name}</small></td><td>{typeLabels[i.asset_type]}</td><td>{i.exchange ?? 'Global'}</td><td>{i.currency ?? 'Variável'}</td><td><StatusBadge status={i.status} /></td></tr>)}</tbody></table></div>{!items.length && <EmptyState>Nenhum instrumento corresponde à busca.</EmptyState>}</section>
    {tab === 'fixed' && <section className="panel settings-section"><h2>Condições padrão de renda fixa</h2>{products.error && <p role="alert">{products.error}</p>}{products.data?.map(p => <article key={p.instrument_id}><strong>{p.symbol}</strong><p>{p.day_count_basis} · {p.compounding} · {p.business_day_calendar} · defasagem: {p.benchmark_lag_months} meses</p></article>)}</section>}
  </>
}
