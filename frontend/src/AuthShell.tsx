import { useCallback, useEffect, useState, type FormEvent } from 'react'
import App from './App'
import { api, AuthenticationRequired, selectHousehold, type AuthState, type AuthConfig } from './api'
import GoogleButton from './GoogleButton'
import SettingsPage from './SettingsPage'

const errorText = (e: unknown) => e instanceof Error ? e.message : 'Não foi possível concluir.'

function Login({ onSuccess }: { onSuccess: (state: AuthState) => void }) {
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [username, setUsername] = useState('local')
  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    void api<AuthConfig>('/auth/config', 'GET', undefined, controller.signal).then(setConfig).catch(e => {
      if (!controller.signal.aborted) setError(errorText(e))
    })
    return () => controller.abort()
  }, [])
  async function devLogin(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try { onSuccess(await api<AuthState>('/auth/dev', 'POST', { username, token })) }
    catch (e) { setError(errorText(e)) }
    finally { setBusy(false) }
  }
  return <main className="auth-login"><section className="panel"><h1>Aurion</h1><p>Entre para acessar seus espaços financeiros.</p>
    {error && <p role="alert">{error}</p>}
    {config ? <GoogleButton config={config} onSuccess={onSuccess} /> : <p>Carregando opções de login…</p>}
    {config?.dev_enabled && <form onSubmit={devLogin}><h2>Login de desenvolvimento</h2>
      <label>Usuário local<input required value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" /></label>
      <label>Chave de desenvolvimento<input required type="password" value={token} onChange={e => setToken(e.target.value)} autoComplete="current-password" /></label>
      <button className="button primary" disabled={busy}>Entrar</button></form>}
  </section></main>
}

export default function AuthShell() {
  const [auth, setAuth] = useState<AuthState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [spaceId, setSpaceId] = useState<number | null>(null)
  const [path, setPath] = useState(() => window.location.hash.slice(1) || '/')
  useEffect(() => {
    const changed = () => setPath(window.location.hash.slice(1) || '/')
    window.addEventListener('hashchange', changed)
    return () => window.removeEventListener('hashchange', changed)
  }, [])
  const signedIn = useCallback((state: AuthState) => {
    const remembered = Number(localStorage.getItem('aurion-household'))
    const id = state.households.find(h => h.id === remembered)?.id ?? state.households[0]?.id ?? null
    selectHousehold(id); setSpaceId(id); setAuth(state); setError('')
    if (id !== null) localStorage.setItem('aurion-household', String(id))
  }, [])
  const restore = useCallback(async () => {
    setLoading(true); setError('')
    try { signedIn(await api<AuthState>('/auth/me')) }
    catch (e) { if (!(e instanceof AuthenticationRequired)) setError(errorText(e)) }
    finally { setLoading(false) }
  }, [signedIn])
  useEffect(() => { void restore() }, [restore])
  useEffect(() => {
    const expired = () => { selectHousehold(null); setAuth(null); setSpaceId(null) }
    window.addEventListener('aurion-session-expired', expired)
    return () => window.removeEventListener('aurion-session-expired', expired)
  }, [])
  function switchSpace(id: number) {
    selectHousehold(id); localStorage.setItem('aurion-household', String(id)); setSpaceId(id)
  }
  async function logout() {
    try {
      await api('/auth/logout', 'POST'); window.google?.accounts.id.disableAutoSelect()
      selectHousehold(null); setAuth(null); setSpaceId(null)
    } catch (e) { setError(errorText(e)) }
  }
  async function refreshAuth(preferredSpace?: number) {
    const state = await api<AuthState>('/auth/me')
    signedIn(state)
    if (preferredSpace !== undefined && state.households.some(h => h.id === preferredSpace)) switchSpace(preferredSpace)
  }
  if (loading) return <main className="auth-login" role="status">Restaurando sessão…</main>
  if (!auth && error) return <main className="auth-login"><p role="alert">{error}</p><button onClick={() => void restore()}>Tentar novamente</button></main>
  if (!auth) return <Login onSuccess={signedIn} />
  const space = auth.households.find(h => h.id === spaceId)
  const settings = path === '/settings'
  return <><div className={'auth-bar' + (settings ? ' settings-bar' : '')}><strong>{auth.user.display_name}</strong>
    <label htmlFor="financial-space">Espaço financeiro</label><select id="financial-space" value={spaceId ?? ''} onChange={e => switchSpace(Number(e.target.value))}>
      {auth.households.map(h => <option key={h.id} value={h.id}>{h.name}</option>)}</select>
    <a className="button quiet" href="#/settings" aria-current={settings ? 'page' : undefined}>Settings</a>
    <button className="button quiet" onClick={() => void logout()}>Sair</button>
    {error && <p role="alert">{error}</p>}
  </div>{settings ? <SettingsPage key={`${auth.user.id}:${spaceId}:${space?.role}`} auth={auth} space={space}
    onRefresh={refreshAuth} onSwitch={switchSpace} onLinked={signedIn} />
    : space ? <App key={`${auth.user.id}:${space.id}:${space.role}`} readOnly={space.role === 'VIEWER'} />
    : <p>Crie um espaço financeiro em <a href="#/settings">Settings</a> para começar.</p>}</>
}
