import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, type AuthConfig, type AuthState, type Invitation, type Member, type Role, type Space } from './api'
import GoogleButton from './GoogleButton'

const errorText = (e: unknown) => e instanceof Error ? e.message : 'Não foi possível concluir.'
const roles: Role[] = ['EDITOR', 'VIEWER', 'OWNER']
const expiration = (value: string) => new Date(value).toLocaleString('pt-BR')

export default function SettingsPage({ auth, space, onRefresh, onSwitch, onLinked }: {
  auth: AuthState; space?: Space; onRefresh: (preferredSpace?: number) => Promise<void>
  onSwitch: (id: number) => void; onLinked: (state: AuthState) => void
}) {
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [members, setMembers] = useState<Member[]>([])
  const [invitations, setInvitations] = useState<Invitation[]>([])
  const [created, setCreated] = useState<(Invitation & { token: string }) | null>(null)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('EDITOR')
  const [token, setToken] = useState('')
  const [linkConfig, setLinkConfig] = useState<AuthConfig | null>(null)
  const owner = space?.role === 'OWNER'
  const spaceId = space?.id
  const base = '/households/' + spaceId
  const googleLinked = auth.user.identities.some(identity => identity.provider === 'GOOGLE')

  const loadAdministration = useCallback(async (signal?: AbortSignal) => {
    if (spaceId === undefined) return
    setLoading(true)
    try {
      const [people, pending] = await Promise.all([
        api<Member[]>(base + '/members', 'GET', undefined, signal),
        owner ? api<Invitation[]>(base + '/invitations', 'GET', undefined, signal) : Promise.resolve([]),
      ])
      if (!signal?.aborted) { setMembers(people); setInvitations(pending) }
    } finally { if (!signal?.aborted) setLoading(false) }
  }, [base, owner, spaceId])

  useEffect(() => {
    const controller = new AbortController()
    void loadAdministration(controller.signal).catch(e => {
      if (!controller.signal.aborted) setError(errorText(e))
    })
    return () => controller.abort()
  }, [loadAdministration])

  async function mutate(work: () => Promise<void>, success: string) {
    setBusy(true); setError(''); setNotice('')
    try { await work(); setNotice(success) }
    catch (e) { setError(errorText(e)) }
    finally { setBusy(false) }
  }

  function createSpace(e: FormEvent) {
    e.preventDefault()
    void mutate(async () => {
      const added = await api<Space>('/households', 'POST', { name })
      await onRefresh(added.id)
      setName('')
    }, 'Espaço criado.')
  }

  function renameSpace(e: FormEvent<HTMLFormElement>, id: number) {
    e.preventDefault()
    const name = String(new FormData(e.currentTarget).get('name'))
    void mutate(async () => {
      await api<Space>('/households/' + id, 'PUT', { name })
      await onRefresh()
    }, 'Nome do espaço atualizado.')
  }

  function changeRole(e: FormEvent<HTMLFormElement>, member: Member) {
    e.preventDefault()
    const role = String(new FormData(e.currentTarget).get('role'))
    void mutate(async () => {
      await api(base + '/members/' + member.id, 'PUT', { role })
      await onRefresh()
      if (member.user_id !== auth.user.id || role === 'OWNER') await loadAdministration()
    }, 'Permissão atualizada.')
  }

  function removeMember(member: Member) {
    if (!window.confirm('Remover o acesso de ' + member.display_name + ' a este espaço?')) return
    void mutate(async () => {
      await api(base + '/members/' + member.id, 'DELETE')
      await onRefresh()
      if (member.user_id !== auth.user.id) await loadAdministration()
    }, 'Membro removido.')
  }

  function invite(e: FormEvent) {
    e.preventDefault()
    void mutate(async () => {
      const result = await api<Invitation & { token: string }>(base + '/invitations', 'POST', { email, role })
      setCreated(result); setEmail('')
      await loadAdministration()
    }, 'Convite criado. Compartilhe o token com a pessoa convidada.')
  }

  function revoke(invitation: Invitation) {
    void mutate(async () => {
      await api(base + '/invitations/' + invitation.id, 'DELETE')
      if (created?.id === invitation.id) setCreated(null)
      await loadAdministration()
    }, 'Convite revogado.')
  }

  function accept(e: FormEvent) {
    e.preventDefault()
    void mutate(async () => {
      await api<Space>('/invitations/accept', 'POST', { token: token.trim() })
      await onRefresh()
      setToken('')
    }, 'Convite aceito. O espaço está disponível no seletor acima.')
  }

  return <main className="settings-page"><div className="content">
    <div className="page-heading"><div><h1>Settings</h1><p>Conta e administração dos espaços financeiros.</p></div>
      <a className="button outline" href="#/">Voltar para carteiras</a></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {notice && <div className="alert success" role="status">{notice}</div>}
    <section className="panel settings-section" aria-labelledby="account-heading">
      <h2 id="account-heading">Conta e identidades</h2>
      <p>Nome: <strong>{auth.user.display_name}</strong></p>
      <ul>{auth.user.identities.map((identity, index) => <li key={index}>
        {identity.provider === 'GOOGLE' ? 'Google' : identity.provider} — Conectado
        {identity.email && <> — {identity.email} — {identity.email_verified ? 'Verificado' : 'Não verificado'}</>}
        {!identity.email && ' — Email não informado'}
      </li>)}</ul>
      {!googleLinked && <><p>Google — Não conectado</p>
        <button className="button outline" disabled={busy} onClick={() => {
          void mutate(async () => setLinkConfig(await api<AuthConfig>('/auth/config')), '')
        }}>Vincular Google</button>
        {linkConfig && <GoogleButton config={linkConfig} onSuccess={onLinked} link />}</>}
    </section>
    <section className="panel settings-section" aria-labelledby="spaces-heading">
      <h2 id="spaces-heading">Espaços financeiros</h2>
      <div className="table-wrap"><table><thead><tr><th>Espaço</th><th>Seu papel</th><th>Ações</th></tr></thead>
        <tbody>{auth.households.map(h => <tr key={h.id}>
          <td>{h.name}{h.id === space?.id && <small>Espaço selecionado</small>}</td><td>{h.role}</td>
          <td><div className="settings-actions">{h.id !== space?.id && <button className="button quiet" disabled={busy} onClick={() => onSwitch(h.id)}>Selecionar</button>}
            {h.role === 'OWNER' && <form key={h.name} onSubmit={e => renameSpace(e, h.id)}>
              <label>Nome do espaço: {h.name}<input name="name" required maxLength={120} defaultValue={h.name} /></label>
              <button className="button outline" disabled={busy}>Renomear</button>
            </form>}</div></td>
        </tr>)}</tbody></table></div>
      <form className="settings-form" onSubmit={createSpace}><fieldset disabled={busy}>
        <label>Nome do novo espaço<input required maxLength={120} value={name} onChange={e => setName(e.target.value)} /></label>
        <button className="button primary">Criar espaço</button>
      </fieldset></form>
    </section>
    <section className="panel settings-section" aria-labelledby="members-heading">
      <h2 id="members-heading">Membros e acesso{space && ' — ' + space.name}</h2>
      {space && <p>Seu papel: {space.role}</p>}
      {!owner && <p>A administração de membros e convites requer OWNER.</p>}
      {space && <>
        {loading ? <p role="status">Carregando membros e convites…</p> : <>
          <button className="button quiet" disabled={busy} onClick={() => void mutate(() => loadAdministration(), '')}>Atualizar membros e convites</button>
          <div className="table-wrap"><table><thead><tr><th>Membro</th><th>Papel</th><th>Ações</th></tr></thead>
            <tbody>{members.map(member => <tr key={member.id}>
              <td>{member.display_name}{member.user_id === auth.user.id && <small>Você</small>}</td><td>{member.role}</td>
              <td>{owner && <div className="settings-actions"><form key={member.role} onSubmit={e => changeRole(e, member)}>
                <label>Papel de {member.display_name}<select name="role" defaultValue={member.role} disabled={busy}>
                  {roles.map(role => <option key={role}>{role}</option>)}
                </select></label><button className="button outline" disabled={busy}>Salvar papel</button>
              </form><button className="button danger" disabled={busy} onClick={() => removeMember(member)}>Remover</button></div>}</td>
            </tr>)}</tbody></table></div>
          {owner && <p>O espaço deve manter pelo menos um OWNER.</p>}
        </>}
      </>}
    </section>
    {owner && <section className="panel settings-section" aria-labelledby="invitations-heading">
      <h2 id="invitations-heading">Convites pendentes — {space?.name}</h2>
      <form className="settings-form" onSubmit={invite}><fieldset disabled={busy}>
        <label>Email do convite<input type="email" required maxLength={254} value={email} onChange={e => setEmail(e.target.value)} /></label>
        <label>Papel do convite<select value={role} onChange={e => setRole(e.target.value as Role)}>
          {roles.map(role => <option key={role}>{role}</option>)}
        </select></label><button className="button primary">Criar convite</button>
      </fieldset></form>
      {created && <div className="alert success"><p>Token para {created.email}. Exibido somente nesta sessão; copie antes de sair desta página.</p>
        <label>Token do convite criado<input readOnly value={created.token} onFocus={e => e.target.select()} /></label></div>}
      {!loading && (!invitations.length ? <p>Nenhum convite pendente.</p> : <div className="table-wrap"><table>
        <thead><tr><th>Email</th><th>Papel</th><th>Expiração</th><th>Ações</th></tr></thead>
        <tbody>{invitations.map(invitation => <tr key={invitation.id}><td>{invitation.email}</td><td>{invitation.role}</td>
          <td>{expiration(invitation.expires_at)}</td><td><button className="button danger" disabled={busy} onClick={() => revoke(invitation)}>Revogar</button></td>
        </tr>)}</tbody></table></div>)}
    </section>}
    <section className="panel settings-section" aria-labelledby="accept-heading">
      <h2 id="accept-heading">Aceitar convite</h2><p>Entre com uma identidade verificada que corresponda ao email convidado.</p>
      <form className="settings-form" onSubmit={accept}><fieldset disabled={busy}>
        <label>Token do convite<input required maxLength={512} autoComplete="off" value={token} onChange={e => setToken(e.target.value)} /></label>
        <button className="button primary">Aceitar convite</button>
      </fieldset></form>
    </section>
  </div></main>
}
