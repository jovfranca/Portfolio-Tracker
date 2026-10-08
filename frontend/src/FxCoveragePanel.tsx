import { useState } from 'react'
import type { FxCoverage } from './api'
import { Link } from './navigation'
import { useResource } from './useResource'
import { dateLabel, EmptyState, ErrorState, fmt, LoadingState } from './ui'

const reasons: Record<string, string> = { valuation: 'Avaliação de posições', transaction_reporting: 'Custo/fluxo na moeda de exibição',
  income_reporting: 'Rendimentos', fixed_income_valuation: 'Avaliação de renda fixa' }
const timestamp = (value: string | null) => value ? new Date(value).toLocaleString('pt-BR') : 'Não registrado'

export default function FxCoveragePanel({ portfolioId, version, compact = false }: { portfolioId: number; version: number; compact?: boolean }) {
  const resource = useResource<FxCoverage>('/portfolios/' + portfolioId + '/fx-coverage', version)
  const [selected, setSelected] = useState(''), [historyPage, setHistoryPage] = useState(0)
  const data = resource.data, pair = data?.pairs?.find(p => p.currency === selected) ?? data?.pairs?.[0]
  const history = [...(pair?.history ?? [])].reverse()
  return <section className="panel settings-section" aria-label="Cobertura cambial da carteira"><h2>Cobertura cambial da carteira</h2>
    {resource.loading ? <LoadingState /> : resource.error ? <ErrorState error={resource.error} retry={resource.retry} /> : data && <>
      <p>Cobertura FX na moeda de exibição {data.reporting_currency}. Observações anteriores são reutilizadas por até {data.fallback_days} dias.</p>
      <p>Última sincronização bem-sucedida: {timestamp(data.last_successful_sync_at)}. O sistema registra a consulta das observações, mas não o término de uma sincronização completa.</p>
      {data.requirements_status === 'pending' && <p className="alert warning">Posições ainda não consolidadas: as necessidades de câmbio são provisórias até atualizar a carteira.</p>}
      {data.requirements_status === 'incomplete' && <p className="alert warning">Moeda contábil/cotação indefinida: {data.unknown_requirements.join(', ')}. Confira os instrumentos antes de avaliar a cobertura.</p>}
      {!data.pairs?.length ? <EmptyState>{data.requirements_status === 'incomplete' ? 'Não foi possível determinar todos os pares necessários.' : 'Nenhum par cambial é necessário para esta carteira.'}</EmptyState> : <>
        <div className="table-wrap"><table><thead><tr><th>Par utilizado</th><th>Período necessário</th><th>Observações necessárias cobertas</th><th>Datas ausentes</th><th>Status</th><th>Fonte</th></tr></thead>
          <tbody>{data.pairs.map(p => <tr key={p.currency}><td>{p.currency}/{p.base_currency}</td><td>{dateLabel(p.required_start)} a {dateLabel(p.required_end)}</td>
            <td>{p.covered_count} de {p.required_count}</td><td>{p.missing_dates.length}</td><td>{p.status === 'complete' ? 'Completo' : 'Incompleto'}</td><td>{p.sources.join(', ') || 'Sem observações'}</td></tr>)}</tbody></table></div>
        {compact ? <><ul className="activity-list">{data.pairs.filter(p => p.missing_dates.length).map(p => <li key={p.currency}><Link href="/data/fx">{p.currency}/{p.base_currency}: {p.missing_dates.length} datas sem FX utilizável</Link><small>Primeira: {dateLabel(p.missing_dates[0])} · Última: {dateLabel(p.missing_dates.at(-1))}</small></li>)}</ul><Link href="/data/fx">Inspecionar histórico e datas de câmbio →</Link></> : pair && <>
          <label>Par cambial<select value={pair.currency} onChange={e => { setSelected(e.target.value); setHistoryPage(0) }}>{data.pairs.map(p => <option key={p.currency} value={p.currency}>{p.currency}/{p.base_currency}</option>)}</select></label>
          <p>Histórico FX disponível: {dateLabel(pair.available_start)} a {dateLabel(pair.available_end)}. Última consulta de observação: {timestamp(pair.last_observation_retrieved_at)}.</p>
          <details><summary>Datas necessárias e observações usadas ({pair.required_count})</summary>
            <div className="table-wrap"><table><thead><tr><th>Data necessária</th><th>Uso</th><th>Referência utilizada</th><th>Status</th></tr></thead><tbody>{pair.requirements.map(r => <tr key={r.date}><td>{dateLabel(r.date)}</td><td>{r.reasons.map(reason => reasons[reason] ?? reason).join(', ')}</td><td>{dateLabel(r.reference_date)}</td><td>{!r.reference_date ? 'FX ausente' : r.fallback_used ? 'Observação anterior' : 'Data exata'}</td></tr>)}</tbody></table></div>
          </details>
          <h3>Histórico de câmbio e PTAX · {pair.currency}/{pair.base_currency}</h3><p>FX sustenta as avaliações. PTAX de compra e venda é exibida para inspeção, sem escolher uma regra tributária.</p>
          {!history.length ? <EmptyState>Nenhuma observação armazenada no período necessário.</EmptyState> : <><div className="table-wrap"><table><thead><tr><th>Data da observação</th><th>Série / lado</th><th>BRL por unidade</th><th>Fonte</th><th>Consulta da observação</th></tr></thead><tbody>{history.slice(historyPage * 100, (historyPage + 1) * 100).map(r => <tr key={r.reference_date + r.rate_type + r.side}><td>{dateLabel(r.reference_date)}</td><td>{r.rate_type} · {r.side === 'BUY' ? 'Compra' : r.side === 'SELL' ? 'Venda' : 'Mercado'}</td><td>{fmt(r.rate, 6)}</td><td>{r.source}</td><td>{timestamp(r.retrieved_at)}</td></tr>)}</tbody></table></div>
            <div className="settings-actions"><button className="button quiet" disabled={historyPage === 0} onClick={() => setHistoryPage(p => p - 1)}>Anteriores</button><span>Página {historyPage + 1} de {Math.ceil(history.length / 100)} · {history.length} observações</span><button className="button quiet" disabled={(historyPage + 1) * 100 >= history.length} onClick={() => setHistoryPage(p => p + 1)}>Próximas</button></div></>}
        </>}
      </>}
    </>}
  </section>
}
