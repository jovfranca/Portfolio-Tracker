import { lazy, Suspense, type ComponentProps } from 'react'
import type { EChartsCoreOption } from 'echarts/core'
import type { Performance, PeriodAnalytics } from './api'
import { dateLabel, fmt, money } from './ui'

const LazyChart = lazy(() => import('./FinancialChart'))
export function FinancialChart(props: ComponentProps<typeof LazyChart>) {
  return <Suspense fallback={<div className={'financial-chart ' + (props.className ?? '')} role="status">Carregando gráfico…</div>}><LazyChart {...props} /></Suspense>
}

export function historyOption(rows: Performance[], analytics: PeriodAnalytics | null, mode: 'return' | 'value', currency: string): EChartsCoreOption {
  const returns = new Map(analytics?.return_series?.map(r => [r.date, r.return_pct]))
  const percent = mode === 'return'
  const format = (value: unknown) => value == null ? '—' : percent ? fmt(Number(value)) + '%' : money(Number(value), currency)
  const primary = rows.map(r => r.status !== 'complete' || r.reporting_currency !== currency ? null :
    percent ? returns.get(r.date) ?? null : r.market_value == null ? null : Number(r.market_value))
  return {
    animation: false,
    grid: { left: 68, right: 22, top: 26, bottom: 94 },
    tooltip: { trigger: 'axis', confine: true, backgroundColor: '#0B1F3B', borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 12 }, valueFormatter: format,
      axisPointer: { type: 'line', snap: true, lineStyle: { color: '#0E7C86', type: 'dashed' } } },
    xAxis: { type: 'category', data: rows.map(r => dateLabel(r.date)), boundaryGap: false,
      axisLine: { lineStyle: { color: '#66708544' } }, axisTick: { show: false },
      axisLabel: { fontSize: 11, color: '#536680', hideOverlap: true }, splitLine: { show: true, lineStyle: { color: '#6670850e' } } },
    yAxis: { type: 'value', scale: true, axisLabel: { fontSize: 11, color: '#536680', formatter: (v: number) => percent ? fmt(v, 0) + '%' :
      new Intl.NumberFormat(currency === 'USD' ? 'en-US' : 'pt-BR', { notation: 'compact', maximumFractionDigits: 1 }).format(v) },
      splitLine: { lineStyle: { color: '#66708518' } } },
    dataZoom: [{ type: 'inside', xAxisIndex: 0, zoomOnMouseWheel: 'ctrl', moveOnMouseWheel: 'shift', moveOnMouseMove: true, preventDefaultMouseMove: false },
      { type: 'slider', xAxisIndex: 0, bottom: 18, height: 32, borderColor: '#66708522',
        backgroundColor: '#66708508', fillerColor: '#0E7C8618', handleStyle: { color: '#0E7C86' },
        dataBackground: { lineStyle: { color: '#0E7C86' }, areaStyle: { color: '#22D3A1' } }, brushSelect: true }],
    series: [{ name: 'Minha carteira', type: 'line', data: primary, connectNulls: false, showSymbol: false,
      symbol: 'circle', symbolSize: 9, lineStyle: { width: 2.5, color: '#13b996' }, itemStyle: { color: '#13b996', borderColor: '#fff', borderWidth: 2 },
      emphasis: { scale: true }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [{ offset: 0, color: '#22D3A15a' }, { offset: 1, color: '#22D3A104' }] } } },
      ...(percent ? (analytics?.benchmarks ?? []).filter(b => b.status !== 'unsupported').map(b => {
        const values = new Map(b.series.map(r => [r.date, r.return_pct]))
        return { name: b.code, type: 'line', data: rows.map(r => values.get(r.date) ?? null), connectNulls: false,
          showSymbol: false, symbolSize: 8, lineStyle: { color: '#6B6FF2', type: 'dashed', width: 1.5 }, itemStyle: { color: '#6B6FF2' } }
      }) : [])],
  }
}
