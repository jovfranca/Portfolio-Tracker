import { useCallback, useEffect, useState } from 'react'
import { api, type AuthState, type Space, type Portfolio, type Overview, type Transaction, type FixedIncomeLot, type FixedIncomeMovement, type InstrumentSearchResult } from './api'
import AppShell from './AppShell'
import TransactionForm from './TransactionForm'
import TransactionImportPage from './TransactionImportPage'
import FixedIncomeForm from './FixedIncomeForm'
import FixedIncomeMovementForm from './FixedIncomeMovementForm'
import OverviewPage from './OverviewPage'
import PositionsPage from './PositionsPage'
import PositionDetailPage from './PositionDetailPage'
import FixedIncomeDetailPage from './FixedIncomeDetailPage'
import TransactionsPage from './TransactionsPage'
import TransactionDetailPage from './TransactionDetailPage'
import PerformancePage from './PerformancePage'
import MarketDataPage from './MarketDataPage'
import InstrumentsPage from './InstrumentsPage'
import PortfoliosPage from './PortfoliosPage'
import SettingsPage from './SettingsPage'
import AccountPage from './AccountPage'
import InvitationPage from './InvitationPage'
import { Link, navigate, useRoute } from './navigation'
import { EmptyState, ErrorState, LoadingState, message, Modal, PageHeader } from './ui'
import type { AddAction } from './text'

type FormState = { action: Exclude<AddAction, 'import'>; lotId?: number; movement?: FixedIncomeMovement; transaction?: Transaction; instrument?: InstrumentSearchResult }
export default function App({ auth, space, onSwitch, onLogout, onRefresh, onLinked, authError }: { auth: AuthState; space?: Space; onSwitch: (id: number) => void; onLogout: () => void; onRefresh: (preferredSpace?: number) => Promise<void>; onLinked: (auth: AuthState) => void; authError: string }) {
  const route = useRoute(), [path, search = ''] = route.split('?'), query = new URLSearchParams(search)
  const readOnly = !space || space.role === 'VIEWER', storageKey = 'quintrion-portfolio:' + auth.user.id + ':' + space?.id
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]), [selected, setSelected] = useState<number | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null), [transactions, setTransactions] = useState<Transaction[]>([]), [lots, setLots] = useState<FixedIncomeLot[]>([])
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState(''), [partial, setPartial] = useState(false), [version, setVersion] = useState(0), [form, setForm] = useState<FormState | null>(null)
  const selectedPortfolio = portfolios.find(p => p.id === selected)
  const [lastUpdate, setLastUpdate] = useState<{ portfolioId: number; at: string } | null>(null)
  const loadPortfolios = useCallback(async (signal?: AbortSignal) => {
    if (!space) { setLoading(false); return }
    const list = await api<Portfolio[]>('/portfolios', 'GET', undefined, signal)
    if (signal?.aborted) return
    const scoped = list.filter(p => p.household_id === undefined || p.household_id === space.id)
    setPortfolios(scoped)
    setSelected(current => scoped.some(p => p.id === current) ? current : scoped.find(p => p.id === Number(localStorage.getItem(storageKey)))?.id ?? scoped[0]?.id ?? null)
    if (!scoped.length) setLoading(false)
  }, [space?.id, storageKey])
  const reload = useCallback(async (signal?: AbortSignal) => {
    if (selected === null) { await loadPortfolios(signal); return }
    const base = '/portfolios/' + selected
    const [data, txs, lotRows, list] = await Promise.all([
      api<Overview>(base + '/overview', 'GET', undefined, signal), api<Transaction[]>(base + '/transactions', 'GET', undefined, signal),
      api<FixedIncomeLot[]>(base + '/fixed-income/lots', 'GET', undefined, signal), api<Portfolio[]>('/portfolios', 'GET', undefined, signal),
    ])
    if (signal?.aborted) return
    setOverview(data); setTransactions(txs); setLots(lotRows); setPortfolios(list.filter(p => p.household_id === undefined || p.household_id === space?.id))
  }, [selected, space?.id, loadPortfolios])
  useEffect(() => {
    const controller = new AbortController()
    void loadPortfolios(controller.signal).catch(e => { if (!controller.signal.aborted) { setError(message(e)); setLoading(false) } })
    return () => controller.abort()
  }, [loadPortfolios])
  useEffect(() => {
    setOverview(null); setTransactions([]); setLots([]); setForm(null); setNotice(''); setError('')
    if (selected === null) return
    localStorage.setItem(storageKey, String(selected))
    const controller = new AbortController(); setLoading(true)
    void reload(controller.signal).catch(e => { if (!controller.signal.aborted) setError(message(e)) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [selected, reload, storageKey])
  const routePortfolio = Number(path.match(/^\/portfolios\/(\d+)\/settings/)?.[1])
  useEffect(() => { if (!busy && routePortfolio && portfolios.some(p => p.id === routePortfolio) && routePortfolio !== selected) setSelected(routePortfolio) }, [routePortfolio, selected, portfolios, busy])
  useEffect(() => { setForm(null) }, [path])
  async function mutate(task: () => Promise<unknown>, success: string) {
    if (readOnly) { setError('Este espaço permite somente leitura.'); return false }
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await task()
      await reload(); setVersion(value => value + 1)
      const incomplete = typeof result === 'object' && result !== null && 'complete' in result && result.complete === false
      setPartial(incomplete); setNotice(incomplete ? 'Carteira atualizada parcialmente. Confira os dados que precisam de atenção.' : success)
      return true
    } catch (e) { setError(message(e)); await reload().catch(() => {}); return false } finally { setBusy(false) }
  }
  function add(action: AddAction, lotId?: number) {
    if (readOnly || selected === null) return
    if (action === 'import') navigate('/transactions/import')
    else setForm({ action, lotId })
  }
  function selectPortfolio(id: number) {
    if (/^\/portfolios\/\d+\/settings/.test(path)) navigate('/portfolios/' + id + '/settings')
    setSelected(id)
  }
  const update = () => { if (selected !== null) void mutate(() => api('/portfolios/' + selected + '/consolidate', 'POST'), 'Carteira atualizada.').then(ok => { if (ok) setLastUpdate({ portfolioId: selected, at: new Date().toISOString() }) }) }
  const edit = (transaction: Transaction) => { if (!readOnly) setForm({ action: 'transaction', transaction }) }
  const editMovement = (movement: FixedIncomeMovement) => { if (!readOnly) setForm({ action: 'contribution', lotId: movement.lot_id, movement }) }
  let content
  if (path.startsWith('/settings/spaces') || path === '/settings') content = <SettingsPage auth={auth} space={space} path={path === '/settings' ? '/settings/spaces' : path} onRefresh={onRefresh} onSwitch={onSwitch} />
  else if (path.startsWith('/account/')) content = <AccountPage auth={auth} tab={path.split('/')[2]} onLinked={onLinked} />
  else if (path.startsWith('/invite/')) {
    let token = path.slice(8)
    try { token = decodeURIComponent(token) } catch { /* A malformed token still receives the invalid-invitation response. */ }
    content = <InvitationPage token={token} onAccepted={onRefresh} />
  }
  else if (path.startsWith('/portfolios')) content = <PortfoliosPage key={path === '/portfolios/new' ? path : path + ':' + portfolios.find(p => p.id === routePortfolio)?.display_currency} portfolios={portfolios} portfolioId={routePortfolio || undefined} creating={path === '/portfolios/new'} space={space} readOnly={readOnly} busy={busy} mutate={mutate} onCreated={p => { setPortfolios(current => [...current.filter(item => item.id !== p.id), p]); setSelected(p.id) }} onSelect={setSelected} onUpdate={update} />
  else if (path.startsWith('/instruments')) content = <InstrumentsPage key={path} lots={lots} instrumentId={path.match(/^\/instruments\/(\d+)$/) ? Number(path.split('/')[2]) : undefined} overview={overview} transactions={transactions} />
  else if (path === '/help') content = <><PageHeader title="Ajuda" /><section className="panel settings-section"><h2>Comece pela carteira</h2><p>Adicione ou importe operações, atualize a carteira e confira os dados pendentes em Dados de mercado. Membros e convites são gerenciados em Configurações → Espaços financeiros.</p></section></>
  else if (loading) content = <LoadingState />
  else if (!selectedPortfolio || !overview) content = <EmptyState action={!readOnly ? <Link className="button primary" href="/portfolios/new">Criar primeira carteira</Link> : <Link href="/settings/spaces">Ver espaços financeiros</Link>}>{error ? 'Não foi possível carregar a carteira.' : 'Nenhuma carteira disponível no espaço financeiro ativo.'}</EmptyState>
  else if (path === '/overview') content = <OverviewPage key={selected} overview={overview} portfolioId={selected!} transactions={transactions} lots={lots} version={version} onAdd={readOnly ? undefined : () => add('transaction')} />
  else if (path === '/positions') content = <PositionsPage overview={overview} lots={lots} onAdd={readOnly ? undefined : () => add('transaction')} onContribute={readOnly ? undefined : id => add('contribution', id)} onRedeem={readOnly ? undefined : id => add('redemption', id)} />
  else if (/^\/positions\/\d+$/.test(path)) content = <PositionDetailPage assetId={Number(path.split('/')[2])} tab={query.get('tab') ?? 'overview'} overview={overview} transactions={transactions} portfolioId={selected!} readOnly={readOnly} busy={busy} version={version} mutate={mutate} onAdd={instrument => setForm({ action: 'transaction', instrument })} onEdit={edit} />
  else if (/^\/fixed-income\/\d+$/.test(path)) content = <FixedIncomeDetailPage busy={busy} onDelete={readOnly ? undefined : m => { if (window.confirm(m.movement_type === 'INITIAL_INVESTMENT' ? 'Excluir a aplicação inicial e o lote? Movimentos futuros podem impedir a exclusão.' : 'Excluir este movimento? Movimentos posteriores podem impedir a exclusão.')) void mutate(() => api(`/portfolios/${selected}/fixed-income/lots/${m.lot_id}/movements/${m.id}`, 'DELETE'), 'Movimento excluído. Atualização da carteira pendente.') }} lot={lots.find(l => l.id === Number(path.split('/')[2]))} onContribute={readOnly ? undefined : id => add('contribution', id)} onRedeem={readOnly ? undefined : id => add('redemption', id)} onEdit={readOnly ? undefined : editMovement} />
  else if (path === '/transactions/import') content = <><PageHeader title="Importar transações" description="Envie, revise, corrija e confirme as operações."><Link className="button outline" href="/transactions">← Voltar para Transações</Link></PageHeader>{readOnly ? <EmptyState>Seu papel permite somente leitura.</EmptyState> : <TransactionImportPage key={selected} portfolioId={selected} portfolioName={selectedPortfolio.name} busy={busy} mutate={mutate} />}</>
  else if (path === '/transactions') content = <TransactionsPage portfolioId={selected!} transactions={transactions} lots={lots} busy={busy} readOnly={readOnly} mutate={mutate} onEdit={edit} onEditMovement={editMovement} onAdd={() => add('transaction')} />
  else if (/^\/transactions\/\d+$/.test(path)) content = <TransactionDetailPage key={path} transaction={transactions.find(t => t.id === Number(path.split('/')[2]))} onEdit={readOnly ? undefined : edit} />
  else if (path === '/performance') content = <PerformancePage portfolioId={selected!} overview={overview} lots={lots} version={version} />
  else if (path === '/data' || path.startsWith('/data/')) content = <MarketDataPage key={path + ':' + selected} tab={path.split('/')[2] ?? 'status'} overview={overview} portfolioId={selected!} readOnly={readOnly} busy={busy} mutate={mutate} version={version} onUpdate={update} />
  else content = <EmptyState action={<Link href="/overview">Abrir visão geral</Link>}>Página não encontrada.</EmptyState>
  return <AppShell path={path} auth={auth} space={space} portfolios={portfolios} selected={selected} overview={overview} busy={busy} loading={loading} updatedAt={lastUpdate?.portfolioId === selected ? lastUpdate.at : undefined} onSelect={selectPortfolio} onSwitch={onSwitch} onLogout={onLogout} onUpdate={update} onAdd={add}>
    {(error || authError) && <ErrorState error={error || authError} retry={() => { setLoading(true); setError(''); void reload().catch(e => setError(message(e))).finally(() => setLoading(false)) }} />}{notice && <div className={'alert ' + (partial ? 'warning' : 'success')} role="status">{notice}{partial && <Link href="/data/status"> Ver status →</Link>}</div>}{content}
    {form && selected !== null && !readOnly && <Modal title={form.transaction || form.movement ? 'Editar operação' : 'Adicionar operação'} onClose={() => { if (!busy) setForm(null) }}>
      {form.action === 'transaction' ? <TransactionForm portfolioId={selected} busy={busy} mutate={mutate} onClose={() => setForm(null)} transaction={form.transaction} instrument={form.instrument} /> : form.action === 'lot' ? <FixedIncomeForm portfolioId={selected} busy={busy} mutate={mutate} onClose={() => setForm(null)} /> : <FixedIncomeMovementForm portfolioId={selected} busy={busy} mutate={mutate} onClose={() => setForm(null)} mode={form.movement ? 'EDIT' : form.action === 'redemption' ? 'REDEMPTION' : 'ADDITIONAL'} initialLotId={form.lotId} editing={form.movement} />}
    </Modal>}
  </AppShell>
}
