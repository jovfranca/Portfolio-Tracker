import { useEffect, useRef, useState } from 'react'
import { api, type AuthConfig, type AuthState } from './api'

type GoogleApi = { accounts: { id: {
  initialize: (options: { client_id: string; nonce: string; callback: (result: { credential: string }) => void }) => void
  renderButton: (element: HTMLElement, options: { theme: string; size: string; text: string }) => void
  disableAutoSelect: () => void
} } }
declare global { interface Window { google?: GoogleApi } }
const errorText = (e: unknown) => e instanceof Error ? e.message : 'Não foi possível concluir.'

export default function GoogleButton({ config, onSuccess, link = false }: {
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
    let script = document.querySelector<HTMLScriptElement>('script[data-quintrion-google]')
    if (window.google) initialize()
    else {
      if (!script) {
        script = document.createElement('script')
        script.src = 'https://accounts.google.com/gsi/client'
        script.async = true
        script.dataset.quintrionGoogle = 'true'
        document.head.appendChild(script)
      }
      script.addEventListener('load', initialize)
    }
    const failed = () => setError('Não foi possível carregar o login Google. Recarregue a página.')
    script?.addEventListener('error', failed)
    return () => { cancelled = true; script?.removeEventListener('load', initialize); script?.removeEventListener('error', failed) }
  }, [config, link, onSuccess])
  return <div><div ref={element} aria-label={link ? 'Vincular Google' : 'Continuar com Google'} />
    {!config.google_client_id && <><button className="button outline" disabled>{link ? 'Vincular Google' : 'Continuar com Google'}</button><p>Login Google indisponível neste ambiente.</p></>}
    {error && <p role="alert">{error}</p>}</div>
}

