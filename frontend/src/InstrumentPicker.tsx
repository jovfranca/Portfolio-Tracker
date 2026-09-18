import { useState } from 'react'
import { api, type InstrumentSearchResult } from './api'

type Props = {
  query: string
  currency: string
  onSelect: (instrument: InstrumentSearchResult & { instrument_id: number }) => void | Promise<void>
}

export default function InstrumentPicker({ query, currency, onSelect }: Props) {
  const [results, setResults] = useState<InstrumentSearchResult[]>([])
  const [selection, setSelection] = useState<InstrumentSearchResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function run(task: () => Promise<void>) {
    setBusy(true); setError('')
    try { await task() } catch (e) { setError(e instanceof Error ? e.message : 'Não foi possível selecionar.') }
    finally { setBusy(false) }
  }
  return <div className="wide">
    <button type="button" className="button quiet" disabled={busy || !query.trim()} onClick={() => void run(async () => {
      setSelection(null)
      const found = await api<InstrumentSearchResult[]>('/instruments/search?q=' + encodeURIComponent(query))
      setResults(found)
      if (!found.length) setError('Nenhum resultado. Você pode cadastrar um instrumento manual.')
    })}>Pesquisar</button>
    <button type="button" className="button quiet" disabled={busy} onClick={() => {
      setResults([]); setSelection({ instrument_id: null, symbol: query, name: '', currency,
        asset_type: 'OTHER', status: 'ACTIVE', exchange: null, provider: null, provider_symbol: null })
    }}>Cadastrar instrumento manual</button>
    {results.map((item, index) => <button type="button" className="button outline" disabled={busy}
      key={index} onClick={() => void run(async () => {
        if (item.instrument_id !== null) {
          await onSelect({ ...item, instrument_id: item.instrument_id }); setResults([])
        } else { setSelection({ ...item, currency: item.currency || currency }); setResults([]) }
      })}>{item.symbol} · {item.name} · {item.currency || 'Moeda não informada'} · {item.status}{item.exchange ? ' · ' + item.exchange : ''}</button>)}
    {selection && <div className="form-grid">
      <p className="wide">Confirme a identidade do instrumento. {selection.provider_symbol && <>Símbolo no provedor: <strong>{selection.provider_symbol}</strong>.</>}</p>
      <label>Símbolo canônico<input maxLength={40} value={selection.symbol} onChange={e => setSelection({ ...selection, symbol: e.target.value.toUpperCase() })} placeholder="Ex.: PETR4 ou BTC" /></label>
      <label>Nome do instrumento<input maxLength={200} value={selection.name} onChange={e => setSelection({ ...selection, name: e.target.value })} /></label>
      <label>Moeda da cotação<input maxLength={3} value={selection.currency} onChange={e => setSelection({ ...selection, currency: e.target.value.toUpperCase() })} /></label>
      <label>Tipo de instrumento<select value={selection.asset_type} onChange={e => setSelection({ ...selection, asset_type: e.target.value as InstrumentSearchResult['asset_type'] })}>
        <option value="STOCK">Ação</option><option value="ETF">ETF</option><option value="CRYPTO">Criptomoeda</option><option value="OTHER">Outro</option>
      </select></label>
      <button type="button" className="button outline" disabled={busy || !/^[A-Z0-9.^=:/_-]+$/.test(selection.symbol) || !/^[A-Z]{3}$/.test(selection.currency)} onClick={() => void run(async () => {
        const { instrument_id: _id, ...values } = selection
        const created = await api<{ id: number }>('/instruments', 'POST', values)
        await onSelect({ ...selection, instrument_id: created.id }); setSelection(null)
      })}>Confirmar instrumento</button>
    </div>}
    {error && <p role="alert" className="negative">{error}</p>}
  </div>
}
