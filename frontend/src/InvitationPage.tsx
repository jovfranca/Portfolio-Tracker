import { useState } from 'react'
import { api, type Space } from './api'
import { Link, navigate } from './navigation'
import { ErrorState, message, PageHeader } from './ui'

export default function InvitationPage({ token, onAccepted }: { token: string; onAccepted: (spaceId?: number) => Promise<void> }) {
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  return <><PageHeader title="Aceitar convite" description="Junte-se a um espaço financeiro compartilhado." /><section className="panel settings-section"><p>Confira com a pessoa que enviou o convite qual espaço e papel serão concedidos. Entre com a identidade verificada do email convidado.</p><p>A prévia do espaço e do remetente ainda não está disponível. Ao aceitar, você ingressa no espaço e mantém as carteiras existentes.</p>{error && <ErrorState error={error} />}<button className="button primary" disabled={busy} onClick={async () => {
    setBusy(true); setError('')
    try { const space = await api<Space>('/invitations/accept', 'POST', { token }); await onAccepted(space.id); navigate('/settings/spaces/' + space.id) } catch (e) { setError(message(e)) } finally { setBusy(false) }
  }}>{busy ? 'Aceitando…' : 'Aceitar convite'}</button><Link className="button quiet" href="/overview">Voltar sem aceitar</Link></section></>
}
