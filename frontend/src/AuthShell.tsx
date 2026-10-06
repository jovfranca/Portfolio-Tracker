import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import App from './App'
import { api, AuthenticationRequired, selectHousehold } from './api'

type Space = { id: number; name: string; role: 'OWNER' | 'EDITOR' | 'VIEWER' }
type AuthState = { user: { id: number; display_name: string }; households: Space[] }
type AuthConfig = { google_client_id: string | null; google_nonce: string | null; dev_enabled: boolean }
type GoogleApi = { accounts: { id: {
  initialize: (options: { client_id: string; nonce: string; callback: (result: { credential: string }) => void }) => void
  renderButton: (element: HTMLElement, options: { theme: string; size: string; text: string }) => void
  disableAutoSelect: () => void
} } }
declare global { interface Window { google?: GoogleApi } }
const errorText = (e: unknown) => e instanceof Error ? e.message : 'Não foi possível concluir.'

function GoogleButton({ config, onSuccess, link = false }: {
  config: AuthConfig; onSuccess: (state: AuthState) => void; link?: boolean
}) {
  const element = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!config.google_client_id || !config.google_nonce) return
    let cancelled = false
    const initialize = () => {
      if (cancelled || !window.google || !element.current) return
      window.google.accounts.id.initialize({ client_id: config.google_client_id!, nonce: config.google_nonce!,
        callback: result => {
          void api<AuthState>(link ? '/auth/google/link' : '/auth/google', 'POST', { credential: result.credential })
            .then(state => { if (!cancelled) onSuccess(state) })
            .catch(e => { if (!cancelled) setError(errorText(e)) })
        },
      })
      element.current.replaceChildren()
      window.google.accounts.id.renderButton(element.current, { theme: 'outline', size: 'large', text: 'continue_with' })
    }
    let script = document.querySelector<HTMLScriptElement>('script[data-aurion-google]')
    if (window.google) initialize()
    else {
      if (!script) {
        script = document.createElement('script')
        script.src = 'https://accounts.google.com/gsi/client'
        script.async = true
        script.dataset.aurionGoogle = 'true'
        document.head.appendChild(script)
      }
      script.addEventListener('load', initialize)
    }
    const failed = () => setError('Não foi possível carregar o login Google. Recarregue a página.')
    script?.addEventListener('error', failed)
    return () => { cancelled = true; script?.removeEventListener('load', initialize); script?.removeEventListener('error', failed) }
  }, [config, link, onSuccess])
  return <div><div ref={element} aria-label={link ? 'Vincular Google' : 'Continue with Google'} />
    {!config.google_client_id && <><button className="button outline" disabled>Continue with Google</button><p>Login Google indisponível neste ambiente.</p></>}
    {error && <p role="alert">{error}</p>}</div>
}

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
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [linkConfig, setLinkConfig] = useState<AuthConfig | null>(null)
  const signedIn = useCallback((state: AuthState) => {
    const remembered = Number(localStorage.getItem('aurion-household'))
    const id = state.households.find(h => h.id === remembered)?.id ?? state.households[0]?.id ?? null
    selectHousehold(id); setSpaceId(id); setAuth(state); setLinkConfig(null); setError('')
  }, [])
  const restore = useCallback(async () => {
    setLoading(true); setError('')
    try { signedIn(await api<AuthState>('/auth/me')) }
    catch (e) { if (!(e instanceof AuthenticationRequired)) setError(errorText(e)) }
    finally { setLoading(false) }
  }, [signedIn])
  useEffect(() => { void restore() }, [restore])
  useEffect(() => {
    const expired = () => { selectHousehold(null); setAuth(null); setSpaceId(null); setLinkConfig(null) }
    window.addEventListener('aurion-session-expired', expired)
    return () => window.removeEventListener('aurion-session-expired', expired)
  }, [])
  function switchSpace(id: number) {
    selectHousehold(id); localStorage.setItem('aurion-household', String(id)); setSpaceId(id)
  }
  async function logout() {
    try {
      await api('/auth/logout', 'POST'); window.google?.accounts.id.disableAutoSelect()
      selectHousehold(null); setAuth(null); setSpaceId(null); setLinkConfig(null)
    } catch (e) { setError(errorText(e)) }
  }
  async function createSpace(e: FormEvent) {
    e.preventDefault()
    try {
      const space = await api<Space>('/households', 'POST', { name })
      setAuth(current => current && { ...current, households: [...current.households, space] })
      switchSpace(space.id); setName(''); setCreating(false)
    } catch (e) { setError(errorText(e)) }
  }
  if (loading) return <main className="auth-login" role="status">Restaurando sessão…</main>
  if (!auth && error) return <main className="auth-login"><p role="alert">{error}</p><button onClick={() => void restore()}>Tentar novamente</button></main>
  if (!auth) return <Login onSuccess={signedIn} />
  const space = auth.households.find(h => h.id === spaceId)
  return <><div className="auth-bar"><strong>{auth.user.display_name}</strong>
    <label htmlFor="financial-space">Espaço financeiro</label><select id="financial-space" value={spaceId ?? ''} onChange={e => switchSpace(Number(e.target.value))}>
      {auth.households.map(h => <option key={h.id} value={h.id}>{h.name}</option>)}</select>
    <span>{space?.role}</span><button className="button quiet" onClick={() => setCreating(!creating)}>+ Espaço financeiro</button>
    <button className="button quiet" onClick={() => {
      void api<AuthConfig>('/auth/config').then(setLinkConfig).catch(e => setError(errorText(e)))
    }}>Vincular Google</button>
    <button className="button quiet" onClick={() => void logout()}>Sair</button>
    {creating && <form onSubmit={createSpace}><label>Nome do espaço<input required maxLength={120} value={name} onChange={e => setName(e.target.value)} /></label><button className="button primary">Criar espaço</button></form>}
    {linkConfig && <GoogleButton config={linkConfig} onSuccess={signedIn} link />}
    {error && <p role="alert">{error}</p>}
  </div>{space ? <App key={`${auth.user.id}:${space.id}`} readOnly={space.role === 'VIEWER'} /> : <p>Crie um espaço financeiro para começar.</p>}</>
}
