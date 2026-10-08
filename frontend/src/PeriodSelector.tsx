import { useState } from 'react'
import { localDate } from './ui'

// Shared calendar boundaries for Overview and Performance, including month-end clamping.
export function periodStart(value: string, now = new Date()) {
  if (value === 'Max') return ''
  if (value === 'YTD') return now.getFullYear() + '-01-01'
  if (value === 'MTD') return now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-01'
  if (value === '1D') { const d = new Date(now); d.setDate(d.getDate() - 1); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10) }
  const d = new Date(now), day = d.getDate()
  d.setDate(1)
  d.setMonth(d.getMonth() - ({ '1M': 1, '3M': 3, '6M': 6, '1Y': 12, '5Y': 60 }[value] ?? 0))
  d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()))
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

export function usePeriod(initial = 'Max') {
  const [period, setPeriod] = useState(initial), [start, setStart] = useState(() => periodStart(initial)), [end, setEnd] = useState(localDate())
  const params = new URLSearchParams()
  if (start) params.set('start_date', start)
  if (end) params.set('end_date', end)
  function choose(value: string) {
    setPeriod(value)
    if (value !== 'custom') { setStart(periodStart(value)); setEnd(localDate()) }
  }
  return { period, start, end, setStart, setEnd, choose, params }
}

export default function PeriodSelector({ selection }: { selection: ReturnType<typeof usePeriod> }) {
  const { period, start, end, setStart, setEnd, choose } = selection
  return <section className="panel filter-bar" aria-label="Período dos resultados">
    <div className="period-buttons">{['1M', '3M', '6M', 'YTD', '1Y', 'Max', 'custom'].map(value =>
      <button key={value} aria-pressed={period === value} className={'button ' + (period === value ? 'primary' : 'quiet')} onClick={() => choose(value)}>
        {value === '1Y' ? '1A' : value === 'Max' ? 'Máx' : value === 'custom' ? 'Personalizado' : value}</button>)}</div>
    {period === 'custom' && <><label>Data inicial<input type="date" value={start} max={end} onChange={e => setStart(e.target.value)} /></label>
      <label>Data final<input type="date" value={end} min={start} max={localDate()} onChange={e => setEnd(e.target.value)} /></label></>}
  </section>
}
