import { useState, type ReactNode } from 'react'
import type { AuthState, Overview, Portfolio, Space } from './api'
import { Link, navigate } from './navigation'
import { navigation, addActions, type AddAction } from './text'
import { dateLabel } from './ui'

function Icon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    search: <><circle cx="10" cy="10" r="6" /><path d="m15 15 6 6" /></>,
    bell: <><path d="M6 9a6 6 0 0 1 12 0v6l3 3H3l3-3Z" /><path d="M10 21h4" /></>,
    menu: <path d="M3 6h18M3 12h18M3 18h18" />,
    more: <><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></>,
    help: <><circle cx="12" cy="12" r="9" /><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 5M12 17h.01" /></>,
    settings: <><path d="m10 3-1 3-3 1-3 3 2 2-1 3 3 3 3-1 2 2 3-1 1-3 3-1 2-3-2-2 1-3-3-3-3 1-2-2Z" /><circle cx="12" cy="12" r="3" /></>,
    overview: <><path d="m3 10 9-7 9 7v10H3Z" /><path d="M9 20v-7h6v7" /></>,
    positions: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M8 4v16M8 10h13" /></>,
    transactions: <><path d="M3 7h18m-4-4 4 4-4 4M21 17H3m4-4-4 4 4 4" /></>,
    performance: <><path d="M4 20V4M4 20h17M7 15l4-5 4 2 6-8" /></>,
    data: <><path d="m3 16 5-7 4 4 4-8 5 3" /><path d="M3 21h18" /></>,
    instruments: <><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0" /></>,
  }
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] ?? <><circle cx="12" cy="12" r="8" /><path d="M12 8v8M8 12h8" /></>}</svg>
}
function Sidebar({ path, collapsed, onCollapse }: { path: string; collapsed: boolean; onCollapse: () => void }) {
  return <aside className={'sidebar' + (collapsed ? ' collapsed' : '')}>
    <Link className="brand" href="/overview" aria-label="Quintrion — Visão geral"><img src={collapsed ? '/brand/quintrion_symbol_small.svg' : '/brand/quintrion_horizontal_master_dark.svg'} alt="Quintrion" /></Link>
    <button className="sidebar-collapse" onClick={onCollapse} aria-label={collapsed ? 'Expandir navegação' : 'Recolher navegação'}><Icon name="menu" /></button>
    <nav aria-label="Navegação principal">{navigation.map(([href, label, icon], index) => <div key={href}>
      {(index === 1 || index === 4) && <div className="nav-label">{index === 1 ? 'INVESTIMENTOS' : 'DADOS E FERRAMENTAS'}</div>}
      <Link title={label} className={'nav-item ' + (path.split('/')[1] === href.split('/')[1] ? 'active' : '')} href={href} aria-current={path.split('/')[1] === href.split('/')[1] ? 'page' : undefined}><Icon name={icon} /><span>{label}</span></Link>
    </div>)}</nav>
    <div className="sidebar-footer"><Link className="nav-item" href="/settings/spaces" aria-current={path.startsWith('/settings') ? 'page' : undefined}><Icon name="settings" /><span>Configurações</span></Link><Link className="nav-item" href="/help"><Icon name="help" /><span>Ajuda</span></Link><small>Seu patrimônio, em perspectiva.</small></div>
  </aside>
}
function GlobalAddMenu({ disabled, onAdd }: { disabled: boolean; onAdd: (action: AddAction) => void }) {
  const [open, setOpen] = useState(false)
  return <div className="menu-anchor"><button className="button primary global-add" disabled={disabled} aria-expanded={open} onClick={() => setOpen(!open)}>+ Adicionar</button>
    {open && <><button className="menu-dismiss" aria-label="Fechar menu Adicionar" onClick={() => setOpen(false)} /><div className="dropdown" aria-label="Adicionar">{addActions.map(([action, label]) => <button key={action} onClick={() => { setOpen(false); onAdd(action) }}>{label}</button>)}</div></>}
  </div>
}
export default function AppShell({ path, auth, space, portfolios, selected, overview, busy, loading, onSelect, onSwitch, onLogout, onUpdate, onAdd, children }: {
  path: string; auth: AuthState; space?: Space; portfolios: Portfolio[]; selected: number | null; overview: Overview | null; busy: boolean; loading: boolean;
  onSelect: (id: number) => void; onSwitch: (id: number) => void; onLogout: () => void; onUpdate: () => void; onAdd: (action: AddAction) => void; children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false)
  const [account, setAccount] = useState(false)
  const [more, setMore] = useState(false)
  const readOnly = !space || space.role === 'VIEWER'
  const section = navigation.find(([href]) => href.split('/')[1] === path.split('/')[1])?.[1] ?? (path.startsWith('/account') ? 'Minha conta' : path.startsWith('/portfolios') ? 'Carteiras' : 'Configurações')
  const status = overview?.summary.history_status
  return <div className={'app' + (collapsed ? ' shell-collapsed' : '')}>
    <a className="skip-link" href="#page-content">Pular para o conteúdo</a><Sidebar path={path} collapsed={collapsed} onCollapse={() => setCollapsed(!collapsed)} />
    <main><header className="topbar"><span className="context-title">{section}</span><div className="context-selectors">
      {auth.households.length > 1 && <label className="context-picker">Espaço financeiro<select aria-label="Espaço financeiro" value={space?.id ?? ''} disabled={busy} onChange={e => onSwitch(Number(e.target.value))}>{auth.households.map(h => <option key={h.id} value={h.id}>{h.name}</option>)}</select></label>}
      <label className="context-picker">Carteira<select aria-label="Carteira" id="portfolio" value={selected ?? ''} disabled={busy || !portfolios.length} onChange={e => onSelect(Number(e.target.value))}>
        {!portfolios.length && <option value="">Nenhuma carteira</option>}{portfolios.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select></label><details className="portfolio-menu"><summary aria-label="Opções da carteira">⋯</summary><div className="dropdown"><Link href="/portfolios">Gerenciar carteiras</Link>{selected !== null && <Link href={'/portfolios/' + selected + '/settings'}>Configurações da carteira</Link>}{auth.households.length > 1 && <Link href="/settings/spaces">Gerenciar espaços financeiros</Link>}</div></details>
    </div><div className="topbar-actions">
      <Link className="data-status" href="/data/status">{busy ? 'Atualizando…' : status === 'pending' ? 'Atualização pendente' : status && status !== 'complete' ? 'Dados precisam de atenção' : overview ? 'Atualizado' : 'Status dos dados'}<small>{dateLabel(overview?.summary.history_built_through)}</small></Link>
      {!readOnly && <><button className="button outline update-button" disabled={selected === null || busy || loading} onClick={onUpdate}>{busy ? 'Atualizando…' : 'Atualizar carteira'}</button><GlobalAddMenu disabled={selected === null || busy || loading} onAdd={onAdd} /></>}
      <button className="icon-button extension-point" disabled title="Busca global em breve" aria-label="Busca global em breve"><Icon name="search" /></button><button className="icon-button extension-point" disabled title="Notificações em breve" aria-label="Notificações em breve"><Icon name="bell" /></button>
      <div className="menu-anchor"><button className="avatar" aria-label="Menu da conta" aria-expanded={account} onClick={() => setAccount(!account)}>{auth.user.display_name.slice(0, 2).toUpperCase()}</button>
        {account && <><button className="menu-dismiss" aria-label="Fechar menu da conta" onClick={() => setAccount(false)} /><div className="dropdown account-menu"><strong>{auth.user.display_name}</strong>{[['/account/profile', 'Meu perfil'], ['/portfolios', 'Carteiras'], ['/settings/spaces', 'Configurações'], ['/account/preferences', 'Preferências'], ['/account/preferences', 'Tema']].map(([href, label]) => <Link key={label} href={href} onClick={() => setAccount(false)}>{label}</Link>)}<button onClick={onLogout}>Sair</button></div></>}
      </div>
    </div></header><div className="content" id="page-content" tabIndex={-1}>{children}</div></main>
    <nav className="mobile-nav" aria-label="Navegação móvel">{navigation.slice(0, 4).map(([href, label, icon]) => <Link key={href} href={href} aria-current={path.startsWith(href) ? 'page' : undefined}><Icon name={icon} /><span>{label}</span></Link>)}<button onClick={() => setMore(!more)} aria-expanded={more}><Icon name="more" />Mais</button></nav>
    {more && <div className="mobile-more panel">{[['/data/status', 'Dados de mercado'], ['/instruments', 'Instrumentos'], ['/portfolios', 'Carteiras'], ['/account/profile', 'Conta'], ['/settings/spaces', 'Configurações'], ['/help', 'Ajuda']].map(([href, label]) => <button key={href} onClick={() => { setMore(false); navigate(href) }}>{label}</button>)}</div>}
  </div>
}
