import { useEffect, useState } from 'react'
import { api, type FixedIncomeLot } from './api'

const dateLabel = (value: string | null) => value ? value.slice(0, 10).split('-').reverse().join('/') : '—'
const amountLabel = (value: string | null) => value === null ? '—' : Number(value).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const percentLabel = (value: string | null) => value === null ? '—' : `${(Number(value) * 100).toLocaleString('pt-BR', { maximumFractionDigits: 4 })}%`
const yieldLabel = (lot: FixedIncomeLot) => lot.yield_structure === 'FIXED_RATE'
  ? `Taxa fixa ${percentLabel(lot.fixed_rate)} a.a.`
  : lot.yield_structure === 'BENCHMARK_MULTIPLE'
    ? `${percentLabel(lot.benchmark_multiplier)} do ${lot.benchmark_code}`
    : `${lot.benchmark_code} + ${percentLabel(lot.benchmark_spread)} a.a.`
const movementLabels: Record<string, string> = {
  INITIAL_INVESTMENT: 'Aplicação inicial', ADDITIONAL_INVESTMENT: 'Aporte adicional',
  PARTIAL_REDEMPTION: 'Resgate parcial', FULL_REDEMPTION: 'Resgate total',
  MATURITY: 'Vencimento', AMORTIZATION: 'Amortização',
}

export default function FixedIncomeLots({ portfolioId, view }: { portfolioId: number; view: 'positions' | 'movements' }) {
  const [lots, setLots] = useState<FixedIncomeLot[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    api<FixedIncomeLot[]>(`/portfolios/${portfolioId}/fixed-income/lots`, 'GET', undefined, controller.signal)
      .then(setLots)
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Falha ao carregar lotes.') })
    return () => controller.abort()
  }, [portfolioId])

  return <section className="panel">
    <div className="section-heading"><div><h2>{view === 'positions' ? 'Renda fixa' : 'Movimentos de renda fixa'}</h2><p>Valor bruto contratual por lote, antes de impostos.</p></div></div>
    {error && <div role="alert" className="alert error">{error}</div>}
    {view === 'positions' ? <div className="table-wrap"><table><thead><tr><th>Instrumento</th><th>Emissor / corretora</th><th>Rendimento</th><th>Aplicação / vencimento</th><th>Valor aplicado</th><th>Saldo atual</th><th>Retorno</th></tr></thead><tbody>
      {lots.map(lot => <tr key={lot.id}>
        <td><strong>{lot.instrument_symbol}</strong><small>{lot.instrument_name}</small></td>
        <td>{lot.issuer}<small>{lot.broker}</small></td>
        <td>{yieldLabel(lot)}</td>
        <td>{dateLabel(lot.start_date)}<small>Vencimento {dateLabel(lot.maturity_date)}</small></td>
        <td>{lot.currency} {amountLabel(lot.opening_amount)}</td>
        <td>{lot.valuation?.status === 'complete' ? <>{lot.currency} {amountLabel(String(lot.valuation.gross_accrued_value))}<small>Principal {amountLabel(String(lot.valuation.outstanding_principal))}</small>{lot.valuation.display_currency !== lot.currency && <small>{lot.valuation.display_currency} {amountLabel(String(lot.valuation.display_value))}</small>}</> : <span title={lot.valuation?.status}>Indisponível · {lot.valuation?.status ?? 'pendente'}</span>}</td>
        <td>{lot.valuation?.status === 'complete' ? <>{lot.currency} {amountLabel(String(lot.valuation.accrued_gain))}<small>Bruto, antes de impostos</small></> : '—'}</td>
      </tr>)}
    </tbody></table></div> : <div className="table-wrap"><table><thead><tr><th>Data</th><th>Instrumento / emissor</th><th>Movimento</th><th>Valor</th><th>Rendimento</th></tr></thead><tbody>
      {lots.flatMap(lot => lot.movements.map(movement => <tr key={`${lot.id}-${movement.id}`}>
        <td>{dateLabel(movement.effective_date)}</td>
        <td><strong>{lot.instrument_symbol}</strong><small>{lot.issuer}</small></td>
        <td>{movementLabels[movement.movement_type] ?? movement.movement_type}</td>
        <td>{movement.currency} {amountLabel(movement.amount)}</td>
        <td>{yieldLabel(lot)}</td>
      </tr>))}
    </tbody></table></div>}
  </section>
}
