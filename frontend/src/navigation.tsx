import { useSyncExternalStore, type AnchorHTMLAttributes } from 'react'

// History routing with compatibility for existing bookmarked hash URLs.
const aliases: Record<string, string> = { '/': '/overview', '/quotes': '/data/quotes', '/catalog': '/instruments' }
export function currentRoute() {
  const path = window.location.hash.startsWith('#/') ? window.location.hash.slice(1) : window.location.pathname + window.location.search
  const [pathname, query] = path.split('?')
  return (aliases[pathname] ?? pathname.replace(/\/$/, '')) + (query ? '?' + query : '')
}
function subscribe(callback: () => void) {
  window.addEventListener('popstate', callback)
  window.addEventListener('hashchange', callback)
  return () => { window.removeEventListener('popstate', callback); window.removeEventListener('hashchange', callback) }
}
export function useRoute() { return useSyncExternalStore(subscribe, currentRoute) }
export function navigate(path: string, replace = false) {
  window.history[replace ? 'replaceState' : 'pushState']({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
  window.scrollTo({ top: 0 })
}
export function Link({ href = '/overview', onClick, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <a href={href} {...props} onClick={e => {
    onClick?.(e)
    if (!e.defaultPrevented && e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey && !props.target) {
      e.preventDefault(); navigate(href)
    }
  }} />
}
