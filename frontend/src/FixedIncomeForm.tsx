import { useEffect, useState, type FormEvent } from 'react'
import { api, type InstrumentSearchResult } from './api'
import InstrumentPicker from './InstrumentPicker'

type Benchmark = { id: number; code: string; name: string }
type YieldStructure = 'FIXED_RATE' | 'BENCHMARK_MULTIPLE' | 'BENCHMARK_SPREAD'
type Props = { portfolioId: number; busy: boolean; mutate: (task: () => Promise<unknown>, success: string) => Promise<boolean>; onClose: () => void }

export default function FixedIncomeForm({ portfolioId, busy, mutate, onClose }: Props) {
  const [instrument, setInstrument] = useState<(InstrumentSearchResult & { instrument_id: number }) | null>(null)
  const [query, setQuery] = useState('')
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([])
  const [benchmarkError, setBenchmarkError] = useState('')
  const [draft, setDraft] = useState({
    product_type: 'CDB', issuer: '', broker: '', currency: 'BRL', start_date: '', maturity_date: '',
    opening_amount: '', yield_structure: 'FIXED_RATE' as YieldStructure, fixed_rate: '',
    benchmark_id: '', benchmark_multiplier: '', benchmark_spread: '', day_count_basis: 'BUS_252',
    compounding: 'COMPOUND', business_day_calendar: 'BR', benchmark_lag_months: '0', notes: '',
  })
  useEffect(() => {
    const controller = new AbortController()
    api<Benchmark[]>('/benchmarks', 'GET', undefined, controller.signal).then(setBenchmarks)
      .catch(reason => { if (!controller.signal.aborted) setBenchmarkError(reason instanceof Error ? reason.message : 'Falha ao carregar indexadores.') })
    return () => controller.abort()
  }, [])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!instrument) return
    const linked = draft.yield_structure !== 'FIXED_RATE'
    const payload = {
      instrument_id: instrument.instrument_id, product_type: draft.product_type, issuer: draft.issuer,
      broker: draft.broker, currency: draft.currency, start_date: draft.start_date,
      maturity_date: draft.maturity_date || null, opening_amount: draft.opening_amount,
      yield_structure: draft.yield_structure,
      fixed_rate: linked ? null : draft.fixed_rate,
      benchmark_id: linked ? Number(draft.benchmark_id) : null,
      benchmark_multiplier: draft.yield_structure === 'BENCHMARK_MULTIPLE' ? draft.benchmark_multiplier : null,
      benchmark_spread: draft.yield_structure === 'BENCHMARK_SPREAD' ? draft.benchmark_spread : null,
      day_count_basis: draft.day_count_basis, compounding: draft.compounding,
      business_day_calendar: draft.business_day_calendar,
      benchmark_lag_months: Number(draft.benchmark_lag_months), notes: draft.notes,
    }
    if (await mutate(() => api('/portfolios/' + portfolioId + '/fixed-income/lots', 'POST', payload), 'Lote de renda fixa registrado. Avaliação pendente.')) onClose()
  }

  return <form className="panel transaction-form" onSubmit={save}>
    <div className="section-heading"><h2>Registrar lote de renda fixa</h2><button type="button" className="button quiet" disabled={busy} onClick={onClose}>Fechar</button></div>
    <fieldset disabled={busy}>
      <div className="form-grid">
        <label>Instrumento<input required maxLength={40} readOnly={!!instrument} value={instrument?.symbol ?? query} onChange={event => setQuery(event.target.value)} placeholder="Código ou nome" /></label>
        {!instrument ? <InstrumentPicker key="fixed-income" query={query} initialMode="FIXED_INCOME" showModeChoices={false} onSelect={item => {
          setInstrument(item)
          if (item.currency) setDraft(current => ({ ...current, currency: item.currency! }))
        }} /> : <div className="selected-instrument wide"><span>Instrumento selecionado: <strong>{instrument.symbol}</strong></span><button type="button" className="button quiet" onClick={() => { setInstrument(null); setQuery('') }}>Trocar ativo</button></div>}
        <label>Produto<select value={draft.product_type} onChange={event => setDraft({ ...draft, product_type: event.target.value })}><option>CDB</option><option>LCI</option><option>LCA</option></select></label>
        <label>Emissor<input required maxLength={200} value={draft.issuer} onChange={event => setDraft({ ...draft, issuer: event.target.value })} /></label>
        <label>Corretora<input required maxLength={120} value={draft.broker} onChange={event => setDraft({ ...draft, broker: event.target.value })} /></label>
        <label>Moeda<input required maxLength={3} pattern="[A-Za-z]{3}" disabled={!!instrument?.currency} value={draft.currency} onChange={event => setDraft({ ...draft, currency: event.target.value.toUpperCase() })} /></label>
        <label>Data da aplicação<input required type="date" value={draft.start_date} onChange={event => setDraft({ ...draft, start_date: event.target.value })} /></label>
        <label>Vencimento<input type="date" min={draft.start_date} value={draft.maturity_date} onChange={event => setDraft({ ...draft, maturity_date: event.target.value })} /></label>
        <label>Valor aplicado<input required type="number" min="0.000000000001" step="any" value={draft.opening_amount} onChange={event => setDraft({ ...draft, opening_amount: event.target.value })} /></label>
        <label>Estrutura de rendimento<select value={draft.yield_structure} onChange={event => setDraft({ ...draft, yield_structure: event.target.value as YieldStructure })}><option value="FIXED_RATE">Taxa fixa</option><option value="BENCHMARK_MULTIPLE">Percentual do indexador</option><option value="BENCHMARK_SPREAD">Indexador + spread</option></select></label>
        {draft.yield_structure === 'FIXED_RATE' ? <label>Taxa fixa anual (fração; 0,12 = 12%)<input required type="number" min="-1" max="1000" step="any" value={draft.fixed_rate} onChange={event => setDraft({ ...draft, fixed_rate: event.target.value })} /></label> : <>
          <label>Indexador<select required value={draft.benchmark_id} onChange={event => setDraft({ ...draft, benchmark_id: event.target.value })}><option value="">Selecione um indexador</option>{benchmarks.map(row => <option key={row.id} value={row.id}>{row.code} · {row.name}</option>)}</select></label>
          {draft.yield_structure === 'BENCHMARK_MULTIPLE' ? <label>Multiplicador (1,10 = 110%)<input required type="number" min="0" max="1000" step="any" value={draft.benchmark_multiplier} onChange={event => setDraft({ ...draft, benchmark_multiplier: event.target.value })} /></label> : <label>Spread anual (fração; 0,06 = 6%)<input required type="number" min="-1" max="1000" step="any" value={draft.benchmark_spread} onChange={event => setDraft({ ...draft, benchmark_spread: event.target.value })} /></label>}
        </>}
        <label>Base de dias<select value={draft.day_count_basis} onChange={event => setDraft({ ...draft, day_count_basis: event.target.value })}><option value="BUS_252">Dias úteis / 252</option><option value="ACT_365">Dias corridos / 365</option><option value="ACT_360">Dias corridos / 360</option></select></label>
        <label>Capitalização<select value={draft.compounding} onChange={event => setDraft({ ...draft, compounding: event.target.value })}><option value="COMPOUND">Composta</option><option value="SIMPLE">Simples</option></select></label>
        <label>Calendário de dias úteis<select value={draft.business_day_calendar} onChange={event => setDraft({ ...draft, business_day_calendar: event.target.value })}><option value="BR">Brasil</option><option value="NONE">Nenhum</option></select></label>
        <label>Defasagem do indexador (meses)<input required type="number" min="0" max="24" step="1" value={draft.benchmark_lag_months} onChange={event => setDraft({ ...draft, benchmark_lag_months: event.target.value })} /></label>
        <label className="wide">Observações<input maxLength={5000} value={draft.notes} onChange={event => setDraft({ ...draft, notes: event.target.value })} /></label>
      </div>
      {benchmarkError && <div role="alert" className="alert error">{benchmarkError}</div>}
      <div className="form-footer"><span>O aporte inicial é registrado automaticamente. A avaliação permanece pendente.</span><button className="button primary" disabled={!instrument || (draft.yield_structure !== 'FIXED_RATE' && (!draft.benchmark_id || !!benchmarkError))}>{busy ? 'Salvando…' : 'Registrar lote'}</button></div>
    </fieldset>
  </form>
}
