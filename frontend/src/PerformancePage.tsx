import { useState } from 'react'
import type { FixedIncomeLot, Overview, Performance } from './api'
import { useResource } from './useResource'
import { Allocation } from './OverviewPage'
import { LotTable, PositionTable } from './PositionsPage'
import { HistoryChart, HistoryTable } from './HistoryPanel'
import { ErrorState, fmt, LoadingState, MetricCard, PageHeader, localDate } from './ui'

export default function PerformancePage({ portfolioId, overview, lots, version }: { portfolioId: number; overview: Overview; lots: FixedIncomeLot[]; version: number }) {
  const [period, setPeriod] = useState('Max'), [start, setStart] = useState(''), [end, setEnd] = useState(localDate())
  const params = new URLSearchParams()
  if (start) params.set('start_date', start)
  if (end) params.set('end_date', end)
  const history = useResource<Performance[]>('/portfolios/' + portfolioId + '/history', version)
  const analytics = useResource<{ return_pct: string | null; net_contributions: string | null; status: string }>('/portfolios/' + portfolioId + '/analytics?' + params, version)
  function choose(value: string) {
    setPeriod(value); setEnd(localDate())
    const d = new Date()
    if (value === 'Max') setStart('')
    else if (value === 'YTD') setStart(d.getFullYear() + '-01-01')
    else if (value !== 'custom') {
      const day = d.getDate()
      d.setDate(1)
      d.setMonth(d.getMonth() - ({ '1M': 1, '3M': 3, '6M': 6, '1Y': 12 }[value] ?? 0))
      d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()))
      setStart(new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10))
    }
  }
  const rows = (history.data ?? []).filter(r => (!start || r.date >= start) && (!end || r.date <= end)), last = rows.at(-1), currency = overview.summary.display_currency
  return <><PageHeader title="Desempenho" description="Evolução e resultados da carteira inteira, na moeda de exibição." />
    <section className="panel filter-bar"><div className="period-buttons">{['1M', '3M', '6M', 'YTD', '1Y', 'Max', 'custom'].map(value => <button key={value} className={'button ' + (period === value ? 'primary' : 'quiet')} onClick={() => choose(value)}>{value === '1Y' ? '1A' : value === 'Max' ? 'Máx' : value === 'custom' ? 'Personalizado' : value}</button>)}</div>{period === 'custom' && <><label>Data inicial<input type="date" value={start} max={end} onChange={e => setStart(e.target.value)} /></label><label>Data final<input type="date" value={end} min={start} max={localDate()} onChange={e => setEnd(e.target.value)} /></label></>}</section>
    {(history.error || analytics.error) && <ErrorState error={history.error || analytics.error} retry={() => { history.retry(); analytics.retry() }} />}
    {history.loading ? <LoadingState /> : <><div className="metrics overview-metrics"><MetricCard featured label={'Patrimônio no fim do período · ' + currency} value={fmt(last?.market_value)} /><MetricCard label="Retorno acumulado até a data final" value={last?.cumulative_return_pct == null ? '—' : fmt(last.cumulative_return_pct) + '%'} /><MetricCard label="Retorno do período" value={analytics.data?.return_pct == null ? '—' : fmt(analytics.data.return_pct) + '%'} /><MetricCard label={'Realizado acumulado · ' + currency} value={fmt(last?.realized_gain)} /><MetricCard label={'Não realizado · ' + currency} value={fmt(last?.unrealized_gain)} /><MetricCard label={'Rendimentos acumulados · ' + currency} value={fmt(last?.gross_income)} /><MetricCard label={'Aportes líquidos do período · ' + currency} value={fmt(analytics.data?.net_contributions)} /></div>
    {rows.some(r => r.status !== 'complete') && <div className="alert warning">Histórico com dados incompletos ou atualização pendente. Retornos desconhecidos permanecem indisponíveis.</div>}
    <div className="overview-grid"><section className="panel"><div className="section-heading"><h2>Evolução do patrimônio</h2></div><HistoryChart rows={rows} title="Evolução do patrimônio" currency={currency} /></section><section className="panel"><div className="section-heading"><h2>Retorno acumulado</h2></div><HistoryChart rows={rows} field="cumulative_return_pct" title="Retorno acumulado" currency="%" /></section></div>
    <div className="overview-grid"><Allocation overview={overview} by="class" /><Allocation overview={overview} by="currency" /></div><section className="panel"><div className="section-heading"><h2>Por ativo</h2><p>Clique para abrir o detalhe da posição.</p></div><PositionTable positions={overview.positions.filter(p => p.position_type !== 'FIXED_INCOME')} />{!!lots.length && <LotTable lots={lots} />}</section>
    <section className="panel"><div className="section-heading"><h2>Por corretora</h2><p>Quantidades contábeis. Valores por corretora não são projetados separadamente.</p></div><div className="table-wrap"><table><thead><tr><th>Ativo</th><th>Corretora</th><th>Quantidade</th></tr></thead><tbody>{overview.positions.flatMap(p => (p.broker_breakdown ?? []).map(b => <tr key={p.asset + b.broker}><td>{p.asset}</td><td>{b.broker}</td><td>{fmt(b.quantity, 6)}</td></tr>))}</tbody></table></div></section>
    <section className="panel"><HistoryTable rows={rows} currency={currency} /></section><p className="method-note">Comparação com benchmarks da carteira ainda não está disponível. CDI e IPCA podem ser inspecionados em Dados de mercado.</p></>}
  </>
}
