import { api, type CatalogInstrument, type Overview, type Transaction, type InstrumentSearchResult } from './api'
import { Link } from './navigation'
import { CorporateActionsPanel, Quotes } from './MarketPanels'
import HistoryPanel from './HistoryPanel'
import { TransactionTable } from './TransactionsPage'
import { dateLabel, EmptyState, fmt, MetricCard, PageHeader, StatusBadge, Tabs, type Mutate } from './ui'
import { useResource } from './useResource'
import { typeLabels } from './text'

export default function PositionDetailPage({ assetId, tab, overview, transactions, portfolioId, readOnly, busy, version, mutate, onAdd, onEdit }: {
  assetId: number; tab: string; overview: Overview; transactions: Transaction[]; portfolioId: number; readOnly: boolean; busy: boolean; version: number;
  mutate: Mutate; onAdd: (instrument: InstrumentSearchResult) => void; onEdit: (tx: Transaction) => void;
}) {
  const p = overview.positions.find(p => p.asset_id === assetId && p.position_type !== 'FIXED_INCOME')
  const instrumentId = p?.instrument_id
  const txs = transactions.filter(t => t.instrument_id === instrumentId)
  const instrument = useResource<CatalogInstrument>(instrumentId ? '/instruments/' + instrumentId : null)
  if (!p) return <EmptyState action={<Link className="button outline" href="/positions">Voltar para posições</Link>}>Posição não encontrada nesta carteira.</EmptyState>
  const base = '/positions/' + assetId
  const items = [['overview', 'Visão geral'], ['performance', 'Desempenho'], ['transactions', 'Transações'], ['events', 'Rendimentos e eventos'], ['data', 'Dados']].map(([key, label]) => [base + '?tab=' + key, label] as const)
  const addInstrument = instrument.data ? { ...instrument.data, status: instrument.data.status as InstrumentSearchResult['status'], instrument_id: instrument.data.id, asset_type: instrument.data.asset_type as InstrumentSearchResult['asset_type'], provider: null, provider_symbol: null } : null
  return <><PageHeader title={p.asset} description={[instrument.data?.name, typeLabels[instrument.data?.asset_type ?? ''] ?? p.allocation_class].filter(Boolean).join(' · ')}>
    <Link className="button outline" href="/positions">← Posições</Link>{!readOnly && addInstrument && <button className="button primary" disabled={busy} onClick={() => onAdd(addInstrument)}>+ Transação neste ativo</button>}
  </PageHeader><div className="detail-context"><StatusBadge status={p.status} /><span>Moeda contábil: {p.native_currency ?? 'Indisponível'}</span><span>Moeda de exibição: {p.display_currency}</span><Link href={'/data/quotes?asset=' + assetId}>Ver cotações / atualizar dados</Link>{instrumentId && <Link href={'/instruments/' + instrumentId}>Abrir instrumento</Link>}</div>
    <div className="metrics"><MetricCard featured label={'Valor atual · ' + p.display_currency} value={fmt(p.display_value)} /><MetricCard label="Quantidade" value={fmt(p.quantity, 6)} /><MetricCard label={'Resultado total · ' + p.display_currency} value={fmt(p.current_total_gain)} context={p.current_accumulated_profitability == null ? 'Retorno indisponível' : fmt(p.current_accumulated_profitability) + '%'} /></div>
    <Tabs items={items} active={base + '?tab=' + tab} />
    {tab === 'overview' && <><section className="panel"><div className="section-heading"><h2>Composição da posição</h2></div><dl className="detail-grid">{[
      ['Custo de aquisição · ' + p.display_currency, fmt(p.display_acquisition_cost)], ['Preço médio · ' + p.display_currency, fmt(p.display_average_cost, 4)], ['Cotação atual · ' + p.display_currency, fmt(p.display_price, 4)],
      ['Custo contábil · ' + (p.native_currency ?? '—'), fmt(p.native_acquisition_cost)], ['Preço médio contábil · ' + (p.native_currency ?? '—'), fmt(p.native_average_cost, 4)], ['Rendimentos · ' + p.display_currency, fmt(p.gross_income)],
    ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></section>
    <section className="panel"><div className="section-heading"><h2>Composição por corretora</h2><p>Custos na moeda contábil: {p.native_currency ?? '—'}</p></div><div className="table-wrap"><table><thead><tr><th>Corretora</th><th>Quantidade</th><th>Custo de aquisição</th><th>Preço médio</th></tr></thead><tbody>{(p.broker_breakdown ?? []).map(b => <tr key={b.broker}><td>{b.broker}</td><td>{fmt(b.quantity, 6)}</td><td>{fmt(b.acquisition_cost)}</td><td>{fmt(b.average_cost, 4)}</td></tr>)}</tbody></table></div></section>
    <HistoryPanel portfolioId={portfolioId} assetId={assetId} version={version} /></>}
    {tab === 'performance' && <HistoryPanel portfolioId={portfolioId} assetId={assetId} version={version} />}
    {tab === 'transactions' && <><p className="method-note">Para alterar a classe atribuída, edite a classe de alocação das transações. As movimentações permanecem a fonte contábil.</p><section className="panel"><TransactionTable transactions={txs} busy={busy} onEdit={readOnly ? undefined : onEdit} onDelete={readOnly ? undefined : tx => { if (window.confirm('Excluir esta transação?')) void mutate(() => api('/portfolios/' + portfolioId + '/transactions/' + tx.id, 'DELETE'), 'Transação excluída. Atualização da carteira pendente.') }} /></section><p className="method-note">Abra a transação para consultar datas, FX salvo e PTAX de compra/venda na liquidação.</p></>}
    {tab === 'events' && <section className="panel"><CorporateActionsPanel base={'/portfolios/' + portfolioId + '/assets/' + assetId} currency={p.native_currency ?? 'BRL'} busy={busy} readOnly={readOnly} mutate={mutate} refreshVersion={version} /></section>}
    {tab === 'data' && <><Quotes assets={overview.assets.filter(a => a.id === assetId)} portfolioId={portfolioId} busy={busy} readOnly={readOnly} mutate={mutate} /><p className="method-note">Última cotação: {dateLabel(p.price_date)} · {p.quote_currency ?? 'Moeda não informada'}. {instrument.data?.aliases?.join(' · ')}</p></>}
  </>
}
