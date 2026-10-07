import { useState } from 'react'
import { api, type Overview } from './api'
import BenchmarkInspection from './BenchmarkInspection'
import { Attention } from './OverviewPage'
import { CorporateActionsPanel, Quotes } from './MarketPanels'
import { dateLabel, EmptyState, fmt, localDate, message, PageHeader, Tabs, type Mutate } from './ui'

export default function MarketDataPage({ tab, overview, portfolioId, readOnly, busy, mutate, version, onUpdate }: { tab: string; overview: Overview; portfolioId: number; readOnly: boolean; busy: boolean; mutate: Mutate; version: number; onUpdate: () => void }) {
  const marketAssets = overview.assets.filter(a => !overview.positions.some(p => p.asset_id === a.id && p.position_type === 'FIXED_INCOME'))
  const [assetId, setAssetId] = useState(Number(new URLSearchParams(window.location.search).get('asset')) || marketAssets[0]?.id || 0)
  const items = [['status', 'Status'], ['quotes', 'Cotações'], ['fx', 'Câmbio'], ['benchmarks', 'Benchmarks'], ['corporate-actions', 'Eventos corporativos']].map(([key, label]) => ['/data/' + key, label] as const)
  return <><PageHeader title="Dados de mercado" description="Monitore cotações, câmbio, benchmarks e eventos que sustentam sua carteira." />
    <Tabs items={items} active={'/data/' + tab} />
    {tab === 'status' && <><Attention overview={overview} /><section className="panel settings-section"><h2>Status da carteira</h2><p>Histórico atualizado até {dateLabel(overview.summary.history_built_through)}. {overview.methodology}</p>{!readOnly && <button className="button primary" disabled={busy} onClick={onUpdate}>Atualizar tudo</button>}</section></>}
    {tab === 'quotes' && <Quotes key={version} portfolioId={portfolioId} assets={marketAssets} initialAssetId={assetId} readOnly={readOnly} busy={busy} mutate={mutate} />}
    {tab === 'benchmarks' && <BenchmarkInspection key={version} />}
    {tab === 'fx' && <FxPanel overview={overview} />}
    {tab === 'corporate-actions' && <section className="panel"><div className="section-heading"><label>Instrumento<select value={assetId} onChange={e => setAssetId(Number(e.target.value))}>{marketAssets.map(a => <option key={a.id} value={a.id}>{a.ticker}</option>)}</select></label></div>{!assetId ? <EmptyState>Adicione uma transação para acompanhar eventos.</EmptyState> : <CorporateActionsPanel key={assetId} base={'/portfolios/' + portfolioId + '/assets/' + assetId} currency={overview.assets.find(a => a.id === assetId)?.transaction_currency ?? 'BRL'} busy={busy} readOnly={readOnly} mutate={mutate} refreshVersion={version} />}</section>}
  </>
}
function FxPanel({ overview }: { overview: Overview }) {
  const currencies = (overview.summary.currencies ?? []).filter(c => c !== 'BRL')
  const [currency, setCurrency] = useState(currencies[0] ?? 'USD'), [day, setDay] = useState(localDate()), [kind, setKind] = useState('FX')
  const [result, setResult] = useState<{ reference_date: string; fallback_used: boolean; rates: { side: string; rate: string; source: string; retrieved_at: string }[] } | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  return <section className="panel settings-section"><h2>Câmbio e PTAX</h2><p>Moedas usadas: {currencies.join(', ') || 'Somente BRL'}. Datas sem publicação podem usar a observação anterior dentro da janela configurada.</p><form className="filter-bar" onSubmit={async e => {
    e.preventDefault(); setBusy(true); setError(''); setResult(null)
    try { setResult(await api('/rates/' + kind + '/' + currency + '/' + day)) } catch (e) { setError(message(e)) } finally { setBusy(false) }
  }}><label>Moeda<input required pattern="[A-Z]{3}" maxLength={3} value={currency} onChange={e => setCurrency(e.target.value.toUpperCase())} /></label><label>Data de referência<input required type="date" value={day} onChange={e => setDay(e.target.value)} /></label><label>Série<select value={kind} onChange={e => setKind(e.target.value)}><option>FX</option><option>PTAX</option></select></label><button className="button outline" disabled={busy}>{busy ? 'Consultando…' : 'Consultar câmbio'}</button></form>
    {error && <p role="alert">{error}</p>}{result && <><p>Data utilizada: {dateLabel(result.reference_date)}{result.fallback_used && ' · observação anterior'}</p><div className="table-wrap"><table><thead><tr><th>Lado</th><th>BRL por unidade</th><th>Fonte</th><th>Consulta</th></tr></thead><tbody>{result.rates.map(r => <tr key={r.side}><td>{r.side === 'BUY' ? 'Compra' : r.side === 'SELL' ? 'Venda' : 'Mercado'}</td><td>{fmt(r.rate, 6)}</td><td>{r.source}</td><td>{dateLabel(r.retrieved_at)}</td></tr>)}</tbody></table></div></>}
  </section>
}
