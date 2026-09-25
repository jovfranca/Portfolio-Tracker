import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, type Portfolio, type Overview, type Transaction, type Performance, type Quote, type Asset, type Numeric, type CatalogInstrument, type CorporateEvent, type Activity } from './api'
import TransactionImportPage from './TransactionImportPage'
import InstrumentPicker from './InstrumentPicker'

const tabPaths: Record<string, string> = { 'Posições': '/', 'Transações': '/transactions', 'Cotações': '/quotes', 'Desempenho': '/performance', 'Catálogo': '/catalog' }
const currentPath = () => window.location.hash.slice(1) || '/'

const fmt = (value: Numeric | null | undefined, digits = 2) => value == null ? '—' : Number(value).toLocaleString('pt-BR', { maximumFractionDigits: digits, minimumFractionDigits: digits })
const localDate = () => {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
const dateLabel = (value: string | null) => value ? value.slice(0, 10).split('-').reverse().join('/') : 'Sem cotação'
const message = (error: unknown) => error instanceof Error ? error.message : 'Não foi possível concluir.'
type Draft = Omit<Transaction, 'id' | 'portfolio_id' | 'fx_rate' | 'instrument_id' | 'transaction_currency_locked'> & {
  instrument_id: number | null; fx_rate: Numeric | ''
}
const emptyDraft = (): Draft => ({ trade_date: localDate().slice(0, 10), settlement_date: localDate().slice(0, 10),
  type: 'Buy', asset: '', instrument_id: null, broker: '', allocation_class: '', transaction_currency: 'BRL', fx_rate: '',
  quantity: 1, price: 0, brokerage_fee: 0, other_fees: 0, notes: '' })

export default function App() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [path, setPath] = useState(currentPath)
  const importing = path === '/transactions/import'
  const cataloging = path === '/catalog'
  const tab = importing ? 'Transações' : Object.keys(tabPaths).find(key => tabPaths[key] === path) ?? 'Posições'
  useEffect(() => {
    const onHashChange = () => setPath(currentPath())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [noticePartial, setNoticePartial] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [listedCurrency, setListedCurrency] = useState<string | null>(null)
  const lockedCurrency = listedCurrency
  const [editing, setEditing] = useState<number | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [portfolioName, setPortfolioName] = useState('')
  const [newPortfolio, setNewPortfolio] = useState(false)
  const [query, setQuery] = useState('')
  const [showClosed, setShowClosed] = useState(false)
  const [currencyDraft, setCurrencyDraft] = useState('BRL')
  const selectedPortfolio = portfolios.find(p => p.id === selected)
  useEffect(() => { setCurrencyDraft(selectedPortfolio?.display_currency ?? 'BRL') }, [selected, selectedPortfolio?.display_currency])

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
    const [data, txs, updatedPortfolios] = await Promise.all([
      api<Overview>(base + '/overview', 'GET', undefined, signal),
      api<Transaction[]>(base + '/transactions', 'GET', undefined, signal),
      api<Portfolio[]>('/portfolios', 'GET', undefined, signal),
    ])
    setOverview(data); setTransactions(txs); setPortfolios(updatedPortfolios)
  }, [selected])

  useEffect(() => {
    setOverview(null); setTransactions([]); setDraft(emptyDraft()); setListedCurrency(null); setEditing(null); setFormOpen(false); setQuery('')
    if (selected === null) return
    const controller = new AbortController()
    setLoading(true); setError('')
    reload(controller.signal).catch(e => {
      if (!controller.signal.aborted) setError(message(e))
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [selected, reload])

  async function mutate(task: () => Promise<unknown>, success: string) {
    setBusy(true); setError(''); setNotice(''); setNoticePartial(false)
    try {
      const result = await task()
      await reload()
      const partial = typeof result === 'object' && result !== null && 'complete' in result && result.complete === false
      setNoticePartial(partial)
      setNotice(partial && 'message' in result && typeof result.message === 'string' ? result.message : success)
      return true
    }
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

  async function saveDisplayCurrency(e: FormEvent) {
    e.preventDefault()
    if (!selectedPortfolio || currencyDraft === selectedPortfolio.display_currency) return
    await mutate(async () => {
      const updated = await api<Portfolio>('/portfolios/' + selectedPortfolio.id, 'PUT', {
        name: selectedPortfolio.name, display_currency: currencyDraft.toUpperCase(),
      })
      setPortfolios(current => current.map(p => p.id === updated.id ? updated : p))
      return updated
    }, 'Moeda de exibição atualizada.')
  }

  async function saveTransaction(e: FormEvent) {
    e.preventDefault()
    if (!draft.instrument_id) {
      setError('Selecione um instrumento antes de salvar.')
      return
    }
    const url = '/portfolios/' + selected + '/transactions' + (editing === null ? '' : '/' + editing)
    const payload = { ...draft, fx_rate: draft.fx_rate === '' ? null : draft.fx_rate }
    if (await mutate(() => api(url, editing === null ? 'POST' : 'PUT', payload), 'Transação salva. Posições recalculadas.')) {
      setDraft(emptyDraft()); setEditing(null); setFormOpen(false)
    }
  }
  function edit(tx: Transaction) {
    const { id, portfolio_id: _portfolioId, transaction_currency_locked: currencyLocked, ...values } = tx
    setDraft({ ...values, fx_rate: values.fx_rate ?? '' }); setListedCurrency(currencyLocked ? values.transaction_currency : null); setEditing(id); setFormOpen(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const filteredPositions = overview?.positions.filter(p => (showClosed || Number(p.quantity) !== 0) && [p.asset, p.allocation_class].join(' ').toLowerCase().includes(query.toLowerCase())) ?? []

  return <div className="app">
    <aside className="sidebar">
      <a className="brand" href="/"><span className="brand-icon">P<span>↗</span></span><span>portfolio<span className="brand-sub">TRACKER</span></span></a>
      <div className="nav-label">MEU PATRIMÔNIO</div>
      {['Posições', 'Transações', 'Cotações', 'Desempenho', 'Catálogo'].map((item, i) =>
        <button className={'nav-item ' + (tab === item ? 'active' : '')} key={item} onClick={() => { window.location.hash = tabPaths[item] }}>
          <span className="nav-symbol" aria-hidden="true">{['◫', '⇄', '⌁', '↗', '◎'][i]}</span>{item}
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
          {importing ? <a className="button outline" href="#/transactions">← Voltar para Transações</a> : !cataloging && <div className="page-actions">
            {tab === 'Transações' && <button className="button outline" disabled={selected === null || busy || loading} onClick={() => { setFormOpen(false); window.location.hash = '/transactions/import' }}>Importar transações</button>}
            <button className="button primary" disabled={selected === null || busy || loading} onClick={() => { setDraft(emptyDraft()); setListedCurrency(null); setEditing(null); setFormOpen(!formOpen) }}>+ Nova transação</button>
          </div>}
        </div>
        {error && <div role="alert" className="alert error">{error} <button className="button quiet" disabled={busy} onClick={() => void loadPortfolios().then(() => reload()).catch(e => setError(message(e)))}>Tentar novamente</button></div>}
        {notice && <div role="status" className={'alert ' + (noticePartial ? 'warning' : 'success')}>{notice}</div>}
        {(newPortfolio || (!loading && !portfolios.length && !error)) && <form className="panel inline-form" onSubmit={createPortfolio}>
          <div><h2>Comece pela sua carteira</h2><p>Crie um espaço para organizar suas transações e posições.</p></div>
          <label>Nome da carteira<input required maxLength={120} value={portfolioName} onChange={e => setPortfolioName(e.target.value)} placeholder="Ex.: Investimentos pessoais" /></label>
          <button className="button primary" disabled={busy}>Criar carteira</button>
        </form>}
        {formOpen && !importing && !cataloging && <form className="panel transaction-form" onSubmit={saveTransaction}>
          <div className="section-heading"><h2>{editing === null ? 'Registrar transação' : 'Editar transação'}</h2><button type="button" className="button quiet" disabled={busy} onClick={() => setFormOpen(false)}>Fechar</button></div>
          <fieldset disabled={busy}>
            <div className="form-grid">
              <label>Operação<select value={draft.type} onChange={e => setDraft({ ...draft, type: e.target.value as 'Buy' | 'Sell' })}><option value="Buy">Compra</option><option value="Sell">Venda</option></select></label>
              <label>Data da negociação<input required type="date" max={localDate().slice(0, 10)} value={draft.trade_date} onChange={e => setDraft({ ...draft, trade_date: e.target.value })} /></label>
              <label>Data da liquidação<input required type="date" min={draft.trade_date} value={draft.settlement_date} onChange={e => setDraft({ ...draft, settlement_date: e.target.value })} /></label>
              <label>Instrumento<input readOnly={draft.instrument_id !== null} required maxLength={40} value={draft.asset} onChange={e => setDraft({ ...draft, asset: e.target.value, instrument_id: null })} placeholder="Ex.: PETR4, Apple ou BTC" /></label>
              {draft.instrument_id === null ? <InstrumentPicker query={draft.asset} onSelect={item => {
                setListedCurrency(item.asset_type === 'STOCK' || item.asset_type === 'ETF' ? item.currency : null)
                setDraft(current => {
                  const currency = (item.asset_type === 'STOCK' || item.asset_type === 'ETF')
                    ? item.currency ?? current.transaction_currency
                    : (item.is_custom ? item.currency : null) ?? current.transaction_currency
                  return { ...current, instrument_id: item.instrument_id, asset: item.symbol, transaction_currency: currency,
                    fx_rate: currency === current.transaction_currency ? current.fx_rate : '' }
                })
              }} /> : <div className="selected-instrument wide"><span>Instrumento selecionado: <strong>{draft.asset}</strong></span><button type="button" className="button quiet" onClick={() => { setDraft({ ...draft, instrument_id: null, asset: '' }); setListedCurrency(null) }}>Trocar ativo</button></div>}
              <label>Corretora<input required maxLength={120} value={draft.broker} onChange={e => setDraft({ ...draft, broker: e.target.value })} /></label>
              <label>Classe de alocação<input required maxLength={120} value={draft.allocation_class} onChange={e => setDraft({ ...draft, allocation_class: e.target.value })} placeholder="Ex.: Ações Brasil" /></label>
              <label>Moeda da transação<input disabled={!!lockedCurrency} required maxLength={3} pattern="[A-Za-z]{3}" value={draft.transaction_currency} onChange={e => { const currency = e.target.value.toUpperCase(); setDraft({ ...draft, transaction_currency: currency, fx_rate: currency === draft.transaction_currency ? draft.fx_rate : '' }) }} placeholder="BRL" /></label>
              <label>Taxa FX<input type="number" min="0.000000000001" step="any" value={draft.fx_rate} disabled={draft.transaction_currency === 'BRL'} onChange={e => setDraft({ ...draft, fx_rate: e.target.value })} placeholder={draft.transaction_currency === 'BRL' ? '1' : 'Automática'} /></label>
              {([['quantity', 'Quantidade'], ['price', 'Preço unitário'], ['brokerage_fee', 'Corretagem'], ['other_fees', 'Outras taxas']] as const).map(([key, label]) => <label key={key}>{label}<input required type="number" min={key === 'quantity' ? '0.000000000001' : '0'} step="any" value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value } as Draft)} /></label>)}
              <label className="wide">Observações<input maxLength={5000} value={draft.notes} onChange={e => setDraft({ ...draft, notes: e.target.value })} /></label>
            </div>
            <div className="form-footer"><span>FX vazio usa a taxa histórica da data de liquidação; o valor salvo não muda depois.</span><button className="button primary" disabled={!draft.instrument_id}>{busy ? 'Salvando…' : 'Salvar transação'}</button></div>
          </fieldset>
        </form>}
        {loading && <div className="panel empty" role="status">Carregando sua carteira…</div>}
        {importing && <TransactionImportPage key={selected} portfolioId={selected} portfolioName={portfolios.find(p => p.id === selected)?.name ?? ''} busy={busy || loading} mutate={mutate} />}
        {cataloging && <CatalogPage />}
        {!importing && !cataloging && !loading && overview && <>
          <form className="panel inline-form" onSubmit={saveDisplayCurrency}>
            <label>Moeda de exibição<input value={currencyDraft} onChange={e => setCurrencyDraft(e.target.value.toUpperCase())} list="reporting-currencies" minLength={3} maxLength={3} pattern="[A-Za-z]{3}" required /></label>
            <datalist id="reporting-currencies"><option value="BRL" /><option value="USD" /><option value="EUR" /></datalist>
            <button className="button outline" disabled={busy || currencyDraft === selectedPortfolio?.display_currency}>Aplicar moeda</button>
          </form>
          <div className="method-note">Histórico: {overview.summary.history_status === 'pending' ? 'consolidação pendente' : overview.summary.history_status === 'complete' ? 'consolidado' : 'incompleto'}{overview.summary.dirty_from ? ' desde ' + dateLabel(overview.summary.dirty_from) : ''}. <button className="button outline" disabled={busy} onClick={() => void mutate(() => api('/portfolios/' + selected + '/consolidate', 'POST'), 'Carteira consolidada.')}>{busy ? 'Consolidando…' : 'Consolidar carteira'}</button></div>
          <div className="metrics">
            <article className="metric featured"><span>Valor das posições · {overview.summary.display_currency}</span><strong>{fmt(overview.summary.total_value)}</strong><small>{overview.summary.missing_fx.length ? 'FX indisponível: ' + overview.summary.missing_fx.join(', ') : overview.summary.missing_prices.length ? 'Sem cotação: ' + overview.summary.missing_prices.join(', ') : 'Total convertido na data das cotações'}</small></article>
            <article className="metric"><span>Ativos acompanhados</span><strong>{overview.summary.assets.toString().padStart(2, '0')}</strong><small>{overview.summary.positions} posições consolidadas</small></article>
            <article className="metric"><span>Operações registradas</span><strong>{overview.summary.transactions.toString().padStart(2, '0')}</strong><small>Compras e vendas persistidas</small></article>
          </div>
          <div className="method-note"><span>i</span> {overview.methodology} {overview.summary.missing_cost_fx.length ? 'FX histórico indisponível para custo: ' + overview.summary.missing_cost_fx.join(', ') + '. ' : ''}Renda corporativa: {Object.keys(overview.summary.income_by_currency).length ? Object.entries(overview.summary.income_by_currency).map(([currency, total]) => currency + ' ' + fmt(total)).join(' · ') : 'nenhuma'}.</div>
          {tab === 'Posições' && <section className="panel">
            <div className="section-heading"><div><h2>Composição da carteira</h2><p>Uma posição por instrumento.</p></div><label className="search"><span className="sr-only">Filtrar posições</span><input placeholder="Buscar ativo ou classe…" value={query} onChange={e => setQuery(e.target.value)} /></label></div>
            <label><input type="checkbox" checked={showClosed} onChange={e => setShowClosed(e.target.checked)} /> Mostrar posições encerradas</label>
            {!overview.positions.length ? <div className="empty"><div className="empty-icon">↗</div><h3>Sua carteira começa aqui</h3><p>Registre uma compra para acompanhar quantidade, preço médio e evolução.</p></div> :
              <div className="table-wrap"><table><thead><tr><th>Ativo / classe</th><th>Quantidade</th><th>Preço médio / custo</th><th>Cotação</th><th>Valor atual</th><th>Renda bruta</th><th>Resultado total</th></tr></thead><tbody>{filteredPositions.map(p => <tr key={p.asset_id ?? p.asset}>
                <td><strong>{p.asset}</strong><small>{p.allocation_class}</small></td><td>{fmt(p.quantity, 6)}</td><td>{p.display_currency} {fmt(p.display_average_cost, 4)}<small>Custo {p.display_currency} {fmt(p.display_acquisition_cost)}</small>{p.native_currency && p.native_currency !== p.display_currency && p.native_average_cost !== null && <small>{p.native_currency} {fmt(p.native_average_cost, 4)} · custo {fmt(p.native_acquisition_cost)}</small>}</td><td>{p.display_currency} {fmt(p.display_price)}{p.native_currency && p.native_currency === p.quote_currency && p.native_currency !== p.display_currency && <small>{p.native_currency} {fmt(p.current_price)}</small>}<small>{dateLabel(p.price_date)}</small></td><td>{p.display_currency} {fmt(p.display_value)}{p.native_currency && p.native_currency === p.quote_currency && p.native_currency !== p.display_currency && <small>{p.native_currency} {fmt(p.total_value)}</small>}</td>
                <td>{p.display_currency} {fmt(p.gross_income)}</td>
                <td className={Number(p.current_total_gain ?? 0) >= 0 ? 'positive' : 'negative'}>{p.display_currency} {fmt(p.current_total_gain)}<small>{fmt(p.current_accumulated_profitability)}%{p.status !== 'complete' ? ' · cálculo incompleto' : ''}{p.history_behind_transactions ? ' · cotação anterior à última atividade' : ''}</small></td>
              </tr>)}</tbody></table>{!filteredPositions.length && <div className="empty">Nenhuma posição corresponde à busca.</div>}</div>}
          </section>}
          {tab === 'Transações' && <section className="panel"><div className="section-heading"><div><h2>Histórico de operações</h2><p>Editar, excluir ou importar recalcula as posições automaticamente.</p></div></div>
            {!transactions.length ? <div className="empty">Nenhuma transação registrada.</div> : <div className="table-wrap"><table><thead><tr><th>Negociação / liquidação</th><th>Operação</th><th>Ativo / moeda</th><th>Corretora / classe</th><th>Quantidade</th><th>Preço / FX</th><th>Taxas</th><th>Ações</th></tr></thead><tbody>{transactions.map(tx => <tr key={tx.id}><td>{dateLabel(tx.trade_date)}<small>{dateLabel(tx.settlement_date)}</small></td><td><span className={'badge ' + (tx.type === 'Buy' ? 'buy' : 'sell')}>{tx.type === 'Buy' ? 'Compra' : 'Venda'}</span></td><td><strong>{tx.asset}</strong><small>{tx.transaction_currency} · {tx.notes}</small></td><td>{tx.broker}<small>{tx.allocation_class}</small></td><td>{fmt(tx.quantity, 6)}</td><td>{fmt(tx.price, 4)}<small>FX {fmt(tx.fx_rate, 6)}</small></td><td>{fmt(Number(tx.brokerage_fee) + Number(tx.other_fees))}</td><td><div className="row-actions"><button className="button quiet" disabled={busy} onClick={() => edit(tx)}>Editar</button><button className="button danger" disabled={busy} onClick={() => {
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

function CatalogPage() {
  const [items, setItems] = useState<CatalogInstrument[]>([])
  const [error, setError] = useState('')
  useEffect(() => { api<CatalogInstrument[]>('/instruments/catalog').then(setItems).catch(reason => setError(message(reason))) }, [])
  return <section className="panel catalog-page">
    <div className="section-heading"><div><h2>Catálogo de instrumentos</h2><p>Definições controladas pela aplicação. Esta página é somente leitura.</p></div></div>
    {error && <div className="alert error">{error}</div>}
    {!items.length && !error ? <div className="empty">Carregando catálogo…</div> : items.map(item => <article key={item.id}>
      <div><strong>{item.symbol}</strong><span>{item.name}</span><small>{item.asset_type} · {item.exchange || 'Global'} · {item.currency || 'Sem moeda nativa'} · {item.status}</small></div>
      <ul>{item.mappings.map(mapping => <li key={[mapping.provider, mapping.provider_symbol, mapping.quote_currency].join('|')}>
        {mapping.provider} · {mapping.provider_symbol} · {mapping.quote_currency}{mapping.is_primary ? ' · PRINCIPAL' : ''}{!mapping.active ? ' · INATIVO' : ''}
      </li>)}</ul>
    </article>)}
  </section>
}

type Mutate = (task: () => Promise<unknown>, success: string) => Promise<boolean>
function Quotes({ portfolioId, assets, busy, mutate }: { portfolioId: number; assets: Asset[]; busy: boolean; mutate: Mutate }) {
  const quoteAssets = assets.filter((asset, index) => assets.findIndex(item => item.id === asset.id) === index)
  const [id, setId] = useState(quoteAssets[0]?.id ?? 0)
  const [rows, setRows] = useState<Quote[]>([])
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)
  const [draft, setDraft] = useState({ date: localDate().slice(0, 10), close: '' })
  useEffect(() => {
    if (!quoteAssets.some(asset => asset.id === id)) setId(quoteAssets[0]?.id ?? 0)
  }, [assets, id])
  const base = '/portfolios/' + portfolioId + '/assets/' + id
  useEffect(() => {
    if (!id) return
    const controller = new AbortController(); setError(''); setRows([])
    api<Quote[]>(base + '/history', 'GET', undefined, controller.signal).then(setRows).catch(e => { if (!controller.signal.aborted) setError(message(e)) })
    return () => controller.abort()
  }, [base, id, version])
  if (!quoteAssets.length) return <div className="panel empty">Registre uma transação para adicionar cotações ao ativo.</div>
  return <section className="panel"><div className="section-heading"><div><h2>Histórico de cotações</h2><p>Adicione preços manualmente ou atualize pelo Yahoo Finance.</p></div><label>Ativo<select value={id} disabled={busy} onChange={e => setId(Number(e.target.value))}>{quoteAssets.map(a => <option key={a.id} value={a.id}>{a.ticker}</option>)}</select></label></div>
    <div className="quote-controls"><form onSubmit={async e => {
      e.preventDefault()
      if (await mutate(() => api(base + '/quote', 'PUT', { date: draft.date, close: Number(draft.close) }), 'Cotação salva.')) setVersion(version + 1)
    }}><fieldset disabled={busy}><div className="form-grid quote-grid"><label>Data da cotação<input required type="date" max={localDate().slice(0, 10)} value={draft.date} onChange={e => setDraft({ ...draft, date: e.target.value })} /></label>
      <label>Fechamento<input required type="number" min="0" step="any" value={draft.close} onChange={e => setDraft({ ...draft, close: e.target.value })} /></label>
    </div><div className="form-footer"><span>Dividendos e desdobramentos são cadastrados separadamente abaixo.</span><button className="button primary">Salvar cotação</button></div></fieldset></form>
    <button className="button outline" disabled={busy} onClick={async () => {
      if (await mutate(() => api(base + '/refresh', 'POST'), 'Histórico atualizado; preços manuais preservados.')) setVersion(version + 1)
    }}>{busy ? 'Processando…' : 'Atualizar pelo Yahoo Finance'}</button></div>
    {error && <div role="alert" className="alert error">{error}</div>}
    {!rows.length ? <div className="empty">Ainda não há cotações para este ativo.</div> : <div className="table-wrap"><table><thead><tr><th>Data</th><th>Fechamento / moeda</th><th>Dividendos</th><th>Desdobramento</th><th>Fonte</th></tr></thead><tbody>{[...rows].reverse().slice(0, 100).map(q => <tr key={q.date}><td>{dateLabel(q.date)}</td><td>{fmt(q.close, 4)}<small>{q.currency}</small></td><td>{fmt(q.dividends, 4)}</td><td>{fmt(q.stock_splits)}</td><td>{q.source}</td></tr>)}</tbody></table><p className="table-caption">Mostrando as {Math.min(rows.length, 100)} cotações mais recentes de {rows.length}.</p></div>}
    <CorporateActionsPanel key={base} base={base} currency={quoteAssets.find(asset => asset.id === id)?.transaction_currency ?? 'BRL'} busy={busy} mutate={mutate} refreshVersion={version} />
  </section>
}

const eventLabels: Record<CorporateEvent['event_type'], string> = {
  STOCK_SPLIT: 'Desdobramento', REVERSE_SPLIT: 'Grupamento', DIVIDEND: 'Dividendo',
  JCP: 'JCP', AMORTIZATION: 'Amortização',
}
type EventDraft = {
  event_type: CorporateEvent['event_type']; effective_date: string; payment_date: string;
  amount_per_unit: string; conversion_factor: string; currency: string; notes: string
}
const emptyEventDraft = (currency: string): EventDraft => ({
  event_type: 'DIVIDEND', effective_date: localDate().slice(0, 10), payment_date: '',
  amount_per_unit: '', conversion_factor: '', currency, notes: '',
})

function CorporateActionsPanel({ base, currency, busy, mutate, refreshVersion }: {
  base: string; currency: string; busy: boolean; mutate: Mutate; refreshVersion: number
}) {
  const [events, setEvents] = useState<CorporateEvent[]>([])
  const [activity, setActivity] = useState<Activity[]>([])
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState<EventDraft>(() => emptyEventDraft(currency))
  const split = draft.event_type === 'STOCK_SPLIT' || draft.event_type === 'REVERSE_SPLIT'
  useEffect(() => {
    const controller = new AbortController(); setError('')
    Promise.all([
      api<CorporateEvent[]>(base + '/corporate-events', 'GET', undefined, controller.signal),
      api<Activity[]>(base + '/activity', 'GET', undefined, controller.signal),
    ]).then(([eventRows, activityRows]) => { setEvents(eventRows); setActivity(activityRows) })
      .catch(reason => { if (!controller.signal.aborted) setError(message(reason)) })
    return () => controller.abort()
  }, [base, version, refreshVersion])

  function reset() { setEditing(null); setDraft(emptyEventDraft(currency)) }
  function editEvent(event: CorporateEvent) {
    setEditing(event.id)
    setDraft({
      event_type: event.event_type, effective_date: event.effective_date,
      payment_date: event.payment_date ?? '', amount_per_unit: event.amount_per_unit == null ? '' : String(event.amount_per_unit),
      conversion_factor: event.conversion_factor == null ? '' : String(event.conversion_factor),
      currency: event.currency ?? currency, notes: event.notes,
    })
  }
  async function saveEvent(e: FormEvent) {
    e.preventDefault()
    const payload = {
      event_type: draft.event_type, effective_date: draft.effective_date,
      payment_date: draft.payment_date || null, notes: draft.notes,
      amount_per_unit: split ? null : draft.amount_per_unit,
      conversion_factor: split ? draft.conversion_factor : null,
      currency: split ? null : draft.currency,
    }
    const path = base + '/corporate-events' + (editing === null ? '' : '/' + editing)
    if (await mutate(() => api(path, editing === null ? 'POST' : 'PUT', payload), 'Evento corporativo salvo.')) {
      reset(); setVersion(value => value + 1)
    }
  }

  return <>
    <div className="section-heading"><div><h2>Eventos corporativos</h2><p>Eventos manuais são privados desta carteira; eventos do provedor são compartilhados pelo instrumento.</p></div></div>
    <form className="quote-controls" onSubmit={saveEvent}><fieldset disabled={busy}><div className="form-grid quote-grid">
      <label>Tipo<select value={draft.event_type} onChange={e => setDraft({ ...draft, event_type: e.target.value as CorporateEvent['event_type'], amount_per_unit: '', conversion_factor: '' })}>{Object.entries(eventLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Data efetiva<input required type="date" max={localDate().slice(0, 10)} value={draft.effective_date} onChange={e => setDraft({ ...draft, effective_date: e.target.value })} /></label>
      {split ? <label>Fator de conversão<input required type="number" min="0.000000000001" step="any" value={draft.conversion_factor} onChange={e => setDraft({ ...draft, conversion_factor: e.target.value })} /></label> : <>
        <label>Valor por unidade<input required type="number" min="0" step="any" value={draft.amount_per_unit} onChange={e => setDraft({ ...draft, amount_per_unit: e.target.value })} /></label>
        <label>Moeda<input required maxLength={3} pattern="[A-Za-z]{3}" value={draft.currency} onChange={e => setDraft({ ...draft, currency: e.target.value.toUpperCase() })} /></label>
        <label>Data de pagamento<input type="date" min={draft.effective_date} value={draft.payment_date} onChange={e => setDraft({ ...draft, payment_date: e.target.value })} /></label>
      </>}
      <label className="wide">Observações<input maxLength={5000} value={draft.notes} onChange={e => setDraft({ ...draft, notes: e.target.value })} /></label>
    </div><div className="form-footer"><span>Eventos na data efetiva são aplicados antes das negociações do mesmo dia.</span><div className="row-actions">{editing !== null && <button type="button" className="button quiet" onClick={reset}>Cancelar</button>}<button className="button primary">{editing === null ? 'Adicionar evento' : 'Salvar alteração'}</button></div></div></fieldset></form>
    {error && <div role="alert" className="alert error">{error}</div>}
    {!!events.length && <div className="table-wrap"><table><thead><tr><th>Data / tipo</th><th>Definição</th><th>Efeito na carteira</th><th>Origem</th><th>Ações</th></tr></thead><tbody>{[...events].reverse().map(event => <tr key={event.origin + '-' + event.id}>
      <td>{dateLabel(event.effective_date)}<small>{eventLabels[event.event_type]}</small></td><td>{event.conversion_factor != null ? 'Fator ' + fmt(event.conversion_factor, 6) : fmt(event.amount_per_unit, 6) + ' ' + event.currency}</td><td>{event.gross_amount != null ? 'Bruto ' + fmt(event.gross_amount, 4) + ' ' + event.currency : fmt(event.eligible_quantity, 6) + ' → posição ajustada'}</td><td>{event.origin === 'manual' ? 'Manual' : event.source}</td><td>{event.origin === 'manual' && <div className="row-actions"><button className="button quiet" onClick={() => editEvent(event)}>Editar</button><button className="button danger" onClick={() => {
        if (window.confirm('Excluir este evento e recalcular as posições?')) void mutate(() => api(base + '/corporate-events/' + event.id, 'DELETE'), 'Evento excluído.').then(ok => { if (ok) { reset(); setVersion(value => value + 1) } })
      }}>Excluir</button></div>}</td>
    </tr>)}</tbody></table></div>}
    <div className="section-heading"><div><h2>Atividade do ativo</h2><p>Leitura cronológica unificada; transações e eventos continuam armazenados separadamente.</p></div></div>
    {!activity.length ? <div className="empty">Nenhuma atividade registrada.</div> : <div className="table-wrap"><table><thead><tr><th>Data</th><th>Atividade</th><th>Quantidade elegível</th><th>Valor / fator</th><th>Origem</th></tr></thead><tbody>{[...activity].sort((a, b) => b.date.localeCompare(a.date) || (a.kind === b.kind ? 0 : a.kind === 'CORPORATE_ACTION' ? -1 : 1)).map(row => row.kind === 'TRANSACTION' ? <tr key={'transaction-' + row.id}>
      <td>{dateLabel(row.date)}</td><td>{row.type === 'Buy' ? 'Compra' : 'Venda'}</td><td>{fmt(row.quantity, 6)}</td><td>{fmt(row.price, 4)} {row.currency}</td><td>{row.broker}</td>
    </tr> : <tr key={'event-' + row.origin + '-' + row.id}>
      <td>{dateLabel(row.date)}</td><td>{eventLabels[row.event_type]}</td><td>{fmt(row.eligible_quantity, 6)}</td><td>{row.conversion_factor != null ? 'Fator ' + fmt(row.conversion_factor, 6) : fmt(row.gross_amount, 4) + ' ' + row.currency}</td><td>{row.origin === 'manual' ? 'Manual' : row.source}</td>
    </tr>)}</tbody></table></div>}
  </>
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
  const assetId = p?.asset_id
  useEffect(() => {
    setRows([]); setError('')
    if (!p || !assetId) return
    const controller = new AbortController(); setLoading(true)
    const params = new URLSearchParams({ asset_id: String(assetId) })
    api<Performance[]>('/portfolios/' + portfolioId + '/performance?' + params, 'GET', undefined, controller.signal)
      .then(setRows).catch(e => { if (!controller.signal.aborted) setError(message(e)) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [portfolioId, assetId, p])
  return <section className="panel"><div className="section-heading"><div><h2>Desempenho da posição · {overview.summary.display_currency}</h2><p>Resultado com renda bruta e retorno ponderado no tempo.</p></div>
    <label>Posição<select value={index} onChange={e => setIndex(Number(e.target.value))}>{overview.positions.map((pos, i) => <option key={i} value={i}>{pos.asset}</option>)}</select></label></div>
    {overview.summary.history_status !== 'complete' && <div className="method-note">Histórico {overview.summary.history_status === 'pending' ? 'pendente de consolidação' : 'incompleto'}. Execute “Consolidar carteira” para atualizar.</div>}
    {error && <div role="alert" className="alert error">{error}</div>}
    {loading ? <div className="empty">Carregando histórico…</div> : !rows.length ? <div className="empty">Consolide a carteira para gerar o histórico desta posição.</div> : <>
      {rows.some(r => r.total_gain !== null) && <GainChart rows={rows.filter(r => r.total_gain !== null)} />}
      <div className="table-wrap"><table><thead><tr><th>Data</th><th>Quantidade</th><th>Custo</th><th>Valor</th><th>Realizado</th><th>Não realizado</th><th>Renda bruta</th><th>Resultado total</th><th>Retorno acumulado</th><th>Status</th></tr></thead><tbody>{[...rows].reverse().slice(0, 100).map(r => <tr key={r.date}><td>{dateLabel(r.date)}</td><td>{fmt(r.quantity, 6)}</td><td>{fmt(r.remaining_acquisition_cost)}</td><td>{fmt(r.market_value)}</td><td>{fmt(r.realized_gain)}</td><td>{fmt(r.unrealized_gain)}</td><td>{fmt(r.gross_income)}</td><td>{fmt(r.total_gain)}</td><td>{fmt(r.cumulative_return_pct)}%</td><td>{r.status === 'complete' ? 'Completo' : 'Incompleto'}</td></tr>)}</tbody></table></div>
    </>}
  </section>
}

function GainChart({ rows }: { rows: Performance[] }) {
  const values = rows.map(r => Number(r.total_gain)), low = Math.min(0, ...values), high = Math.max(0, ...values)
  const span = high - low || 1
  const y = (n: number) => 160 - (n - low) / span * 125
  const points = rows.map((r, i) => (55 + i / Math.max(rows.length - 1, 1) * 690) + ',' + y(Number(r.total_gain))).join(' ')
  return <div className="chart"><svg viewBox="0 0 800 205" role="img" aria-label="Evolução histórica do ganho total">
    {[low, (high + low) / 2, high].map((v, i) => <g key={i}><line x1="55" x2="745" y1={y(v)} y2={y(v)} stroke="#e6ece8" /><text x="48" y={y(v) + 4} textAnchor="end">{fmt(v, 0)}</text></g>)}
    <polyline points={points} fill="none" stroke="#27755b" strokeWidth="2.5" />
    {rows.length === 1 && <circle cx="55" cy={y(Number(rows[0].total_gain))} r="4" fill="#27755b" />}
    <text x="55" y="190">{dateLabel(rows[0].date)}</text><text x="745" y="190" textAnchor="end">{dateLabel(rows[rows.length - 1].date)}</text>
  </svg></div>
}
