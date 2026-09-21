import { useEffect, useState } from 'react'
import { api, type InstrumentSearchResult } from './api'

type Props = {
  query: string
  onSelect: (instrument: InstrumentSearchResult & { instrument_id: number }) => void | Promise<void>
}

export default function InstrumentPicker({ query, onSelect }: Props) {
  const [category, setCategory] = useState('ALL')
  const [associateId, setAssociateId] = useState('')
  const [currencyConfirmed, setCurrencyConfirmed] = useState(false)
  const [localChoices, setLocalChoices] = useState<InstrumentSearchResult[]>([])
  const [results, setResults] = useState<InstrumentSearchResult[]>([])
  const [selection, setSelection] = useState<InstrumentSearchResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { setResults([]); setSelection(null); setError('') }, [query])
  async function run(task: () => Promise<void>) {
    setBusy(true); setError('')
    try { await task() } catch (e) { setError(e instanceof Error ? e.message : 'Não foi possível selecionar.') }
    finally { setBusy(false) }
  }
  return <div className="wide">
    <label>Categoria<select value={category} onChange={e => { setCategory(e.target.value); setResults([]) }}>
      <option value="ALL">Todos</option><option value="STOCK">Ações</option><option value="ETF">ETFs</option>
      <option value="CRYPTO">Crypto</option><option value="OTHER">Outros</option>
    </select></label>
    <button type="button" className="button quiet" disabled={busy || !query.trim()} onClick={() => void run(async () => {
      setSelection(null)
      const found = await api<InstrumentSearchResult[]>('/instruments/search?q=' + encodeURIComponent(query) + '&category=' + category)
      setResults(found); setLocalChoices([...new Map(found.filter(item => item.instrument_id !== null).map(item => [item.instrument_id, item])).values()])
      if (!found.length) setError('Nenhum resultado. Você pode cadastrar um instrumento manual.')
    })}>Pesquisar</button>
    <button type="button" className="button quiet" disabled={busy} onClick={() => {
      setResults([]); setAssociateId(''); setSelection({ instrument_id: null, symbol: query, name: '', currency: null,
        asset_type: 'OTHER', status: 'ACTIVE', exchange: null, provider: null, provider_symbol: null })
    }}>Cadastrar instrumento manual</button>
    {results.map((item, index) => <button type="button" className="button outline" disabled={busy}
      key={index} onClick={() => void run(async () => {
        if (item.instrument_id !== null && !item.provider_symbol) {
          await onSelect({ ...item, instrument_id: item.instrument_id }); setResults([])
        } else { setSelection(item); setAssociateId(item.instrument_id ? String(item.instrument_id) : ''); setCurrencyConfirmed(false); setResults([]) }
      })}>{item.symbol} · {item.name} · [{item.asset_type}] · {item.quote_currency || item.quote_currencies?.join('/') || item.currency || 'Moeda não informada'} · {item.status}{item.provider_exchange || item.exchange ? ' · ' + (item.provider_exchange || item.exchange) : ''}{item.provider_symbol && item.instrument_id ? ' · Associar cotação' : ''}</button>)}
    {selection && <div className="form-grid">
      <p className="wide">Confirme a identidade do instrumento. {selection.provider_symbol && <>Símbolo no provedor: <strong>{selection.provider_symbol}</strong>.</>}</p>
      <label>Símbolo canônico<input maxLength={40} value={selection.symbol} onChange={e => setSelection({ ...selection, symbol: e.target.value.toUpperCase() })} placeholder="Ex.: PETR4 ou BTC" /></label>
      {selection.provider_symbol && <label>Associar a instrumento existente<select value={associateId} onChange={e => setAssociateId(e.target.value)}>
        <option value="">Confirmar identidade acima</option>
        {localChoices.filter(item => item.asset_type === selection.asset_type).map(item => <option key={item.instrument_id} value={item.instrument_id!}>{item.symbol} · {item.name} · {item.exchange}</option>)}
      </select></label>}
      <label>Nome do instrumento<input maxLength={200} value={selection.name} onChange={e => setSelection({ ...selection, name: e.target.value })} /></label>
      <label>{selection.provider_symbol ? 'Moeda da cotação do provedor' : 'Moeda nativa (opcional)'}<input maxLength={3} value={(selection.provider_symbol ? selection.quote_currency : selection.currency) ?? ''} onChange={e => { setCurrencyConfirmed(false); setSelection({ ...selection, [selection.provider_symbol ? 'quote_currency' : 'currency']: e.target.value.toUpperCase() }) }} /></label>
      {selection.provider_symbol && <label className="wide"><input type="checkbox" checked={currencyConfirmed} onChange={e => setCurrencyConfirmed(e.target.checked)} />Verifiquei a moeda de cotação no provedor. Não use a moeda da transação como estimativa.</label>}
      <label>Tipo de instrumento<select value={selection.asset_type} onChange={e => setSelection({ ...selection, asset_type: e.target.value as InstrumentSearchResult['asset_type'] })}>
        <option value="STOCK">Ação</option><option value="ETF">ETF</option><option value="CRYPTO">Criptomoeda</option><option value="OTHER">Outro</option>
      </select></label>
      <button type="button" className="button outline" disabled={busy || !/^[A-Z0-9.^=:/_-]+$/.test(selection.symbol) || (!!selection.provider_symbol && (!currencyConfirmed || !/^[A-Z]{3}$/.test(selection.quote_currency ?? '')))} onClick={() => void run(async () => {
        const { instrument_id: _id, quote_currencies: _quotes, ...values } = selection
        const created = await api<InstrumentSearchResult & { id: number }>('/instruments', 'POST', { ...values, currency: values.currency || null, quote_currency: values.quote_currency || null, instrument_id: associateId ? Number(associateId) : null, provider_currency_confirmed: currencyConfirmed })
        await onSelect({ ...selection, ...created, instrument_id: created.id }); setSelection(null)
      })}>Confirmar instrumento</button>
    </div>}
    {error && <p role="alert" className="negative">{error}</p>}
  </div>
}
