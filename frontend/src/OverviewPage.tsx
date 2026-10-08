import { useMemo, useState } from 'react'
import type { Overview, Performance, Transaction, FixedIncomeLot, PeriodAnalytics, Numeric } from './api'
import { Link } from './navigation'
import { movementLabels } from './text'
import { dateLabel, EmptyState, ErrorState, fmt, money, localDate } from './ui'
import { FinancialChart, historyOption } from './OverviewChart'
import { useResource } from './useResource'
import { periodStart, usePeriod } from './PeriodSelector'

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

const percent = (value: Numeric | null | undefined) => value == null ? '—' : (Number(value) > 0 ? '+' : '') + fmt(value) + '%'
const tone = (value: Numeric | null | undefined) => value == null || Number(value) === 0 ? '' : Number(value) > 0 ? 'positive' : 'negative'
const periodNames: Record<string, string> = { '1Y': '1A', '5Y': '5A', Max: 'Máx', custom: 'Personalizado' }
const colors = ['#0E7C86', '#6B6FF2', '#4A90E2', '#D4A574', '#22D3A1', '#F4B24A', '#667085']

function OverviewAllocation({ overview }: { overview: Overview }) {
  const [dimension, setDimension] = useState<'class' | 'currency'>('class')
  const groups = useMemo(() => {
    const grouped = new Map<string, number | null>()
    for (const p of overview.positions) {
      const key = dimension === 'class' ? p.allocation_class || 'Sem classe' : p.native_currency ?? p.transaction_currency ?? 'Sem moeda'
      const previous = grouped.get(key) ?? 0
      grouped.set(key, p.display_value == null || grouped.has(key) && grouped.get(key) === null ? null : previous + Number(p.display_value))
    }
    return [...grouped].sort((a, b) => (b[1] ?? -1) - (a[1] ?? -1))
  }, [overview.positions, dimension])
  const total = overview.summary.total_value
  const complete = total != null && total > 0 && groups.every(([, value]) => value != null && value >= 0)
  const option = useMemo(() => ({ animation: false, tooltip: { trigger: 'item', valueFormatter: (v: unknown) => money(Number(v), overview.summary.display_currency) },
    series: [{ type: 'pie', radius: ['66%', '88%'], center: ['50%', '50%'], label: { show: false },
      itemStyle: { borderWidth: 3, borderColor: 'transparent', borderRadius: 2 },
      data: groups.map(([name, value], i) => ({ name, value, itemStyle: { color: colors[i % colors.length] } })) }] }), [groups, overview.summary.display_currency])
  return <section className="panel overview-allocation"><div className="section-heading"><h2>Alocação da carteira</h2>
    <div className="segmented" aria-label="Dimensão da alocação">{([['class', 'Por classe'], ['currency', 'Por moeda']] as const).map(([key, label]) =>
      <button key={key} aria-pressed={dimension === key} onClick={() => setDimension(key)}>{label}</button>)}</div></div>
    {!groups.length ? <EmptyState>Nenhuma posição registrada.</EmptyState> : <div className="allocation-body">
      <div className="allocation-donut">{complete ? <FinancialChart option={option} label={'Alocação ' + (dimension === 'class' ? 'por classe' : 'por moeda')} /> : <div className="donut-placeholder" />}
        <div className="donut-total"><b>{complete ? money(total, overview.summary.display_currency) : '—'}</b><small>{complete ? 'Total alocado' : 'Dados incompletos'}</small></div></div>
      <table className="allocation-table"><thead className="sr-only"><tr><th>Categoria</th><th>Percentual</th><th>Valor</th></tr></thead><tbody>
        {groups.map(([label, value], i) => <tr key={label}><td><i style={{ background: colors[i % colors.length] }} />{label}</td><td>{complete && value != null ? fmt(value / total! * 100, 1) + '%' : '—'}</td><td>{money(value, overview.summary.display_currency)}</td></tr>)}
      </tbody></table></div>}
  </section>
}

function PeriodButtons({ selection, onChoose }: { selection: ReturnType<typeof usePeriod>; onChoose: (p: string) => void }) {
  return <div className="period-buttons" aria-label="Período do gráfico">{['1M', '3M', '6M', 'YTD', '1Y', '5Y', 'Max'].map(p =>
    <button key={p} aria-pressed={selection.period === p} onClick={() => onChoose(p)}>{periodNames[p] ?? p}</button>)}</div>
}

export default function OverviewPage({ overview, portfolioId, transactions, lots, version, onAdd }: { lots: FixedIncomeLot[]; overview: Overview; portfolioId: number; transactions: Transaction[]; version: number; onAdd?: () => void }) {
  const base = '/portfolios/' + portfolioId
  const currency = overview.summary.display_currency
  const history = useResource<Performance[]>(base + '/history', version)
  const chartPeriod = usePeriod('1Y'), selection = usePeriod('1Y'), gainPeriod = usePeriod('1M')
  const [mode, setMode] = useState<'return' | 'value'>('return')
  const [chartRevision, setChartRevision] = useState(0)
  const [benchmarks, setBenchmarks] = useState<string[]>([])
  const chartAnalytics = useResource<PeriodAnalytics>(base + '/analytics?' + chartPeriod.params + '&include_series=true&benchmark_codes=' + (currency === 'BRL' ? benchmarks.join(',') : ''), version)
  const rangeAnalytics = useResource<PeriodAnalytics>(selection.params.toString() === chartPeriod.params.toString() ? null : base + '/analytics?' + selection.params + '&include_series=true&benchmark_codes=' + (currency === 'BRL' ? benchmarks.join(',') : ''), version)
  const analytics = selection.params.toString() === chartPeriod.params.toString() ? chartAnalytics : rangeAnalytics
  const gain = useResource<PeriodAnalytics>(base + '/analytics?' + gainPeriod.params, version)
  const monthly = useResource<PeriodAnalytics>(base + '/analytics?start_date=' + periodStart('1M') + '&end_date=' + localDate(), version)
  const month = useResource<PeriodAnalytics>(base + '/analytics?start_date=' + periodStart('MTD') + '&end_date=' + localDate(), version)
  const daily = useResource<PeriodAnalytics>(base + '/analytics?start_date=' + periodStart('1D') + '&end_date=' + localDate(), version)
  const annual = useResource<PeriodAnalytics>(base + '/analytics?start_date=' + periodStart('1Y') + '&end_date=' + localDate(), version)
  const inception = useResource<PeriodAnalytics>(base + '/analytics?end_date=' + localDate(), version)
  const rows = useMemo(() => (history.data ?? []).filter(r => (!chartPeriod.start || r.date >= chartPeriod.start) && (!chartPeriod.end || r.date <= chartPeriod.end)), [history.data, chartPeriod.start, chartPeriod.end])
  const option = useMemo(() => historyOption(rows, chartAnalytics.data, mode, currency), [rows, chartAnalytics.data, mode, currency])
  const activity = [...transactions.map(t => ({ key: 'tx' + t.id, id: t.id, date: t.trade_date,
    label: (t.type === 'Buy' ? 'Compra de ' : 'Venda de ') + t.asset, detail: fmt(t.quantity, 4) + ' × ' + money(t.price, t.transaction_currency),
    value: Number(t.quantity) * Number(t.price), currency: t.transaction_currency, incoming: t.type === 'Sell' })),
    ...lots.flatMap(l => l.movements.map(m => ({ key: 'fi' + m.id, id: m.id, date: m.effective_date,
      label: (movementLabels[m.movement_type] ?? 'Movimento') + ' · ' + l.instrument_symbol, detail: l.broker,
      value: Number(m.amount), currency: m.currency, incoming: ['PARTIAL_REDEMPTION', 'FULL_REDEMPTION', 'MATURITY', 'AMORTIZATION'].includes(m.movement_type) })))].sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id || b.key.localeCompare(a.key)).slice(0, 5)
  const last = history.data?.at(-1)
  const comparison = analytics.data?.benchmarks?.find(b => b.code === benchmarks[0])
  const result = gain.data?.status === 'complete' ? gain.data.monetary_result : null
  const currentMonth = month.data?.status === 'complete' ? month.data.monetary_result : null
  const largest = overview.positions.filter(p => p.display_value != null)
    .sort((a, b) => Number(b.display_value) - Number(a.display_value)).slice(0, 5)
  const periodContext = (data: PeriodAnalytics | null) => data ? dateLabel(data.coverage_start ?? data.start_date) + ' a ' + dateLabel(data.coverage_end ?? data.end_date) : '—'
  const errors = [...new Set([history.error, chartAnalytics.error, analytics.error, gain.error, month.error, monthly.error, daily.error, annual.error, inception.error].filter(Boolean))]
  function choose(value: string) { chartPeriod.choose(value); selection.choose(value); setChartRevision(v => v + 1) }
  function restore() {
    if (chartPeriod.period !== 'custom') { choose(chartPeriod.period); return }
    selection.choose('custom')
    selection.setStart(chartPeriod.start)
    selection.setEnd(chartPeriod.end)
    setChartRevision(v => v + 1)
  }
  function editDates(start: string, end: string) {
    chartPeriod.choose('custom'); selection.choose('custom')
    chartPeriod.setStart(start); selection.setStart(start)
    chartPeriod.setEnd(end); selection.setEnd(end)
    setChartRevision(v => v + 1)
  }
  function range(start: number, end: number) {
    if (rows.length < 2) return
    selection.choose('custom')
    selection.setStart(rows[Math.round(start / 100 * (rows.length - 1))].date)
    selection.setEnd(rows[Math.round(end / 100 * (rows.length - 1))].date)
  }
  return <div className="overview-page"><div className="overview-heading"><h1>Visão geral</h1><Link href="/data/status" className="overview-status">{overview.summary.history_status === 'complete' ? 'Conferir dados →' : 'Dados precisam de atenção →'}</Link></div>
    {errors.map(error => <ErrorState key={error} error={error} retry={() => { history.retry(); chartAnalytics.retry(); analytics.retry(); gain.retry(); month.retry(); monthly.retry(); daily.retry(); annual.retry(); inception.retry() }} />)}
    {!overview.positions.length && <EmptyState action={onAdd && <button className="button primary" onClick={onAdd}>Adicionar primeira transação</button>}>Sua carteira começa aqui. Adicione ou importe suas operações.</EmptyState>}
    <div className="overview-dashboard"><section className="panel overview-chart-panel"><div className="chart-toolbar">
      <div className="segmented" aria-label="Série do gráfico"><button aria-pressed={mode === 'return'} onClick={() => setMode('return')}>Rentabilidade</button><button aria-pressed={mode === 'value'} onClick={() => setMode('value')}>Patrimônio</button></div>
      <PeriodButtons selection={selection} onChoose={choose} /><label className="benchmark-picker"><span className="sr-only">Comparar com</span><select aria-label="Comparar com" value={currency === 'BRL' ? benchmarks[0] ?? '' : ''} onChange={e => setBenchmarks(e.target.value ? [e.target.value] : [])}>
        <option value="">Comparar com</option>{currency === 'BRL' ? <><option value="CDI">CDI</option><option disabled>IBOV · indisponível</option></> : <><option disabled>SPX · indisponível</option><option disabled>Taxa de caixa USD · indisponível</option></>}</select></label>
    </div><div className="chart-legend"><span><i />Minha carteira <b className={tone(analytics.data?.return_pct)}>{percent(analytics.data?.return_pct)}</b></span>{comparison && <span><i className="benchmark-dot" />{comparison.code} <b>{percent(comparison.return_pct)}</b></span>}</div>
      <div className="chart-caption"><span>{mode === 'return' ? 'Rentabilidade desde ' + dateLabel(chartAnalytics.data?.coverage_start) : 'Patrimônio · ' + currency}</span><span>Janela: {periodContext(analytics.data)}</span></div>
      {history.loading || chartAnalytics.loading ? <div className="chart-empty" role="status">Carregando histórico…</div> : !rows.length ? <div className="chart-empty">Histórico indisponível. Atualize a carteira para conferir os dados.</div> : <FinancialChart key={chartRevision} option={option} label={mode === 'return' ? 'Rentabilidade da carteira no período' : 'Evolução do patrimônio'} onRange={range} />}
      <div className="chart-footer"><span>Arraste para navegar · Ctrl + rolagem: zoom · Ctrl + Shift + rolagem: zoom e deslocamento</span><button onClick={restore}>Restaurar período</button></div>
      <details className="chart-accessible"><summary>Datas e valores do gráfico</summary><div className="chart-date-inputs"><label>Data inicial<input type="date" value={selection.start} max={selection.end} onChange={e => editDates(e.target.value, selection.end)} /></label><label>Data final<input type="date" value={selection.end} min={selection.start} max={localDate()} onChange={e => editDates(selection.start, e.target.value)} /></label></div><div className="table-wrap"><table><thead><tr><th>Data</th><th>Patrimônio</th><th>Rentabilidade</th></tr></thead><tbody>{rows.map((r, i) => <tr key={r.date}><td>{dateLabel(r.date)}</td><td>{money(r.status === 'complete' && r.reporting_currency === currency ? r.market_value : null, currency)}</td><td>{percent(chartAnalytics.data?.return_series?.[i]?.return_pct)}</td></tr>)}</tbody></table></div></details>
      {analytics.data?.status !== 'complete' && !analytics.loading && <p className="chart-notice">Retornos indisponíveis onde o histórico está incompleto.</p>}
      {comparison && comparison.status !== 'complete' && <p className="chart-notice">CDI: cobertura incompleta para o período selecionado. <Link href="/data/benchmarks">Conferir dados →</Link></p>}
    </section>
    <div className="overview-kpis"><Link href="/positions" className="metric featured wealth-card" aria-label="Patrimônio total — Ver posições"><div className="kpi-heading"><h2>Patrimônio total</h2><span>Ver detalhes →</span></div><strong>{money(overview.summary.total_value, currency)}</strong><div className={'month-result ' + tone(currentMonth)}><span aria-hidden="true">{currentMonth == null ? '' : Number(currentMonth) < 0 ? '↓' : '↑'}</span> {money(currentMonth, currency)} <small>no mês atual · dias encerrados</small></div></Link>
      <Link href="/performance" className="metric return-card" aria-label="Rentabilidade — Ver desempenho"><div className="kpi-heading"><h2>Rentabilidade</h2><span>Ver detalhes →</span></div><strong className={tone(analytics.data?.annualized_return_pct)}>{percent(analytics.data?.annualized_return_pct)}</strong><p>Anualizada · {periodContext(analytics.data)}</p><p className="benchmark-context">{comparison ? 'vs. ' + percent(comparison.annualized_return_pct) + ' a.a. do ' + comparison.code : 'Selecione um benchmark para comparar'}</p><div className="return-submetrics">{[['Diária', daily.data], ['Mensal', monthly.data], ['Anual', annual.data], ['Desde o início', inception.data]].map(([label, data]) => <div key={String(label)}><span>{String(label)}</span><b className={tone((data as PeriodAnalytics | null)?.return_pct)}>{percent((data as PeriodAnalytics | null)?.return_pct)}</b></div>)}</div></Link>
      <section className="metric gain-card" aria-label="Ganho patrimonial"><div className="kpi-heading"><h2>Ganho patrimonial</h2><label><span className="sr-only">Período do ganho patrimonial</span><select value={gainPeriod.period} onChange={e => gainPeriod.choose(e.target.value)}>{['1D', '1M', 'YTD', '1Y', '5Y', 'Max'].map(p => <option key={p} value={p}>{periodNames[p] ?? p}</option>)}</select></label></div><strong className={tone(result)}>{gain.loading ? '…' : money(result, currency)}</strong><p>{periodContext(gain.data)}</p>{gain.data?.status !== 'complete' && !gain.loading && <small>Dados incompletos ou atualização pendente</small>}<small>Resultado do período · dias encerrados</small></section>
    </div>
    <OverviewAllocation overview={overview} />
    <Link href="/transactions" className="panel overview-activity" aria-label="Atividade recente — Ver transações"><div className="section-heading"><h2>Atividade recente</h2><span>Ver todas →</span></div>{!activity.length ? <EmptyState>Nenhuma atividade registrada.</EmptyState> : <ul>{activity.map(a => <li key={a.key}><span className={'activity-icon ' + (a.incoming ? 'incoming' : '')} aria-hidden="true">{a.incoming ? '↓' : '↑'}</span><div className="activity-description"><b>{a.label}</b><small>{a.detail}</small></div><div className="activity-value"><time dateTime={a.date}>{dateLabel(a.date)}</time><b className={a.incoming ? 'positive' : ''}>{a.incoming ? '+ ' : '− '}{money(a.value, a.currency)}</b></div></li>)}</ul>}</Link>
    </div>
    <details className="overview-more"><summary>Mais sobre a carteira</summary><dl className="overview-secondary"><div><dt>Custo de aquisição</dt><dd>{money(overview.summary.acquisition_cost, currency)}</dd></div><div><dt>Resultado acumulado</dt><dd>{money(overview.summary.total_gain, currency)}</dd></div><div><dt>Rendimentos</dt><dd>{money(overview.summary.gross_income, currency)}</dd></div><div><dt>Posições</dt><dd>{overview.summary.positions}</dd></div><div><dt>Retorno acumulado</dt><dd>{percent(last?.cumulative_return_pct)}<small>Até {dateLabel(last?.date)}</small></dd></div></dl>
      <section className="panel" aria-label="Maiores posições"><div className="section-heading"><h2>Maiores posições</h2><Link href="/positions">Ver posições →</Link></div>
        {overview.positions.some(p => p.display_value == null) && <p className="table-caption">Ordenação apenas pelos valores disponíveis; há posições com valor desconhecido.</p>}
        {!largest.length ? <EmptyState>Não há posições com valor disponível.</EmptyState> : <div className="table-wrap"><table><thead><tr><th>Instrumento</th><th>Valor atual</th></tr></thead><tbody>{largest.map(p =>
          <tr key={p.asset_id}><td><Link href={p.position_type === 'FIXED_INCOME' ? '/positions?type=fixed' : '/positions/' + p.asset_id}>{p.asset}</Link></td><td>{money(p.display_value, currency)}</td></tr>)}
        </tbody></table></div>}
      </section><Attention overview={overview} /><p className="method-note">Resultado dos dias encerrados: variação do patrimônio mais renda bruta, descontados os aportes e resgates líquidos. O dia atual ainda não integra o histórico. Retorno anualizado em base de 365 dias; não representa taxa contratada. Atividades exibem a data e o valor bruto na moeda da operação.</p></details>
  </div>
}
