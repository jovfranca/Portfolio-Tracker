import { useState } from 'react'
import type { Transaction } from './api'
import { Link } from './navigation'
import { api } from './api'
import { dateLabel, EmptyState, ErrorState, fmt, message, PageHeader } from './ui'

type Rate = { reference_date: string; fallback_used: boolean; rates: { side: string; rate: string; source: string }[] }
export default function TransactionDetailPage({ transaction: tx, onEdit }: { transaction?: Transaction; onEdit?: (tx: Transaction) => void }) {
  const [rate, setRate] = useState<Rate | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  if (!tx) return <EmptyState action={<Link href="/transactions">Voltar para transações</Link>}>Transação não encontrada nesta carteira.</EmptyState>
  return <><PageHeader title={'Transação · ' + tx.asset} description={tx.type === 'Buy' ? 'Compra' : 'Venda'}><Link className="button outline" href="/transactions">← Transações</Link>{onEdit && <button className="button primary" onClick={() => onEdit(tx)}>Editar transação</button>}</PageHeader>
    <section className="panel"><dl className="detail-grid">{[
      ['Instrumento', tx.asset], ['Classe de alocação', tx.allocation_class], ['Negociação', dateLabel(tx.trade_date)], ['Liquidação', dateLabel(tx.settlement_date)], ['Moeda da transação', tx.transaction_currency], ['Quantidade', fmt(tx.quantity, 12)], ['Preço unitário', fmt(tx.price, 12)], ['FX salvo', fmt(tx.fx_rate, 12)], ['Corretagem', fmt(tx.brokerage_fee, 12)], ['Outras taxas', fmt(tx.other_fees, 12)], ['Corretora', tx.broker], ['Observações', tx.notes || '—'], ['Identificador', String(tx.id)],
    ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><Link className="button quiet" href={'/instruments/' + tx.instrument_id}>Abrir instrumento →</Link></section>
    {tx.transaction_currency !== 'BRL' && <section className="panel settings-section"><h2>PTAX de referência</h2><p>Consulta de compra e venda na liquidação. Não altera o FX salvo e não determina tratamento tributário.</p><button className="button outline" disabled={busy} onClick={async () => {
      setBusy(true); setError('')
      try { setRate(await api<Rate>('/rates/PTAX/' + tx.transaction_currency + '/' + tx.settlement_date)) } catch (e) { setError(message(e)) } finally { setBusy(false) }
    }}>{busy ? 'Consultando…' : 'Consultar PTAX'}</button>{error && <ErrorState error={error} />}{rate && <><p>Data utilizada: {dateLabel(rate.reference_date)}{rate.fallback_used && ' · observação anterior'}</p><ul>{rate.rates.map(r => <li key={r.side}>{r.side === 'BUY' ? 'Compra' : 'Venda'}: {fmt(r.rate, 6)} · {r.source}</li>)}</ul></>}</section>}
    <p className="method-note">Origem e metadados de criação/alteração não são expostos por operação nesta versão.</p>
  </>
}
