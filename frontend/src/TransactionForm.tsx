import { useState, type FormEvent } from 'react'
import { api, type Transaction, type Numeric, type InstrumentSearchResult } from './api'
import InstrumentPicker from './InstrumentPicker'
import { localDate, type Mutate } from './ui'
type OperationType = 'LISTED' | 'CRYPTO' | 'CUSTOM'
type Draft = Omit<Transaction, 'id' | 'portfolio_id' | 'fx_rate' | 'instrument_id' | 'transaction_currency_locked'> & { instrument_id: number | null; fx_rate: Numeric | '' }
const emptyDraft = (): Draft => ({ trade_date: localDate(), settlement_date: localDate(), type: 'Buy', asset: '', instrument_id: null, broker: '', allocation_class: '', transaction_currency: 'BRL', fx_rate: '', quantity: 1, price: 0, brokerage_fee: 0, other_fees: 0, notes: '' })
export default function TransactionForm({ portfolioId: selected, busy, mutate, onClose, transaction, instrument }: { portfolioId: number; busy: boolean; mutate: Mutate; onClose: () => void; transaction?: Transaction; instrument?: InstrumentSearchResult }) {
  const editing = transaction?.id ?? null
  const [operationType, setOperationType] = useState<OperationType>('LISTED')
  const [draft, setDraft] = useState<Draft>(() => transaction ? { ...transaction, fx_rate: transaction.fx_rate ?? '' } : instrument ? { ...emptyDraft(), instrument_id: instrument.instrument_id, asset: instrument.symbol, transaction_currency: instrument.currency ?? 'BRL' } : emptyDraft())
  const [listedCurrency, setListedCurrency] = useState<string | null>(transaction?.transaction_currency_locked ? transaction.transaction_currency : instrument && ['STOCK','ETF'].includes(instrument.asset_type) ? instrument.currency : null)
  const lockedCurrency = listedCurrency
  async function saveTransaction(e: FormEvent) {
    e.preventDefault()
    if (!draft.instrument_id) return
    const { id: _id, portfolio_id: _portfolioId, transaction_currency_locked: _locked, ...payload } = draft as Draft & Partial<Transaction>
    if (await mutate(() => api('/portfolios/' + selected + '/transactions' + (editing === null ? '' : '/' + editing), editing === null ? 'POST' : 'PUT', { ...payload, fx_rate: draft.fx_rate === '' ? null : draft.fx_rate }), 'Transação salva. Atualização das posições pendente.')) onClose()
  }
  return <>{editing === null && !instrument && <div className="asset-type-choices" aria-label="Tipo de ativo da nova operação">{([['LISTED','Ações e ETFs'],['CRYPTO','Cripto'],['CUSTOM','Personalizado']] as const).map(([value,label]) => <button key={value} type="button" className={'button ' + (operationType === value ? 'primary' : 'outline')} disabled={busy} onClick={() => { setOperationType(value); setDraft(emptyDraft()); setListedCurrency(null) }}>{label}</button>)}</div>}
<form className="panel transaction-form" onSubmit={saveTransaction}>
          <div className="section-heading"><h2>{editing === null ? 'Registrar transação' : 'Editar transação'}</h2><button type="button" className="button quiet" disabled={busy} onClick={() => onClose()}>Fechar</button></div>
          <fieldset disabled={busy}>
            <div className="form-grid">
              <label>Operação<select value={draft.type} onChange={e => setDraft({ ...draft, type: e.target.value as 'Buy' | 'Sell' })}><option value="Buy">Compra</option><option value="Sell">Venda</option></select></label>
              <label>Data da negociação<input required type="date" max={localDate().slice(0, 10)} value={draft.trade_date} onChange={e => setDraft({ ...draft, trade_date: e.target.value })} /></label>
              <label>Data da liquidação<input required type="date" min={draft.trade_date} value={draft.settlement_date} onChange={e => setDraft({ ...draft, settlement_date: e.target.value })} /></label>
              <label>Instrumento<input readOnly={draft.instrument_id !== null} required maxLength={40} value={draft.asset} onChange={e => setDraft({ ...draft, asset: e.target.value, instrument_id: null })} placeholder="Ex.: PETR4, Apple ou BTC" /></label>
              {draft.instrument_id === null ? <InstrumentPicker key={operationType ?? 'edit'} query={draft.asset} initialMode={operationType ?? 'LISTED'} showModeChoices={editing !== null} onSelect={item => {
                setListedCurrency(item.asset_type === 'STOCK' || item.asset_type === 'ETF' ? item.currency : null)
                setDraft(current => {
                  const currency = (item.asset_type === 'STOCK' || item.asset_type === 'ETF')
                    ? item.currency ?? current.transaction_currency
                    : (item.is_custom ? item.currency : null) ?? current.transaction_currency
                  return { ...current, instrument_id: item.instrument_id, asset: item.symbol, transaction_currency: currency,
                    fx_rate: currency === current.transaction_currency ? current.fx_rate : '' }
                })
              }} /> : <div className="selected-instrument wide"><span>Instrumento selecionado: <strong>{draft.asset}</strong></span><button type="button" className="button quiet" onClick={() => { setDraft({ ...draft, instrument_id: null, asset: '' }); setListedCurrency(null) }}>Trocar ativo</button></div>}
              <label>Corretora<input required maxLength={120} value={draft.broker} onChange={e => setDraft({ ...draft, broker: e.target.value })} /></label>
              <label>Classe de alocação<input required maxLength={120} value={draft.allocation_class} onChange={e => setDraft({ ...draft, allocation_class: e.target.value })} placeholder="Ex.: Ações Brasil" /></label>
              <label>Moeda da transação<input disabled={!!lockedCurrency} required maxLength={3} pattern="[A-Za-z]{3}" value={draft.transaction_currency} onChange={e => { const currency = e.target.value.toUpperCase(); setDraft({ ...draft, transaction_currency: currency, fx_rate: currency === draft.transaction_currency ? draft.fx_rate : '' }) }} placeholder="BRL" /></label>
              <label>Taxa FX<input type="number" min="0.000000000001" step="any" value={draft.fx_rate} disabled={draft.transaction_currency === 'BRL'} onChange={e => setDraft({ ...draft, fx_rate: e.target.value })} placeholder={draft.transaction_currency === 'BRL' ? '1' : 'Automática'} /></label>
              {([['quantity', 'Quantidade'], ['price', 'Preço unitário'], ['brokerage_fee', 'Corretagem'], ['other_fees', 'Outras taxas']] as const).map(([key, label]) => <label key={key}>{label}<input required type="number" min={key === 'quantity' ? '0.000000000001' : '0'} step="any" value={draft[key]} onChange={e => setDraft({ ...draft, [key]: e.target.value } as Draft)} /></label>)}
              <label className="wide">Observações<input maxLength={5000} value={draft.notes} onChange={e => setDraft({ ...draft, notes: e.target.value })} /></label>
            </div>
            <div className="form-footer"><span>FX vazio usa a taxa histórica da data de liquidação; o valor salvo não muda depois.</span><button className="button primary" disabled={!draft.instrument_id}>{busy ? 'Salvando…' : 'Salvar transação'}</button></div>
          </fieldset>
        </form>
  </>
}
