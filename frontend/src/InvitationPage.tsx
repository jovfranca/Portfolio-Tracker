import { useEffect, useState } from 'react'
import { api, type InvitationPreview, type Space } from './api'
import { Link, navigate } from './navigation'
import { ErrorState, LoadingState, message, PageHeader } from './ui'

const statusLabels: Record<InvitationPreview['status'], string> = {
  PENDING: 'Pendente', ACCEPTED: 'Aceito', REJECTED: 'Rejeitado', REVOKED: 'Revogado', EXPIRED: 'Expirado',
}

export default function InvitationPage({ token, onAccepted }: { token: string; onAccepted: (spaceId?: number) => Promise<void> }) {
  const [preview, setPreview] = useState<InvitationPreview | null>(null)
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [loading, setLoading] = useState(true)
  const [version, setVersion] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setPreview(null); setError('')
    api<InvitationPreview>('/invitations/preview', 'POST', { token }, controller.signal).then(data => {
      if (!controller.signal.aborted) setPreview(data)
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [token, version])
  async function decide(action: 'accept' | 'reject') {
    setBusy(true); setError('')
    try {
      if (action === 'reject') setPreview(await api<InvitationPreview>('/invitations/reject', 'POST', { token }))
      else {
        const space = await api<Space>('/invitations/accept', 'POST', { token })
        await onAccepted(space.id); navigate('/settings/spaces/' + space.id)
      }
    } catch (e) {
      setError(message(e))
      // A concurrent decision/revocation may have changed the available actions.
      try { setPreview(await api<InvitationPreview>('/invitations/preview', 'POST', { token })) } catch { /* Keep the decision error visible. */ }
    }
    finally { setBusy(false) }
  }
  return <><PageHeader title="Convite para espaço financeiro" description="Confira os detalhes antes de decidir." />
    <section className="panel settings-section">
      {loading && <LoadingState />}
      {error && <ErrorState error={error} retry={() => setVersion(v => v + 1)} />}
      {preview && <>
        <h2>{preview.space.name}</h2>
        <dl><dt>Convidado por</dt><dd>{preview.inviter?.display_name ?? 'Remetente não registrado'}</dd>
          <dt>Email convidado</dt><dd>{preview.email}</dd><dt>Papel concedido</dt><dd>{preview.role}</dd>
          <dt>Status do convite</dt><dd>{statusLabels[preview.status]}</dd>
          <dt>Expiração</dt><dd>{new Date(preview.expires_at).toLocaleString('pt-BR')}</dd></dl>
        {preview.status === 'PENDING' ? <><p>O convite concede acesso ao espaço financeiro e às carteiras existentes.</p>
          <button className="button primary" disabled={busy} onClick={() => void decide('accept')}>Aceitar convite</button>
          <button className="button danger" disabled={busy} onClick={() => void decide('reject')}>Rejeitar convite</button></>
          : <p role="status">Convite {statusLabels[preview.status].toLowerCase()}. Nenhuma nova decisão está disponível.</p>}
      </>}
      <Link className="button quiet" href="/overview">Voltar à carteira</Link>
    </section></>
}
