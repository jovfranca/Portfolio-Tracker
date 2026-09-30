import { useEffect, useState, type FormEvent } from 'react'
import { api, type FixedIncomeLot, type FixedIncomeMovement } from './api'

type Props = {
  portfolioId: number; busy: boolean;
  mutate: (task: () => Promise<unknown>, success: string) => Promise<boolean>;
  onClose: () => void; mode: 'REDEMPTION' | 'ADDITIONAL' | 'EDIT';
  initialLotId?: number; editing?: FixedIncomeMovement;
}

export default function FixedIncomeMovementForm({ portfolioId, busy, mutate, onClose, mode, initialLotId, editing }: Props) {
  const [lots, setLots] = useState<FixedIncomeLot[]>([])
  const [error, setError] = useState('')
  const [lotId, setLotId] = useState<number | null>(initialLotId ?? editing?.lot_id ?? null)
  const [kind, setKind] = useState(editing?.movement_type ?? (mode === 'ADDITIONAL' ? 'ADDITIONAL_INVESTMENT' : 'PARTIAL_REDEMPTION'))
  const [day, setDay] = useState(editing?.effective_date ?? '')
  const [amount, setAmount] = useState(editing?.amount ?? '')
  const [notes, setNotes] = useState(editing?.notes ?? '')
  const lot = lots.find(row => row.id === lotId)

  useEffect(() => {
    const controller = new AbortController()
    api<FixedIncomeLot[]>(`/portfolios/${portfolioId}/fixed-income/lots`, 'GET', undefined, controller.signal)
      .then(setLots)
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Falha ao carregar lotes.') })
    return () => controller.abort()
  }, [portfolioId])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!lot || !day) return
    const base = `/portfolios/${portfolioId}/fixed-income/lots/${lot.id}/movements`
    const payload = { movement_type: kind, effective_date: day,
      amount: kind === 'FULL_REDEMPTION' ? null : amount,
      currency: lot.currency, notes }
    if (await mutate(() => api(base + (editing ? `/${editing.id}` : ''), editing ? 'PUT' : 'POST', payload),
      editing ? 'Movimento e histórico atualizados.' : 'Movimento registrado. Histórico pendente de consolidação.')) onClose()
  }

  const redemption = mode === 'REDEMPTION' || (mode === 'EDIT' &&
    ['PARTIAL_REDEMPTION', 'FULL_REDEMPTION'].includes(editing?.movement_type ?? ''))
  const today = new Date().toLocaleDateString('en-CA')
  const latestDate = lot?.maturity_date && lot.maturity_date < today ? lot.maturity_date : today
  return <form className="panel transaction-form" onSubmit={save}>
    <div className="section-heading"><h2>{editing ? 'Editar movimento de renda fixa' : redemption ? 'Resgatar renda fixa' : 'Aporte adicional'}</h2>
      <button type="button" className="button quiet" disabled={busy} onClick={onClose}>Fechar</button></div>
    <fieldset disabled={busy}><div className="form-grid">
      <label>Lote<select required value={lotId ?? ''} disabled={!!editing} onChange={event => setLotId(Number(event.target.value))}>
        <option value="">Selecione um lote</option>
        {lots.map(row => <option key={row.id} value={row.id}>{row.instrument_symbol} · {row.issuer} · {row.broker} · {row.start_date} · lote #{row.id}</option>)}
      </select></label>
      {lot && <div className="selected-instrument wide">{lot.instrument_symbol} · {lot.issuer} · {lot.broker} · aplicação {lot.currency} {Number(lot.opening_amount).toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</div>}
      {redemption && <label>Tipo de resgate<select value={kind} onChange={event => setKind(event.target.value)}>
        <option value="PARTIAL_REDEMPTION">Resgate parcial</option><option value="FULL_REDEMPTION">Resgate total</option>
      </select></label>}
      <label>Data do movimento<input required type="date" min={editing?.movement_type === 'INITIAL_INVESTMENT' ? undefined : lot?.start_date} max={latestDate} value={day} onChange={event => setDay(event.target.value)} /></label>
      {kind !== 'FULL_REDEMPTION' && <label>{redemption ? 'Valor bruto resgatado' : 'Valor aplicado'}<input required type="number" min="0.000000000001" step="any" value={amount} onChange={event => setAmount(event.target.value)} /></label>}
      <label className="wide">Observações<input maxLength={5000} value={notes} onChange={event => setNotes(event.target.value)} /></label>
    </div>
    {kind === 'FULL_REDEMPTION' && <p className="method-note">O valor do resgate total será calculado pela avaliação bruta do lote na data escolhida.</p>}
    {error && <div role="alert" className="alert error">{error}</div>}
    <div className="form-footer"><span>O movimento afeta apenas o lote selecionado.</span><button className="button primary" disabled={!lot}>{busy ? 'Salvando…' : 'Salvar movimento'}</button></div>
    </fieldset>
  </form>
}
