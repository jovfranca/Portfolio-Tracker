import { useState, type FormEvent } from 'react'
import { api, type Portfolio, type Space, type Overview } from './api'
import { Link, navigate } from './navigation'
import { useResource } from './useResource'
import { dateLabel, EmptyState, fmt, PageHeader, type Mutate } from './ui'

export default function PortfoliosPage({ portfolios, portfolioId, creating, space, readOnly, busy, mutate, onCreated, onSelect, onUpdate }: { portfolios: Portfolio[]; portfolioId?: number; creating: boolean; space?: Space; readOnly: boolean; busy: boolean; mutate: Mutate; onCreated: (p: Portfolio) => void; onSelect: (id: number) => void; onUpdate: () => void }) {
  const portfolio = portfolios.find(p => p.id === portfolioId)
  const [name, setName] = useState(portfolio?.name ?? ''), [currency, setCurrency] = useState(portfolio?.display_currency ?? 'BRL'), [step, setStep] = useState(1)
  async function save(e: FormEvent) {
    e.preventDefault()
    if (creating && step === 1) { setStep(2); return }
    let saved: Portfolio | undefined
    if (await mutate(async () => {
      saved = await api<Portfolio>('/portfolios' + (creating ? '' : '/' + portfolioId), creating ? 'POST' : 'PUT', { name, display_currency: currency })
      return saved
    }, creating ? 'Carteira criada.' : 'Configurações da carteira salvas.')) {
      // Finish reloading the current context before selecting a newly created one.
      if (creating && saved) onCreated(saved)
      navigate(creating ? '/overview' : '/portfolios/' + portfolioId + '/settings')
    }
  }
  if (portfolioId && !portfolio) return <EmptyState>Carteira não encontrada no espaço financeiro ativo.</EmptyState>
  if (creating || portfolioId) return <><PageHeader title={creating ? 'Nova carteira' : 'Configurações da carteira'} description={'Espaço financeiro: ' + (space?.name ?? 'Nenhum')}><Link className="button outline" href="/portfolios">← Carteiras</Link></PageHeader>
    {readOnly ? <section className="panel settings-section"><h2>{portfolio?.name}</h2><p>Moeda de exibição: {portfolio?.display_currency}</p><p>Seu papel permite somente leitura.</p></section> : <form className="panel settings-section" onSubmit={save}><h2>{creating ? 'Etapa ' + step + ' de 2' : 'Geral'}</h2><fieldset disabled={busy}><div className="form-grid">
      {(!creating || step === 1) && <label>Nome da carteira<input required maxLength={120} value={name} onChange={e => setName(e.target.value)} /></label>}
      {(!creating || step === 2) && <label>Moeda de exibição<input required pattern="[A-Z]{3}" minLength={3} maxLength={3} value={currency} onChange={e => setCurrency(e.target.value.toUpperCase())} /></label>}
    </div><div className="form-footer"><span>A moeda de exibição altera a projeção dos valores. O histórico contábil nativo é preservado.</span>{creating && step === 2 && <button type="button" className="button quiet" onClick={() => setStep(1)}>Voltar</button>}<button className="button primary">{creating ? step === 1 ? 'Continuar' : 'Criar carteira' : 'Salvar carteira'}</button></div></fieldset></form>}
    {portfolio && <section className="panel settings-section"><h2>Dados</h2><p>Histórico atualizado até {dateLabel(portfolio.history_built_through)}.</p><p>{portfolio.dirty_from ? 'Atualização pendente desde ' + dateLabel(portfolio.dirty_from) : 'Nenhuma alteração pendente registrada.'}</p>{!readOnly && <button className="button outline" disabled={busy} onClick={() => { onSelect(portfolio.id); onUpdate() }}>Atualizar carteira</button>}</section>}
  </>
  return <><PageHeader title="Carteiras" description={'Organize seus investimentos no espaço ' + (space?.name ?? '')}>{!readOnly && <Link className="button primary" href="/portfolios/new">+ Nova carteira</Link>}</PageHeader><section className="panel"><div className="table-wrap"><table><thead><tr><th>Carteira</th><th>Moeda de exibição</th><th>Valor total</th><th>Última atualização do histórico</th><th>Status</th><th>Ações</th></tr></thead><tbody>{portfolios.map(p => <tr key={p.id}><td>{p.name}</td><td>{p.display_currency}</td><PortfolioValue portfolioId={p.id} /><td>{dateLabel(p.history_built_through)}</td><td>{p.dirty_from ? 'Atualização pendente' : p.history_built_through ? 'Histórico disponível' : 'Sem histórico'}</td><td><button className="button quiet" onClick={() => { onSelect(p.id); navigate('/overview') }}>Abrir</button><Link className="button outline" href={'/portfolios/' + p.id + '/settings'}>Configurações</Link></td></tr>)}</tbody></table></div>{!portfolios.length && <EmptyState>Crie sua primeira carteira neste espaço financeiro.</EmptyState>}</section></>
}

function PortfolioValue({ portfolioId }: { portfolioId: number }) {
  const resource = useResource<Overview>('/portfolios/' + portfolioId + '/overview')
  return <td>{resource.loading ? 'Carregando…' : resource.error ? 'Indisponível' : fmt(resource.data?.summary.total_value)}{resource.error && <button className="button quiet" onClick={resource.retry}>Tentar novamente</button>}</td>
}
