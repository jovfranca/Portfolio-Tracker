import { useEffect, useState } from 'react'
import { api, InstrumentSearchResult } from './api'

type Props = {
  query: string
  onSelect: (instrument: InstrumentSearchResult & { instrument_id: number }) => void | Promise<void>
  initialMode?: Mode
  showModeChoices?: boolean
}
type Mode = 'LISTED' | 'CRYPTO' | 'FIXED_INCOME' | 'CUSTOM'

export default function InstrumentPicker({ query, onSelect, initialMode = 'LISTED', showModeChoices = true }: Props) {
  const [mode, setMode] = useState<Mode>(initialMode)
  const [results, setResults] = useState<InstrumentSearchResult[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [custom, setCustom] = useState({ name: '', symbol: query.toUpperCase(), currency: 'BRL', asset_type: initialMode === 'FIXED_INCOME' ? 'FIXED_INCOME' : 'OTHER' })
  useEffect(() => {
    if (mode === 'CUSTOM' && initialMode === 'CUSTOM') setCustom(current => ({ ...current, symbol: query.toUpperCase() }))
  }, [query, mode, initialMode])

  const run = async (task: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await task() } catch (reason) { setError(reason instanceof Error ? reason.message : 'Falha ao pesquisar.') }
    finally { setBusy(false) }
  }
  const chooseMode = (next: Mode) => {
    setMode(next); setResults([]); setError('')
    if (next === 'CUSTOM') setCustom(current => ({ ...current, symbol: query.toUpperCase() }))
  }

  return <div className="instrument-picker wide">
    {showModeChoices && <div className="asset-type-choices" aria-label="Tipo de seleção do ativo">
      <button type="button" className={'button ' + (mode === 'LISTED' ? 'primary' : 'outline')} onClick={() => chooseMode('LISTED')}>Ações e ETFs</button>
      <button type="button" className={'button ' + (mode === 'CRYPTO' ? 'primary' : 'outline')} onClick={() => chooseMode('CRYPTO')}>Cripto</button>
      <button type="button" className={'button ' + (mode === 'CUSTOM' ? 'primary' : 'outline')} onClick={() => chooseMode('CUSTOM')}>Personalizado</button>
    </div>}

    {mode !== 'CUSTOM' && <>
      <button type="button" className="button outline" disabled={busy || !query.trim()} onClick={() => void run(async () => {
        const found = await api<InstrumentSearchResult[]>('/instruments/search?q=' + encodeURIComponent(query) + '&category=' + mode)
        setResults(found)
        if (!found.length) setError('Nenhum instrumento do catálogo encontrado. Crie um instrumento manual para continuar.')
      })}>{busy ? 'Pesquisando…' : 'Pesquisar no catálogo'}</button>
      {!!results.length && <div className="instrument-results" role="list">
        {results.map(item => <button type="button" role="listitem" disabled={busy} key={item.instrument_id!} onClick={() => void run(async () => { await onSelect({ ...item, instrument_id: item.instrument_id! }) })}>
          <strong>{item.symbol}</strong><span>{item.name}</span>
          <small>{item.asset_type} · {item.exchange || 'Mercado global'} · {item.currency || item.quote_currencies?.[0] || 'Moeda variável'}</small>
          <em>Selecionar</em>
        </button>)}
      </div>}
      {initialMode === 'FIXED_INCOME' && <button type="button" className="button quiet" onClick={() => chooseMode('CUSTOM')}>Criar instrumento de renda fixa</button>}
    </>}

    {mode === 'CUSTOM' && <div className="custom-instrument-form">
      <p>{initialMode === 'FIXED_INCOME' ? 'Instrumentos de renda fixa são identidades canônicas; as condições do investimento ficam no lote.' : 'Ativos personalizados não consultam o provedor. Informe preços manualmente na área de Cotações.'}</p>
      <label>Nome do ativo<input maxLength={200} value={custom.name} onChange={event => setCustom({ ...custom, name: event.target.value })} /></label>
      <label>Símbolo<input maxLength={40} value={custom.symbol} onChange={event => setCustom({ ...custom, symbol: event.target.value.toUpperCase() })} /></label>
      <label>Moeda<input maxLength={3} value={custom.currency} onChange={event => setCustom({ ...custom, currency: event.target.value.toUpperCase() })} /></label>
      {initialMode !== 'FIXED_INCOME' && <label>Tipo do ativo<select value={custom.asset_type} onChange={event => setCustom({ ...custom, asset_type: event.target.value })}>
        <option value="OTHER">Outro / privado</option><option value="STOCK">Ação</option><option value="ETF">ETF</option><option value="CRYPTO">Cripto</option>
      </select></label>}
      <button type="button" className="button outline" disabled={busy || !custom.name || !custom.symbol || !/^[A-Z]{3}$/.test(custom.currency)} onClick={() => void run(async () => {
        const created = await api<InstrumentSearchResult & { id: number }>('/instruments/custom', 'POST', custom)
        await onSelect({ ...created, currency: custom.currency, instrument_id: created.id, provider: null, provider_symbol: null, is_custom: true })
      })}>Criar ativo personalizado</button>
    </div>}
    {error && <div role="alert" className="alert error">{error}</div>}
  </div>
}
