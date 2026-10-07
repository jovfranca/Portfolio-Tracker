import { useCallback, useEffect, useState, type FormEvent } from 'react'
import App from './App'
import { api, AuthenticationRequired, selectHousehold, type AuthState, type AuthConfig } from './api'
import GoogleButton from './GoogleButton'
import { Link, navigate, useRoute } from './navigation'

const errorText = (e: unknown) => e instanceof Error ? e.message : 'Não foi possível concluir.'

function Login({ onSuccess, path }: { onSuccess: (state: AuthState) => void; path: string }) {
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
  return <main className="auth-login"><section className="panel"><img className="login-brand light-brand" src="/brand/quintrion_horizontal_portuguese_light.svg" alt="Quintrion" /><img className="login-brand dark-brand" src="/brand/quintrion_horizontal_master_dark.svg" alt="Quintrion" /><h1>{path === '/signup' ? 'Criar conta' : 'Entre na sua conta'}</h1><p>Entre para acessar seus espaços financeiros.</p>
    {error && <p role="alert">{error}</p>}
    {path === '/signup' && <p>Continue com Google para criar sua conta no primeiro acesso.</p>}
    {['/forgot-password', '/reset-password'].includes(path) && <p>Recupere o acesso pelo provedor conectado. Recuperação por senha local ainda não está disponível.</p>}
    {config ? <GoogleButton config={config} onSuccess={onSuccess} /> : <p>Carregando opções de login…</p>}
    {config?.dev_enabled && <form onSubmit={devLogin}><h2>Login de desenvolvimento</h2>
      <label>Usuário local<input required value={username} onChange={e => setUsername(e.target.value)} autoComplete="username" /></label>
      <label>Chave de desenvolvimento<input required type="password" value={token} onChange={e => setToken(e.target.value)} autoComplete="current-password" /></label>
      <button className="button primary" disabled={busy}>Entrar</button></form>}
    <p className="auth-footer">{path === '/signup' ? <Link href="/login">Já tenho conta</Link> : <Link href="/signup">Criar conta</Link>}</p>
  </section></main>
}

export default function AuthShell() {
  const [auth, setAuth] = useState<AuthState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [spaceId, setSpaceId] = useState<number | null>(null)
  const route = useRoute()
  const path = route.split('?')[0]
  const signedIn = useCallback((state: AuthState) => {
    const remembered = Number(localStorage.getItem('quintrion-household') ?? localStorage.getItem('aurion-household'))
    const id = state.households.find(h => h.id === remembered)?.id ?? state.households[0]?.id ?? null
    selectHousehold(id); setSpaceId(id); setAuth(state); setError('')
    if (id !== null) localStorage.setItem('quintrion-household', String(id))
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
    window.addEventListener('quintrion-session-expired', expired)
    return () => window.removeEventListener('quintrion-session-expired', expired)
  }, [])
  function switchSpace(id: number) {
    if (/^\/settings\/spaces\/\d+/.test(path)) navigate(path.replace(/^(\/settings\/spaces\/)\d+/, '$1' + id))
    selectHousehold(id); localStorage.setItem('quintrion-household', String(id)); setSpaceId(id)
  }
  async function logout() {
    try {
      await api('/auth/logout', 'POST'); window.google?.accounts.id.disableAutoSelect()
      selectHousehold(null); setAuth(null); setSpaceId(null); navigate('/login')
    } catch (e) { setError(errorText(e)) }
  }
  async function refreshAuth(preferredSpace?: number) {
    const state = await api<AuthState>('/auth/me')
    signedIn(state)
    if (preferredSpace !== undefined && state.households.some(h => h.id === preferredSpace)) switchSpace(preferredSpace)
  }
  const targetId = Number(path.match(/^\/settings\/spaces\/(\d+)/)?.[1])
  useEffect(() => {
    if (targetId && auth?.households.some(h => h.id === targetId) && targetId !== spaceId) switchSpace(targetId)
  }, [targetId, spaceId, auth])
  useEffect(() => { if (auth && ['/login', '/signup'].includes(path)) navigate('/overview', true) }, [auth, path])
  if (loading) return <main className="auth-login" role="status">Restaurando sessão…</main>
  if (!auth && error) return <main className="auth-login"><p role="alert">{error}</p><button onClick={() => void restore()}>Tentar novamente</button></main>
  if (!auth) return <Login onSuccess={signedIn} path={path} />
  if (targetId && !auth.households.some(h => h.id === targetId)) return <main className="auth-login"><p role="alert">Espaço financeiro não encontrado ou sem acesso.</p><Link href="/settings/spaces">Ver meus espaços financeiros</Link></main>
  const space = auth.households.find(h => h.id === spaceId)
  if (targetId && auth.households.some(h => h.id === targetId) && targetId !== spaceId) return <p role="status">Abrindo espaço financeiro…</p>
  return <App key={`${auth.user.id}:${spaceId}:${space?.role}`} auth={auth} space={space} onSwitch={switchSpace} onLogout={() => void logout()} onRefresh={refreshAuth} onLinked={signedIn} authError={error} />
}
