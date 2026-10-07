import { useEffect, useState } from 'react'
import { api } from './api'
import { message } from './ui'

export function useResource<T>(path: string | null, version = 0) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(!!path)
  const [retryVersion, setRetryVersion] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError(''); setLoading(!!path)
    if (path) void api<T>(path, 'GET', undefined, controller.signal).then(value => {
      if (!controller.signal.aborted) setData(value)
    }).catch(e => { if (!controller.signal.aborted) setError(message(e)) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [path, version, retryVersion])
  return { data, error, loading, retry: () => setRetryVersion(value => value + 1) }
}
