import { useEffect, useState, type FormEvent } from 'react'
import { api, type Asset, type Quote, type CorporateEvent, type Activity } from './api'
import { fmt, localDate, dateLabel, message, type Mutate } from './ui'
export function Quotes({ portfolioId, assets, busy, readOnly, mutate, initialAssetId }: { initialAssetId?: number; portfolioId: number; assets: Asset[]; busy: boolean; readOnly: boolean; mutate: Mutate }) {
  const quoteAssets = assets.filter((asset, index) => assets.findIndex(item => item.id === asset.id) === index)
  const [id, setId] = useState(quoteAssets.find(a => a.id === initialAssetId)?.id ?? quoteAssets[0]?.id ?? 0)
  const [rows, setRows] = useState<Quote[]>([])
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)
  const [draft, setDraft] = useState({ date: localDate().slice(0, 10), close: '' })
  useEffect(() => {
    if (!quoteAssets.some(asset => asset.id === id)) setId(quoteAssets[0]?.id ?? 0)
  }, [assets, id])
  const base = '/portfolios/' + portfolioId + '/assets/' + id
  useEffect(() => {
    if (!id) return
    const controller = new AbortController(); setError(''); setRows([])
    api<Quote[]>(base + '/history', 'GET', undefined, controller.signal).then(setRows).catch(e => { if (!controller.signal.aborted) setError(message(e)) })
    return () => controller.abort()
  }, [base, id, version])
  if (!quoteAssets.length) return <div className="panel empty">Registre uma transação para adicionar cotações ao ativo.</div>
  return <section className="panel"><div className="section-heading"><div><h2>Histórico de cotações</h2><p>Adicione preços manualmente ou atualize pelo Yahoo Finance.</p></div><label>Ativo<select value={id} disabled={busy} onChange={e => setId(Number(e.target.value))}>{quoteAssets.map(a => <option key={a.id} value={a.id}>{a.ticker}</option>)}</select></label></div>
    {!readOnly && <div className="quote-controls"><form onSubmit={async e => {
      e.preventDefault()
      if (await mutate(() => api(base + '/quote', 'PUT', { date: draft.date, close: Number(draft.close) }), 'Cotação salva.')) setVersion(version + 1)
    }}><fieldset disabled={busy || readOnly}><div className="form-grid quote-grid"><label>Data da cotação<input required type="date" max={localDate().slice(0, 10)} value={draft.date} onChange={e => setDraft({ ...draft, date: e.target.value })} /></label>
      <label>Fechamento<input required type="number" min="0" step="any" value={draft.close} onChange={e => setDraft({ ...draft, close: e.target.value })} /></label>
    </div><div className="form-footer"><span>Dividendos e desdobramentos são cadastrados na aba Eventos corporativos.</span><button className="button primary">Salvar cotação</button></div></fieldset></form>
    <button className="button outline" disabled={busy || readOnly} onClick={async () => {
      if (await mutate(() => api(base + '/refresh', 'POST'), 'Histórico atualizado; preços manuais preservados.')) setVersion(version + 1)
    }}>{busy ? 'Processando…' : 'Atualizar pelo Yahoo Finance'}</button></div>}
    {error && <div role="alert" className="alert error">{error}</div>}
    {!rows.length ? <div className="empty">Ainda não há cotações para este ativo.</div> : <div className="table-wrap"><table><thead><tr><th>Data</th><th>Fechamento / moeda</th><th>Dividendos</th><th>Desdobramento</th><th>Fonte</th></tr></thead><tbody>{[...rows].reverse().slice(0, 100).map(q => <tr key={q.date}><td>{dateLabel(q.date)}</td><td>{fmt(q.close, 4)}<small>{q.currency}</small></td><td>{fmt(q.dividends, 4)}</td><td>{fmt(q.stock_splits)}</td><td>{q.source}</td></tr>)}</tbody></table><p className="table-caption">Mostrando as {Math.min(rows.length, 100)} cotações mais recentes de {rows.length}.</p></div>}

  </section>
}

const eventLabels: Record<CorporateEvent['event_type'], string> = {
  STOCK_SPLIT: 'Desdobramento', REVERSE_SPLIT: 'Grupamento', DIVIDEND: 'Dividendo',
  JCP: 'JCP', AMORTIZATION: 'Amortização',
}
type EventDraft = {
  event_type: CorporateEvent['event_type']; effective_date: string; payment_date: string;
  amount_per_unit: string; conversion_factor: string; currency: string; notes: string
}
const emptyEventDraft = (currency: string): EventDraft => ({
  event_type: 'DIVIDEND', effective_date: localDate().slice(0, 10), payment_date: '',
  amount_per_unit: '', conversion_factor: '', currency, notes: '',
})

export function CorporateActionsPanel({ base, currency, busy, mutate, refreshVersion, readOnly = false }: {
  base: string; currency: string; busy: boolean; mutate: Mutate; refreshVersion: number; readOnly?: boolean
}) {
  const [events, setEvents] = useState<CorporateEvent[]>([])
  const [activity, setActivity] = useState<Activity[]>([])
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState<EventDraft>(() => emptyEventDraft(currency))
  const split = draft.event_type === 'STOCK_SPLIT' || draft.event_type === 'REVERSE_SPLIT'
  useEffect(() => {
    const controller = new AbortController(); setError('')
    Promise.all([
      api<CorporateEvent[]>(base + '/corporate-events', 'GET', undefined, controller.signal),
      api<Activity[]>(base + '/activity', 'GET', undefined, controller.signal),
    ]).then(([eventRows, activityRows]) => { setEvents(eventRows); setActivity(activityRows) })
      .catch(reason => { if (!controller.signal.aborted) setError(message(reason)) })
    return () => controller.abort()
  }, [base, version, refreshVersion])

  function reset() { setEditing(null); setDraft(emptyEventDraft(currency)) }
  function editEvent(event: CorporateEvent) {
    setEditing(event.id)
    setDraft({
      event_type: event.event_type, effective_date: event.effective_date,
      payment_date: event.payment_date ?? '', amount_per_unit: event.amount_per_unit == null ? '' : String(event.amount_per_unit),
      conversion_factor: event.conversion_factor == null ? '' : String(event.conversion_factor),
      currency: event.currency ?? currency, notes: event.notes,
    })
  }
  async function saveEvent(e: FormEvent) {
    e.preventDefault()
    const payload = {
      event_type: draft.event_type, effective_date: draft.effective_date,
      payment_date: draft.payment_date || null, notes: draft.notes,
      amount_per_unit: split ? null : draft.amount_per_unit,
      conversion_factor: split ? draft.conversion_factor : null,
      currency: split ? null : draft.currency,
    }
    const path = base + '/corporate-events' + (editing === null ? '' : '/' + editing)
    if (await mutate(() => api(path, editing === null ? 'POST' : 'PUT', payload), 'Evento corporativo salvo.')) {
      reset(); setVersion(value => value + 1)
    }
  }

  return <>
    <div className="section-heading"><div><h2>Eventos corporativos</h2><p>Eventos manuais são privados desta carteira; eventos do provedor são compartilhados pelo instrumento.</p></div></div>
    {!readOnly && <form className="quote-controls" onSubmit={saveEvent}><fieldset disabled={busy}><div className="form-grid quote-grid">
      <label>Tipo<select value={draft.event_type} onChange={e => setDraft({ ...draft, event_type: e.target.value as CorporateEvent['event_type'], amount_per_unit: '', conversion_factor: '' })}>{Object.entries(eventLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Data efetiva<input required type="date" max={localDate().slice(0, 10)} value={draft.effective_date} onChange={e => setDraft({ ...draft, effective_date: e.target.value })} /></label>
      {split ? <label>Fator de conversão<input required type="number" min="0.000000000001" step="any" value={draft.conversion_factor} onChange={e => setDraft({ ...draft, conversion_factor: e.target.value })} /></label> : <>
        <label>Valor por unidade<input required type="number" min="0" step="any" value={draft.amount_per_unit} onChange={e => setDraft({ ...draft, amount_per_unit: e.target.value })} /></label>
        <label>Moeda<input required maxLength={3} pattern="[A-Za-z]{3}" value={draft.currency} onChange={e => setDraft({ ...draft, currency: e.target.value.toUpperCase() })} /></label>
        <label>Data de pagamento<input type="date" min={draft.effective_date} value={draft.payment_date} onChange={e => setDraft({ ...draft, payment_date: e.target.value })} /></label>
      </>}
      <label className="wide">Observações<input maxLength={5000} value={draft.notes} onChange={e => setDraft({ ...draft, notes: e.target.value })} /></label>
    </div><div className="form-footer"><span>Eventos na data efetiva são aplicados antes das negociações do mesmo dia.</span><div className="row-actions">{editing !== null && <button type="button" className="button quiet" onClick={reset}>Cancelar</button>}<button className="button primary">{editing === null ? 'Adicionar evento' : 'Salvar alteração'}</button></div></div></fieldset></form>}
    {error && <div role="alert" className="alert error">{error}</div>}
    {!!events.length && <div className="table-wrap"><table><thead><tr><th>Data / tipo</th><th>Definição</th><th>Efeito na carteira</th><th>Origem</th><th>Ações</th></tr></thead><tbody>{[...events].reverse().map(event => <tr key={event.origin + '-' + event.id}>
      <td>{dateLabel(event.effective_date)}<small>{eventLabels[event.event_type]}</small></td><td>{event.conversion_factor != null ? 'Fator ' + fmt(event.conversion_factor, 6) : fmt(event.amount_per_unit, 6) + ' ' + event.currency}</td><td>{event.gross_amount != null ? 'Bruto ' + fmt(event.gross_amount, 4) + ' ' + event.currency : fmt(event.eligible_quantity, 6) + ' → posição ajustada'}</td><td>{event.origin === 'manual' ? 'Manual' : event.source}</td><td>{!readOnly && event.origin === 'manual' && <div className="row-actions"><button className="button quiet" disabled={busy} onClick={() => editEvent(event)}>Editar</button><button className="button danger" disabled={busy} onClick={() => {
        if (window.confirm('Excluir este evento? A atualização das posições ficará pendente.')) void mutate(() => api(base + '/corporate-events/' + event.id, 'DELETE'), 'Evento excluído. Atualização das posições pendente.').then(ok => { if (ok) { reset(); setVersion(value => value + 1) } })
      }}>Excluir</button></div>}</td>
    </tr>)}</tbody></table></div>}
    <div className="section-heading"><div><h2>Atividade do ativo</h2><p>Leitura cronológica unificada; transações e eventos continuam armazenados separadamente.</p></div></div>
    {!activity.length ? <div className="empty">Nenhuma atividade registrada.</div> : <div className="table-wrap"><table><thead><tr><th>Data</th><th>Atividade</th><th>Quantidade elegível</th><th>Valor / fator</th><th>Origem</th></tr></thead><tbody>{[...activity].sort((a, b) => b.date.localeCompare(a.date) || (a.kind === b.kind ? 0 : a.kind === 'CORPORATE_ACTION' ? -1 : 1)).map(row => row.kind === 'TRANSACTION' ? <tr key={'transaction-' + row.id}>
      <td>{dateLabel(row.date)}</td><td>{row.type === 'Buy' ? 'Compra' : 'Venda'}</td><td>{fmt(row.quantity, 6)}</td><td>{fmt(row.price, 4)} {row.currency}</td><td>{row.broker}</td>
    </tr> : <tr key={'event-' + row.origin + '-' + row.id}>
      <td>{dateLabel(row.date)}</td><td>{eventLabels[row.event_type]}</td><td>{fmt(row.eligible_quantity, 6)}</td><td>{row.conversion_factor != null ? 'Fator ' + fmt(row.conversion_factor, 6) : fmt(row.gross_amount, 4) + ' ' + row.currency}</td><td>{row.origin === 'manual' ? 'Manual' : row.source}</td>
    </tr>)}</tbody></table></div>}
  </>
}

