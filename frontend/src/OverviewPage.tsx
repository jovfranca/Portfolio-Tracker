import type { Overview, Performance, Transaction, FixedIncomeLot } from './api'
import { Link } from './navigation'
import { movementLabels } from './text'
import { dateLabel, EmptyState, fmt, MetricCard, PageHeader } from './ui'
import { HistoryChart } from './HistoryPanel'
import { useResource } from './useResource'

export function Attention({ overview }: { overview: Overview }) {
  const { summary } = overview
  const issues = [
    ['/data/quotes', 'Cotações ausentes', summary.missing_prices ?? []], ['/data/fx', 'Câmbio ausente', [...(summary.missing_fx ?? []), ...(summary.missing_cost_fx ?? [])]],
    ['/data/corporate-actions', 'Eventos não verificados', summary.missing_actions ?? []],
  ] as const
  return <section className="panel attention"><div className="section-heading"><h2>Atenção aos dados</h2></div>
    {issues.filter(([, , items]) => items.length).map(([href, label, items]) => <Link key={href} href={href}><strong>{label}</strong><small>{items.join(', ')}</small><span aria-hidden="true">→</span></Link>)}
    {overview.fixed_income?.valuation_status && !['none', 'complete'].includes(overview.fixed_income.valuation_status) && <Link href="/data/benchmarks">Renda fixa com avaliação pendente ou incompleta →</Link>}
    {summary.history_status === 'pending' && <Link href="/data/status">Atualização da carteira pendente →</Link>}
    {summary.history_status !== 'complete' && summary.history_status !== 'pending' && <Link href="/data/status">Confira a cobertura do histórico →</Link>}
    {summary.history_status === 'complete' && !issues.some(([, , items]) => items.length) && <p className="table-caption">Nenhuma pendência identificada.</p>}
  </section>
}
export function Allocation({ overview, by }: { overview: Overview; by: 'class' | 'currency' | 'broker' | 'asset' }) {
  // Only group display-currency values already calculated by the backend.
  const grouped = new Map<string, number | null>()
  for (const p of overview.positions) {
    const key = by === 'class' ? p.allocation_class || 'Sem classe' : by === 'currency' ? p.native_currency ?? p.transaction_currency ?? 'Sem moeda' : by === 'broker' ? p.broker || 'Várias corretoras' : p.asset
    const previous = grouped.get(key) ?? 0
    grouped.set(key, p.display_value == null || grouped.has(key) && grouped.get(key) === null ? null : previous + Number(p.display_value))
  }
  const values = [...grouped.entries()].sort((a, b) => (b[1] ?? -1) - (a[1] ?? -1))
  const total = overview.summary.total_value
  return <section className="panel"><div className="section-heading"><h2>Alocação por {by === 'class' ? 'classe' : by === 'currency' ? 'moeda' : by === 'broker' ? 'corretora' : 'ativo'}</h2></div>{!values.length ? <EmptyState>Nenhuma posição registrada.</EmptyState> : <div className="allocation-list">{values.map(([label, value]) => <div key={label}><span>{label}</span><strong>{overview.summary.display_currency} {fmt(value)}</strong><progress aria-label={label} max="100" value={value !== null && total && total > 0 ? value / total * 100 : 0} /><small>{value === null || total == null ? 'Dados incompletos' : total > 0 ? fmt(value / total * 100, 1) + '%' : 'Sem saldo'}</small></div>)}</div>}</section>
}
export default function OverviewPage({ overview, portfolioId, transactions, lots, version, onAdd }: { lots: FixedIncomeLot[]; overview: Overview; portfolioId: number; transactions: Transaction[]; version: number; onAdd?: () => void }) {
  const history = useResource<Performance[]>('/portfolios/' + portfolioId + '/history', version)
  const activity = [...transactions.map(t => ({ key: 'tx' + t.id, date: t.trade_date, href: '/transactions/' + t.id, label: (t.type === 'Buy' ? 'Compra' : 'Venda') + ' · ' + t.asset, broker: t.broker })), ...lots.flatMap(l => l.movements.map(m => ({ key: 'fi' + m.id, date: m.effective_date, href: '/fixed-income/' + l.id, label: (movementLabels[m.movement_type] ?? 'Movimento') + ' · ' + l.instrument_symbol, broker: l.broker })))].sort((a,b) => b.date.localeCompare(a.date)).slice(0,5)
  const last = history.data?.at(-1)
  const currency = overview.summary.display_currency
  return <><PageHeader title="Sua carteira, em um só lugar" description="Acompanhe seu patrimônio, a composição e as atividades recentes." />
    <div className="metrics overview-metrics"><MetricCard featured label={'Patrimônio total · ' + currency} value={fmt(overview.summary.total_value)} context="Valores na moeda de exibição" /><MetricCard label={'Custo de aquisição · ' + currency} value={fmt(overview.summary.acquisition_cost)} context="Valores atuais consolidados" /><MetricCard label={'Resultado acumulado · ' + currency} value={fmt(overview.summary.total_gain)} /><MetricCard label="Retorno acumulado" value={last?.cumulative_return_pct == null ? '—' : fmt(last.cumulative_return_pct) + '%'} context={last && 'Até ' + dateLabel(last.date)} /><MetricCard label={'Rendimentos · ' + currency} value={fmt(overview.summary.gross_income)} /><MetricCard label="Posições" value={overview.summary.positions} /></div>
    {!overview.positions.length && <EmptyState action={onAdd && <button className="button primary" onClick={onAdd}>Adicionar primeira transação</button>}>Sua carteira começa aqui. Adicione ou importe suas operações.</EmptyState>}
    <div className="overview-grid"><section className="panel"><div className="section-heading"><h2>Evolução do patrimônio</h2><Link href="/performance">Ver desempenho →</Link></div>{history.loading ? <p role="status" className="table-caption">Carregando histórico…</p> : history.error ? <p role="alert" className="table-caption">{history.error}</p> : <HistoryChart rows={history.data ?? []} title="Evolução do patrimônio" currency={currency} />}</section><Allocation overview={overview} by="class" /></div>
    <div className="overview-grid"><Allocation overview={overview} by="currency" /><Attention overview={overview} /></div>
    <div className="overview-grid"><section className="panel"><div className="section-heading"><h2>Maiores posições</h2><Link href="/positions">Ver posições →</Link></div><div className="table-wrap"><table><thead><tr><th>Instrumento</th><th>Valor · {currency}</th></tr></thead><tbody>{[...overview.positions].sort((a, b) => Number(b.display_value ?? -1) - Number(a.display_value ?? -1)).slice(0, 5).map(p => <tr key={p.asset_id}><td><Link href={p.position_type === 'FIXED_INCOME' ? '/positions?type=fixed' : '/positions/' + p.asset_id}>{p.asset}</Link></td><td>{fmt(p.display_value)}</td></tr>)}</tbody></table></div></section>
    <section className="panel"><div className="section-heading"><h2>Atividade recente</h2><Link href="/transactions">Ver todas →</Link></div>{!activity.length ? <EmptyState>Nenhuma atividade registrada.</EmptyState> : <ul className="activity-list">{activity.map(a => <li key={a.key}><Link href={a.href}>{a.label}</Link><small>{dateLabel(a.date)} · {a.broker}</small></li>)}</ul>}</section></div>
  </>
}
