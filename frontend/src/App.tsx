import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, type Portfolio, type Overview, type Transaction, type Performance, type Quote, type Asset, type Numeric } from './api'
import TransactionImportPage from './TransactionImportPage'

const tabPaths: Record<string, string> = { 'Posições': '/', 'Transações': '/transactions', 'Cotações': '/quotes', 'Desempenho': '/performance' }
const currentPath = () => window.location.hash.slice(1) || '/'

const fmt = (value: Numeric | null | undefined, digits = 2) => value == null ? '—' : Number(value).toLocaleString('pt-BR', { maximumFractionDigits: digits, minimumFractionDigits: digits })
const localDate = () => {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
const dateLabel = (value: string | null) => value ? value.slice(0, 10).split('-').reverse().join('/') : 'Sem cotação'
const message = (error: unknown) => error instanceof Error ? error.message : 'Não foi possível concluir.'
type Draft = Omit<Transaction, 'id' | 'portfolio_id' | 'fx_rate'> & { fx_rate: Numeric | '' }
const emptyDraft = (): Draft => ({ trade_date: localDate().slice(0, 10), settlement_date: localDate().slice(0, 10),
  type: 'Buy', asset: '', broker: '', allocation_class: '', asset_currency: 'BRL', fx_rate: '',
  quantity: 1, price: 0, brokerage_fee: 0, other_fees: 0, notes: '' })

export default function App() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [path, setPath] = useState(currentPath)
  const importing = path === '/transactions/import'
  const tab = importing ? 'Transações' : Object.keys(tabPaths).find(key => tabPaths[key] === path) ?? 'Posições'
  useEffect(() => {
    const onHashChange = () => setPath(currentPath())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [editing, setEditing] = useState<number | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [portfolioName, setPortfolioName] = useState('')
  const [newPortfolio, setNewPortfolio] = useState(false)
  const [query, setQuery] = useState('')

  const loadPortfolios = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const list = await api<Portfolio[]>('/portfolios')
      setPortfolios(list)
      setSelected(current => list.some(p => p.id === current) ? current : list[0]?.id ?? null)
    } catch (e) { setError(message(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void loadPortfolios() }, [loadPortfolios])

  const reload = useCallback(async (signal?: AbortSignal) => {
    if (selected === null) return
    const base = '/portfolios/' + selected
    const [data, txs] = await Promise.all([
      api<Overview>(base + '/overview', 'GET', undefined, signal),
      api<Transaction[]>(base + '/transactions', 'GET', undefined, signal),
    ])
    setOverview(data); setTransactions(txs)
  }, [selected])

  useEffect(() => {
    setOverview(null); setTransactions([]); setDraft(emptyDraft()); setEditing(null); setFormOpen(false); setQuery('')
    if (selected === null) return
    const controller = new AbortController()
    setLoading(true); setError('')
    reload(controller.signal).catch(e => {
      if (!controller.signal.aborted) setError(message(e))
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [selected, reload])

  async function mutate(task: () => Promise<unknown>, success: string) {
    setBusy(true); setError(''); setNotice('')
    try { await task(); await reload(); setNotice(success); return true }
    catch (e) { setError(message(e)); return false }
    finally { setBusy(false) }
  }

  async function createPortfolio(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      const created = await api<Portfolio>('/portfolios', 'POST', { name: portfolioName })
      setPortfolios([...portfolios, created]); setSelected(created.id); setPortfolioName(''); setNewPortfolio(false)
    } catch (e) { setError(message(e)) } finally { setBusy(false) }
  }

  async function saveTransaction(e: FormEvent) {
    e.preventDefault()
    const url = '/portfolios/' + selected + '/transactions' + (editing === null ? '' : '/' + editing)
    const payload = { ...draft, fx_rate: draft.fx_rate === '' ? null : draft.fx_rate }
    if (await mutate(() => api(url, editing === null ? 'POST' : 'PUT', payload), 'Transação salva. Posições recalculadas.')) {
      setDraft(emptyDraft()); setEditing(null); setFormOpen(false)
    }
  }
  function edit(tx: Transaction) {
    const { id, portfolio_id: _portfolioId, ...values } = tx
    setDraft({ ...values, fx_rate: values.fx_rate ?? '' }); setEditing(id); setFormOpen(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const filteredPositions = overview?.positions.filter(p => [p.asset, p.broker, p.allocation_class].join(' ').toLowerCase().includes(query.toLowerCase())) ?? []

  return <div className="app">
    <aside className="sidebar">
      <a className="brand" href="/"><span className="brand-icon">P<span>↗</span></span><span>portfolio<span className="brand-sub">TRACKER</span></span></a>
      <div className="nav-label">MEU PATRIMÔNIO</div>
      {['Posições', 'Transações', 'Cotações', 'Desempenho'].map((item, i) =>
        <button className={'nav-item ' + (tab === item ? 'active' : '')} key={item} onClick={() => { window.location.hash = tabPaths[item] }}>
          <span className="nav-symbol" aria-hidden="true">{['◫', '⇄', '⌁', '↗'][i]}</span>{item}
        </button>)}
      <div className="sidebar-footer"><span className="status-dot" /> Ambiente local<span>Seus registros em PostgreSQL</span></div>
    </aside>
    <main>
      <header className="topbar"><span>Visão da carteira</span><div className="portfolio-picker">
        <label className="sr-only" htmlFor="portfolio">Carteira</label>
        <select id="portfolio" value={selected ?? ''} disabled={busy || !portfolios.length} onChange={e => setSelected(Number(e.target.value))}>
          {!portfolios.length && <option value="">Nenhuma carteira</option>}
          {portfolios.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}
        </select>
        <button className="button quiet" disabled={busy} onClick={() => setNewPortfolio(!newPortfolio)}>+ Carteira</button>
      </div></header>
      <div className="content">
        <div className="page-heading"><div><div className="eyebrow">SEU PORTFOLIO, EM PERSPECTIVA</div><h1>{importing ? 'Importar transações' : tab}</h1>
          <p>{importing ? 'Envie seu histórico em CSV ou XLSX, revise os valores e confirme a importação na carteira selecionada.' : 'Acompanhe seus investimentos a partir das operações registradas.'}</p></div>
          {importing ? <a className="button outline" href="#/transactions">← Voltar para Transações</a> : <div className="page-actions">
            {tab === 'Transações' && <button className="button outline" disabled={selected === null || busy || loading} onClick={() => { setFormOpen(false); window.location.hash = '/transactions/import' }}>Importar transações</button>}
            <button className="button primary" disabled={selected === null || busy || loading} onClick={() => { setDraft(emptyDraft()); setEditing(null); setFormOpen(!formOpen) }}>+ Nova transação</button>
          </div>}
        </div>
        {error && <div role="alert" className="alert error">{error} <button className="button quiet" disabled={busy} onClick={() => void loadPortfolios().then(() => reload()).catch(e => setError(message(e)))}>Tentar novamente</button></div>}
        {notice && <div role="status" className="alert success">{notice}</div>}
        {(newPortfolio || (!loading && !portfolios.length && !error)) && <form className="panel inline-form" onSubmit={createPortfolio}>
          <div><h2>Comece pela sua carteira</h2><p>Crie um espaço para organizar suas transações e posições.</p></div>
          <label>Nome da carteira<input required maxLength={120} value={portfolioName} onChange={e => setPortfolioName(e.target.value)} placeholder="Ex.: Investimentos pessoais" /></label>
          <button className="button primary" disabled={busy}>Criar carteira</button>
        </form>}
        {formOpen && !importing && <form className="panel transaction-form" onSubmit={saveTransaction}>
          <div className="section-heading"><h2>{editing === null ? 'Registrar transação' : 'Editar transação'}</h2><button type="button" className="button quiet" disabled={busy} onClick={() => setFormOpen(false)}>Fechar</button></div>
          <fieldset disabled={busy}>
            <div className="form-grid">
              <label>Operação<select value={draft.type} onChange={e => setDraft({ ...draft, type: e.target.value as 'Buy' | 'Sell' })}><option value="Buy">Compra</option><option value="Sell">Venda</option></select></label>
              <label>Data da negociação<input required type="date" max={localDate().slice(0, 10)} value={draft.trade_date} onChange={e => setDraft({ ...draft, trade_date: e.target.value })} /></label>
              <label>Data da liquidação<input required type="date" min={draft.trade_date} value={draft.settlement_date} onChange={e => setDraft({ ...draft, settlement_date: e.target.value })} /></label>
              <label>Ticker<input required maxLength={40} value={draft.asset} onChange={e => setDraft({ ...draft, asset: e.target.value })} placeholder="Ex.: PETR4.SA" /></label>
              <label>Corretora<input required maxLength={120} value={draft.broker} onChange={e => setDraft({ ...draft, broker: e.target.value })} /></label>
              <label>Classe de alocação<input required maxLength={120} value={draft.allocation_class} onChange={e => setDraft({ ...draft, allocation_class: e.target.value })} placeholder="Ex.: Ações Brasil" /></label>
              <label>Moeda do ativo<input required maxLength={3} pattern="[A-Za-z]{3}" value={draft.asset_currency} onChange={e => { const currency = e.target.value.toUpperCase(); setDraft({ ...draft, asset_currency: currency, fx_rate: currency === draft.asset_currency ? draft.fx_rate : '' }) }} placeholder="BRL" /></label>
              <label>Taxa FX<input type="number" min="0.000000000001" step="any" value={draft.fx_rate} disabled={draft.asset_currency === 'BRL'} onChange={e => setDraft({ ...draft, fx_rate: e.target.value })} placeholder={draft.asset_currency === 'BRL' ? '1' : 'Automática'} /></label>
              {([['quantity', 'Quantidade'], ['price', 'Preço unitário'], ['brokerage_fee', 'Corretagem'], ['other_fees', 'Outras taxas']] as const).map(([key, label]) => <label key={key}>{label}<input required type="number" min={key === 'quantity' ? '0.000000000001' : '0'} step="any" value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value } as Draft)} /></label>)}
              <label className="wide">Observações<input maxLength={5000} value={draft.notes} onChange={e => setDraft({ ...draft, notes: e.target.value })} /></label>
            </div>
            <div className="form-footer"><span>FX vazio usa a taxa histórica da data de liquidação; o valor salvo não muda depois.</span><button className="button primary">{busy ? 'Salvando…' : 'Salvar transação'}</button></div>
          </fieldset>
        </form>}
        {loading && <div className="panel empty" role="status">Carregando sua carteira…</div>}
        {importing && <TransactionImportPage key={selected} portfolioId={selected} portfolioName={portfolios.find(p => p.id === selected)?.name ?? ''} busy={busy || loading} mutate={mutate} />}
        {!importing && !loading && overview && <>
          <div className="metrics">
            <article className="metric featured"><span>Valor das posições</span><strong>{fmt(overview.summary.total_value)}</strong><small>{overview.summary.currencies.length > 1 ? 'Totais separados: ' + Object.entries(overview.summary.totals_by_currency).map(([currency, total]) => currency + ' ' + fmt(total)).join(' · ') : overview.summary.missing_prices.length ? 'Parcial com cotação: ' + fmt(overview.summary.priced_value) : 'Na moeda do ativo'}</small></article>
            <article className="metric"><span>Ativos acompanhados</span><strong>{overview.summary.assets.toString().padStart(2, '0')}</strong><small>{overview.summary.positions} posições por corretora e classe</small></article>
            <article className="metric"><span>Operações registradas</span><strong>{overview.summary.transactions.toString().padStart(2, '0')}</strong><small>Compras e vendas persistidas</small></article>
          </div>
          <div className="method-note"><span>i</span> Moedas diferentes são exibidas separadamente e nunca somadas. Ganhos seguem as fórmulas originais, sem dividendos ou taxas.</div>
          {tab === 'Posições' && <section className="panel">
            <div className="section-heading"><div><h2>Composição da carteira</h2><p>Uma posição para cada ativo, corretora e classe.</p></div><label className="search"><span className="sr-only">Filtrar posições</span><input placeholder="Buscar ativo, corretora ou classe…" value={query} onChange={e => setQuery(e.target.value)} /></label></div>
            {!overview.positions.length ? <div className="empty"><div className="empty-icon">↗</div><h3>Sua carteira começa aqui</h3><p>Registre uma compra para acompanhar quantidade, preço médio e evolução.</p></div> :
              <div className="table-wrap"><table><thead><tr><th>Ativo / classe</th><th>Corretora</th><th>Quantidade</th><th>Preço médio</th><th>Cotação</th><th>Valor atual</th><th>Ganho histórico</th></tr></thead><tbody>{filteredPositions.map(p => <tr key={[p.asset, p.broker, p.allocation_class].join('|')}>
                <td><strong>{p.asset}</strong><small>{p.allocation_class}</small></td><td>{p.broker}</td><td>{fmt(p.quantity, 6)}</td><td>{fmt(p.average_cost, 4)}</td><td>{fmt(p.current_price)}<small>{dateLabel(p.price_date)}</small></td><td>{fmt(p.total_value)}</td>
                <td className={(p.current_total_gain ?? 0) >= 0 ? 'positive' : 'negative'}>{fmt(p.current_total_gain)}<small>{fmt(p.current_accumulated_profitability)}%{p.history_behind_transactions ? ' · histórico incompleto' : ''}</small></td>
              </tr>)}</tbody></table>{!filteredPositions.length && <div className="empty">Nenhuma posição corresponde à busca.</div>}</div>}
          </section>}
          {tab === 'Transações' && <section className="panel"><div className="section-heading"><div><h2>Histórico de operações</h2><p>Editar, excluir ou importar recalcula as posições automaticamente.</p></div></div>
            {!transactions.length ? <div className="empty">Nenhuma transação registrada.</div> : <div className="table-wrap"><table><thead><tr><th>Negociação / liquidação</th><th>Operação</th><th>Ativo / moeda</th><th>Corretora / classe</th><th>Quantidade</th><th>Preço / FX</th><th>Taxas</th><th>Ações</th></tr></thead><tbody>{transactions.map(tx => <tr key={tx.id}><td>{dateLabel(tx.trade_date)}<small>{dateLabel(tx.settlement_date)}</small></td><td><span className={'badge ' + (tx.type === 'Buy' ? 'buy' : 'sell')}>{tx.type === 'Buy' ? 'Compra' : 'Venda'}</span></td><td><strong>{tx.asset}</strong><small>{tx.asset_currency} · {tx.notes}</small></td><td>{tx.broker}<small>{tx.allocation_class}</small></td><td>{fmt(tx.quantity, 6)}</td><td>{fmt(tx.price, 4)}<small>FX {fmt(tx.fx_rate, 6)}</small></td><td>{fmt(Number(tx.brokerage_fee) + Number(tx.other_fees))}</td><td><div className="row-actions"><button className="button quiet" disabled={busy} onClick={() => edit(tx)}>Editar</button><button className="button danger" disabled={busy} onClick={() => {
              if (window.confirm('Excluir esta transação e recalcular as posições?')) void mutate(() => api('/portfolios/' + selected + '/transactions/' + tx.id, 'DELETE'), 'Transação excluída.')
            }}>Excluir</button></div></td></tr>)}</tbody></table></div>}
          </section>}
          {tab === 'Cotações' && <Quotes key={selected} portfolioId={selected!} assets={overview.assets} busy={busy} mutate={mutate} />}
          {tab === 'Desempenho' && <PerformancePanel key={selected} portfolioId={selected!} overview={overview} />}
          <footer className="footnote">Portfolio Tracker · Cálculos executados no backend Python · Uso local individual</footer>
        </>}
      </div>
    </main>
  </div>
}

type Mutate = (task: () => Promise<unknown>, success: string) => Promise<boolean>
function Quotes({ portfolioId, assets, busy, mutate }: { portfolioId: number; assets: Asset[]; busy: boolean; mutate: Mutate }) {
  const [id, setId] = useState(assets[0]?.id ?? 0)
  const [rows, setRows] = useState<Quote[]>([])
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)
  const [draft, setDraft] = useState({ date: localDate().slice(0, 10), close: '', dividends: '0', stock_splits: '0' })
  useEffect(() => {
    if (!assets.some(asset => asset.id === id)) setId(assets[0]?.id ?? 0)
  }, [assets, id])
  const base = '/portfolios/' + portfolioId + '/assets/' + id
  useEffect(() => {
    if (!id) return
    const controller = new AbortController(); setError(''); setRows([])
    api<Quote[]>(base + '/history', 'GET', undefined, controller.signal).then(setRows).catch(e => { if (!controller.signal.aborted) setError(message(e)) })
    return () => controller.abort()
  }, [base, id, version])
  if (!assets.length) return <div className="panel empty">Registre uma transação para adicionar cotações ao ativo.</div>
  return <section className="panel"><div className="section-heading"><div><h2>Histórico de cotações</h2><p>Adicione preços manualmente ou atualize pelo Yahoo Finance.</p></div><label>Ativo<select value={id} disabled={busy} onChange={e => setId(Number(e.target.value))}>{assets.map(a => <option key={a.id} value={a.id}>{a.ticker}</option>)}</select></label></div>
    <div className="quote-controls"><form onSubmit={async e => {
      e.preventDefault()
      if (await mutate(() => api(base + '/quote', 'PUT', { date: draft.date, close: Number(draft.close), dividends: Number(draft.dividends), stock_splits: Number(draft.stock_splits) }), 'Cotação salva.')) setVersion(version + 1)
    }}><fieldset disabled={busy}><div className="form-grid quote-grid"><label>Data da cotação<input required type="date" max={localDate().slice(0, 10)} value={draft.date} onChange={e => setDraft({ ...draft, date: e.target.value })} /></label>
      {(['close', 'dividends', 'stock_splits'] as const).map((key, i) => <label key={key}>{['Fechamento', 'Dividendos por unidade', 'Fator de desdobramento'][i]}<input required type="number" min="0" step="any" value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /></label>)}
    </div><div className="form-footer"><span>Dividendos e desdobramentos são armazenados, sem aplicação nas fórmulas legadas.</span><button className="button primary">Salvar cotação</button></div></fieldset></form>
    <button className="button outline" disabled={busy} onClick={async () => {
      if (await mutate(() => api(base + '/refresh', 'POST'), 'Histórico atualizado; preços manuais preservados.')) setVersion(version + 1)
    }}>{busy ? 'Processando…' : 'Atualizar pelo Yahoo Finance'}</button></div>
    {error && <div role="alert" className="alert error">{error}</div>}
    {!rows.length ? <div className="empty">Ainda não há cotações para este ativo.</div> : <div className="table-wrap"><table><thead><tr><th>Data</th><th>Fechamento</th><th>Dividendos</th><th>Desdobramento</th><th>Fonte</th></tr></thead><tbody>{[...rows].reverse().slice(0, 100).map(q => <tr key={q.date}><td>{dateLabel(q.date)}</td><td>{fmt(q.close, 4)}</td><td>{fmt(q.dividends, 4)}</td><td>{fmt(q.stock_splits)}</td><td>{q.source}</td></tr>)}</tbody></table><p className="table-caption">Mostrando as {Math.min(rows.length, 100)} cotações mais recentes de {rows.length}.</p></div>}
  </section>
}

function PerformancePanel({ portfolioId, overview }: { portfolioId: number; overview: Overview }) {
  const [index, setIndex] = useState(0)
  const [rows, setRows] = useState<Performance[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const p = overview.positions[index]
  useEffect(() => {
    if (index >= overview.positions.length) setIndex(0)
  }, [index, overview.positions.length])
  const assetId = overview.assets.find(a => a.ticker === p?.asset)?.id
  useEffect(() => {
    setRows([]); setError('')
    if (!p || !assetId) return
    const controller = new AbortController(); setLoading(true)
    const params = new URLSearchParams({ asset_id: String(assetId), broker: p.broker, allocation_class: p.allocation_class })
    api<Performance[]>('/portfolios/' + portfolioId + '/performance?' + params, 'GET', undefined, controller.signal)
      .then(setRows).catch(e => { if (!controller.signal.aborted) setError(message(e)) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [portfolioId, assetId, p])
  return <section className="panel"><div className="section-heading"><div><h2>Evolução do ganho por posição</h2><p>Ganho realizado + ganho não realizado, conforme a fórmula original.</p></div>
    <label>Posição<select value={index} onChange={e => setIndex(Number(e.target.value))}>{overview.positions.map((pos, i) => <option key={i} value={i}>{pos.asset} · {pos.broker} · {pos.allocation_class}</option>)}</select></label></div>
    <div className="method-note">O percentual acumulado divide o ganho pelas compras acumuladas. A variação diária compara ganhos; não representa retorno diário da carteira.</div>
    {error && <div role="alert" className="alert error">{error}</div>}
    {loading ? <div className="empty">Carregando histórico…</div> : !rows.length ? <div className="empty">Adicione cotações para visualizar o histórico desta posição.</div> : <>
      <GainChart rows={rows} />
      <div className="table-wrap"><table><thead><tr><th>Data</th><th>Ganho realizado</th><th>Ganho não realizado</th><th>Ganho total</th><th>Ganho / compras</th><th>Variação do ganho</th></tr></thead><tbody>{[...rows].reverse().slice(0, 100).map(r => <tr key={r.date}><td>{dateLabel(r.date)}</td><td>{fmt(r.realized_gain)}</td><td>{fmt(r.unrealized_gain)}</td><td>{fmt(r.total_gain)}</td><td>{fmt(r.accumulated_profitability_pct)}%</td><td>{fmt(r.daily_profitability_pct)}%</td></tr>)}</tbody></table></div>
    </>}
  </section>
}

function GainChart({ rows }: { rows: Performance[] }) {
  const values = rows.map(r => r.total_gain), low = Math.min(0, ...values), high = Math.max(0, ...values)
  const span = high - low || 1
  const y = (n: number) => 160 - (n - low) / span * 125
  const points = rows.map((r, i) => (55 + i / Math.max(rows.length - 1, 1) * 690) + ',' + y(r.total_gain)).join(' ')
  return <div className="chart"><svg viewBox="0 0 800 205" role="img" aria-label="Evolução histórica do ganho total">
    {[low, (high + low) / 2, high].map((v, i) => <g key={i}><line x1="55" x2="745" y1={y(v)} y2={y(v)} stroke="#e6ece8" /><text x="48" y={y(v) + 4} textAnchor="end">{fmt(v, 0)}</text></g>)}
    <polyline points={points} fill="none" stroke="#27755b" strokeWidth="2.5" />
    {rows.length === 1 && <circle cx="55" cy={y(rows[0].total_gain)} r="4" fill="#27755b" />}
    <text x="55" y="190">{dateLabel(rows[0].date)}</text><text x="745" y="190" textAnchor="end">{dateLabel(rows[rows.length - 1].date)}</text>
  </svg></div>
}
