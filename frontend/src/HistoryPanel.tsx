import type { Performance } from './api'
import { dateLabel, EmptyState, ErrorState, fmt, LoadingState, MetricCard, StatusBadge } from './ui'
import { useResource } from './useResource'

export function HistoryChart({ rows, field = 'market_value', title, currency }: { rows: Performance[]; field?: 'market_value' | 'total_gain' | 'cumulative_return_pct'; title: string; currency: string }) {
  const values = rows.filter(r => r[field] != null).map(r => Number(r[field]))
  if (!values.length) return <EmptyState>Histórico indisponível. Atualize a carteira para conferir os dados.</EmptyState>
  const low = Math.min(0, ...values), high = Math.max(0, ...values), span = high - low || 1
  const y = (n: number) => 160 - (n - low) / span * 125
  const points = rows.map((r, i) => r[field] == null ? '' : ((i === 0 || rows[i - 1][field] == null) ? 'M' : 'L') + (70 + i / Math.max(rows.length - 1, 1) * 660) + ',' + y(Number(r[field]))).join(' ')
  return <div className="chart"><p>{title} · {currency}</p><svg viewBox="0 0 800 205" role="img" aria-label={title}>
    {[low, (high + low) / 2, high].map((v, i) => <g key={i}><line x1="70" x2="730" y1={y(v)} y2={y(v)} stroke="var(--border)" /><text x="65" y={y(v) + 4} textAnchor="end">{fmt(v, 0)}</text></g>)}
    <path d={points} fill="none" stroke="var(--chart-primary)" strokeWidth="2.5" /><text x="70" y="190">{dateLabel(rows[0]?.date)}</text><text x="730" y="190" textAnchor="end">{dateLabel(rows.at(-1)?.date)}</text>
  </svg></div>
}
export function HistoryTable({ rows, currency }: { rows: Performance[]; currency: string }) {
  return <div className="table-wrap"><table aria-label="Histórico de desempenho"><thead><tr>{['Data', 'Valor · ' + currency, 'Custo', 'Realizado', 'Não realizado', 'Rendimentos', 'Resultado total', 'Retorno acumulado', 'Cotação utilizada', 'Status'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{[...rows].reverse().slice(0, 100).map(r => <tr key={r.date}>
    <td>{dateLabel(r.date)}</td><td>{fmt(r.market_value)}</td><td>{fmt(r.remaining_acquisition_cost)}</td><td>{fmt(r.realized_gain)}</td><td>{fmt(r.unrealized_gain)}</td><td>{fmt(r.gross_income)}</td><td>{fmt(r.total_gain)}</td><td>{r.cumulative_return_pct == null ? '—' : fmt(r.cumulative_return_pct) + '%'}</td><td>{dateLabel(r.quote_date)}{r.quote_date && r.quote_date !== r.date && <small>Última disponível</small>}</td><td><StatusBadge status={r.status} /></td>
  </tr>)}</tbody></table><p className="table-caption">Até 100 observações recentes. Valores na moeda de exibição.</p></div>
}
export default function HistoryPanel({ portfolioId, assetId, version = 0 }: { portfolioId: number; assetId: number; version?: number }) {
  const resource = useResource<Performance[]>('/portfolios/' + portfolioId + '/performance?asset_id=' + assetId, version)
  if (resource.loading) return <LoadingState />
  if (resource.error) return <ErrorState error={resource.error} retry={resource.retry} />
  const rows = resource.data ?? [], last = rows.at(-1), currency = last?.reporting_currency ?? ''
  return <section className="panel"><div className="section-heading"><h2>Desempenho da posição · {currency}</h2></div>{!rows.length ? <EmptyState>Atualize a carteira para gerar o histórico desta posição.</EmptyState> : <>
    <div className="metrics"><MetricCard label="Resultado realizado" value={fmt(last?.realized_gain)} /><MetricCard label="Resultado não realizado" value={fmt(last?.unrealized_gain)} /><MetricCard label="Retorno acumulado" value={last?.cumulative_return_pct == null ? '—' : fmt(last.cumulative_return_pct) + '%'} /></div>
    {rows.some(r => r.status !== 'complete') && <div className="alert warning">Histórico com dados incompletos ou pendentes. Confira o status dos dados.</div>}
    <HistoryChart rows={rows} field="total_gain" title="Evolução histórica do ganho total" currency={currency} /><HistoryTable rows={rows} currency={currency} />
  </>}</section>
}
