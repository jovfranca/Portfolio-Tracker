import { useEffect, useRef, type ReactNode } from 'react'
import type { Numeric } from './api'
import { Link } from './navigation'

export const fmt = (value: Numeric | null | undefined, digits = 2) => value == null ? '—' : Number(value).toLocaleString('pt-BR', { maximumFractionDigits: digits, minimumFractionDigits: digits })
export const money = (value: Numeric | null | undefined, currency: string) => {
  if (value == null) return '—'
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '—'
  if (currency === 'USD') return 'US$ ' + amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  try { return new Intl.NumberFormat('pt-BR', { style: 'currency', currency }).format(amount) } catch { return currency + ' ' + fmt(value) }
}
export const dateLabel = (value: string | null | undefined) => value ? value.slice(0, 10).split('-').reverse().join('/') : '—'
export const message = (error: unknown) => error instanceof Error ? error.message : 'Não foi possível concluir.'
export const localDate = () => {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}
export type Mutate = (task: () => Promise<unknown>, success: string) => Promise<boolean>
export function PageHeader({ title, description, children }: { title: string; description?: string; children?: ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">QUINTRION · INVESTIMENTOS</div><h1>{title}</h1>{description && <p>{description}</p>}</div><div className="page-actions">{children}</div></div>
}
export function MetricCard({ label, value, context, featured = false }: { label: string; value: ReactNode; context?: ReactNode; featured?: boolean }) {
  return <article className={'metric' + (featured ? ' featured' : '')}><span>{label}</span><strong>{value}</strong>{context && <small>{context}</small>}</article>
}
const statusLabels: Record<string, string> = {
  complete: 'Completo', pending: 'Atualização pendente', missing_price: 'Cotação pendente', missing_price_history: 'Cotação pendente',
  missing_fx: 'Câmbio pendente', missing_benchmark: 'Benchmark pendente', missing_actions: 'Evento pendente',
  missing_price_and_fx: 'Cotação e câmbio pendentes', incomplete_history: 'Histórico incompleto', incomplete: 'Incompleto',
  ACTIVE: 'Ativo', INACTIVE: 'Inativo', DELISTED: 'Deslistado', CLOSED: 'Encerrado',
}
export function StatusBadge({ status }: { status: string }) {
  return <span className={'badge status-' + (status === 'complete' || status === 'ACTIVE' ? 'complete' : 'pending')}>{statusLabels[status] ?? 'Dados incompletos'}</span>
}
export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) { return <div className="empty"><p>{children}</p>{action}</div> }
export function LoadingState() { return <div className="panel empty skeleton" role="status">Carregando…</div> }
export function ErrorState({ error, retry }: { error: string; retry?: () => void }) {
  return <div role="alert" className="alert error">{error}{retry && <button className="button quiet" onClick={retry}>Tentar novamente</button>}</div>
}
export function Tabs({ items, active }: { items: readonly (readonly [string, string])[]; active: string }) {
  return <nav className="tabs" aria-label="Seções da página">{items.map(([path, label]) => <Link key={path} href={path} aria-current={path === active ? 'page' : undefined}>{label}</Link>)}</nav>
}
export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    ref.current?.showModal()
    return () => { ref.current?.close(); previous?.focus() }
  }, [])
  return <dialog ref={ref} className="action-dialog" aria-label={title} onCancel={e => { e.preventDefault(); onClose() }}>
    <header><h2>{title}</h2><button type="button" className="button quiet" onClick={onClose} aria-label="Fechar formulário">Fechar</button></header>{children}
  </dialog>
}
