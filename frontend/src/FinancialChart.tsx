import { useEffect, useRef } from 'react'
import { init, use, type EChartsCoreOption } from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([LineChart, PieChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

export default function FinancialChart({ option, label, className = '', onRange }: {
  option: EChartsCoreOption; label: string; className?: string; onRange?: (start: number, end: number) => void
}) {
  const element = useRef<HTMLDivElement>(null)
  const range = useRef(onRange)
  const latestOption = useRef(option)
  const repaint = useRef<() => void>(() => {})
  range.current = onRange
  latestOption.current = option
  useEffect(() => {
    const el = element.current!
    const chart = init(el)
    const render = () => {
      const current = latestOption.current
      const style = getComputedStyle(document.documentElement)
      const color = style.getPropertyValue('--muted').trim()
      const xAxis = current.xAxis as { axisLabel?: Record<string, unknown> } | undefined
      const yAxis = current.yAxis as { axisLabel?: Record<string, unknown> } | undefined
      const zoom = (chart.getOption()?.dataZoom as { start: number; end: number }[] | undefined)?.[0]
      const dataZoom = current.dataZoom as Record<string, unknown>[] | undefined
      chart.setOption({ ...current, textStyle: { fontFamily: 'Inter, sans-serif', color },
        ...(zoom && dataZoom ? { dataZoom: dataZoom.map(config => ({ ...config, start: zoom.start, end: zoom.end })) } : {}),
        ...(xAxis ? { xAxis: { ...xAxis, axisLabel: { ...xAxis.axisLabel, color } } } : {}),
        ...(yAxis ? { yAxis: { ...yAxis, axisLabel: { ...yAxis.axisLabel, color } } } : {}),
      }, true)
    }
    repaint.current = render
    render()
    chart.on('datazoom', () => {
      const zoom = (chart.getOption().dataZoom as { start: number; end: number }[])?.[0]
      if (zoom) range.current?.(zoom.start, zoom.end)
    })
    const resize = new ResizeObserver(() => chart.resize())
    resize.observe(el)
    const theme = new MutationObserver(render)
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    media.addEventListener('change', render)
    return () => { resize.disconnect(); theme.disconnect(); media.removeEventListener('change', render); chart.dispose() }
  }, [])
  useEffect(() => { repaint.current() }, [option])
  return <div ref={element} className={'financial-chart ' + className} role="img" aria-label={label} />
}

