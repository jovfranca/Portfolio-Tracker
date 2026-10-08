import { test, expect } from '@playwright/test'
import type { AuthState, Member, Role } from '../src/api'
const counts = { member_count: 1, portfolio_count: 0, status: 'ACTIVE' as const }

test('Settings administers spaces and invitations through the real API', async ({ page }) => {
  const username = 'settings-' + Date.now()
  const login = await page.request.post('/api/auth/dev', { data: {
    username, token: process.env.DEV_AUTH_TOKEN ?? 'browser-test-only',
  } })
  expect(login.ok()).toBeTruthy()
  await page.goto('/#/settings')
  const header = page.locator('.topbar')
  await expect(header.getByRole('button', { name: 'Vincular Google' })).toHaveCount(0)
  await expect(header.getByRole('button', { name: '+ Espaço financeiro' })).toHaveCount(0)
  await expect(page.getByLabel('Espaço financeiro', { exact: true })).toHaveCount(0)
  await page.goto('/account/security')
  await expect(page.getByRole('heading', { name: 'Conta e identidades' })).toBeVisible()
  await expect(page.getByText('LOCAL — Conectado')).toBeVisible()
  await page.goto('/settings/spaces/new')
  await page.getByLabel('Nome do novo espaço').fill('Settings family')
  await page.getByRole('button', { name: 'Criar espaço', exact: true }).click()
  await expect(page.getByLabel('Espaço financeiro', { exact: true }).locator('option:checked')).toHaveText('Settings family')
  const family = await page.getByLabel('Espaço financeiro', { exact: true }).inputValue()
  const personal = await page.getByLabel('Espaço financeiro', { exact: true }).locator('option').filter({ hasText: username }).getAttribute('value')
  await page.goto('/settings/spaces')
  const spaces = page.getByRole('region', { name: 'Espaços financeiros', exact: true })
  const familyRow = spaces.getByRole('row').filter({ hasText: 'Settings family' })
  await expect(familyRow.getByText('Espaço selecionado')).toBeVisible()
  await familyRow.getByLabel('Nome do espaço: Settings family').fill('Renamed family')
  await familyRow.getByRole('button', { name: 'Renomear' }).click()
  await expect(page.getByLabel('Espaço financeiro', { exact: true }).locator('option:checked')).toHaveText('Renamed family')
  await page.reload()
  await expect(page.getByLabel('Espaço financeiro', { exact: true })).toHaveValue(family)
  await page.goto('/settings/spaces/' + family)
  await page.getByLabel('Email do convite').fill('invited@gmail.com')
  await page.getByLabel('Papel do convite').selectOption('VIEWER')
  await page.getByRole('button', { name: 'Criar convite', exact: true }).click()
  await expect(page.getByLabel('Token do convite criado')).not.toHaveValue('')
  const pending = page.getByRole('region', { name: 'Convites pendentes — Renamed family' })
  await expect(pending.getByRole('row').filter({ hasText: 'invited@gmail.com' })).toContainText('VIEWER')
  await page.reload()
  await expect(page.getByLabel('Token do convite criado')).toHaveCount(0)
  await pending.getByRole('button', { name: 'Revogar' }).click()
  await expect(pending.getByText('Nenhum convite pendente.')).toBeVisible()
  await page.getByLabel('Papel de ' + username).selectOption('VIEWER')
  await page.getByRole('button', { name: 'Salvar papel' }).click()
  await expect(page.getByRole('alert')).toContainText('must retain an owner')
  page.once('dialog', dialog => dialog.accept())
  await page.getByRole('button', { name: 'Remover', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('must retain an owner')
  await page.getByLabel('Espaço financeiro', { exact: true }).selectOption(personal!)
  await page.goto('/settings/spaces/' + personal)
  await expect(page.getByRole('heading', { name: 'Membros e acesso — ' + username })).toBeVisible()
})

// Provider interactions and a second verified user are simulated here. Backend
// identity verification, acceptance, permissions and isolation have API regressions.
test('linked Google state survives reload and acceptance refreshes spaces', async ({ page }) => {
  let state: AuthState = { user: { id: 1, display_name: 'Alice', identities: [
    { provider: 'LOCAL', email: 'alice@gmail.com', email_verified: true },
  ] }, households: [{ id: 10, name: 'Personal', role: 'OWNER', ...counts }] }
  let linked = false
  await page.addInitScript(() => {
    let callback: (result: { credential: string }) => void
    ;(window as any).google = { accounts: { id: {
      initialize: (options: any) => { callback = options.callback },
      renderButton: (element: HTMLElement) => {
        const button = document.createElement('button')
        button.textContent = 'Confirmar Google simulado'
        button.onclick = () => callback({ credential: 'synthetic-credential' })
        element.appendChild(button)
      },
      disableAutoSelect: () => {},
    } } }
  })
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/auth/me') return route.fulfill({ json: state })
    if (path === '/api/households') return route.fulfill({ json: state.households })
    if (path === '/api/invitations/preview') return route.fulfill({ json: {
      id: 1, space: { id: 20, name: 'Shared' }, inviter: { id: 3, display_name: 'Owner' },
      email: 'alice@gmail.com', role: 'EDITOR', status: 'PENDING', expires_at: '2027-01-01T00:00:00Z',
    } })
    if (path === '/api/auth/config') return route.fulfill({ json: {
      google_client_id: 'synthetic-client', google_nonce: 'synthetic-nonce', dev_enabled: true,
    } })
    if (path === '/api/auth/google/link') {
      linked = true
      state = { ...state, user: { ...state.user, identities: [...state.user.identities,
        { provider: 'GOOGLE', email: 'alice@gmail.com', email_verified: true }] } }
      return route.fulfill({ json: state })
    }
    if (path === '/api/invitations/accept') {
      expect(route.request().postDataJSON()).toEqual({ token: 'synthetic-invite' })
      state = { ...state, households: [...state.households, { id: 20, name: 'Shared', role: 'EDITOR', ...counts }] }
      return route.fulfill({ json: state.households[1] })
    }
    return route.fulfill({ json: [] })
  })
  await page.goto('/account/security')
  // A LOCAL email alone must never hide the Google link action.
  await page.getByRole('button', { name: 'Vincular Google', exact: true }).click()
  await page.getByRole('button', { name: 'Confirmar Google simulado' }).click()
  await expect(page.getByText('Google — Conectado — alice@gmail.com — Verificado', { exact: true })).toBeVisible()
  expect(linked).toBeTruthy()
  await expect(page.getByRole('button', { name: 'Vincular Google', exact: true })).toHaveCount(0)
  await page.reload()
  await expect(page.getByText('Google — Conectado — alice@gmail.com — Verificado', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Vincular Google', exact: true })).toHaveCount(0)
  await page.goto('/settings/spaces')
  await page.getByLabel('Token do convite', { exact: true }).fill(' synthetic-invite ')
  await page.getByRole('button', { name: 'Conferir convite', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Convite para espaço financeiro' })).toBeVisible()
  await page.getByRole('button', { name: 'Aceitar convite', exact: true }).click()
  const selector = page.getByLabel('Espaço financeiro', { exact: true })
  await expect(selector).toContainText('Shared')
  await expect(selector).toContainText('Personal')
  await expect(selector).toHaveValue('20')
  await expect(page.getByLabel('Token do convite', { exact: true })).toHaveValue('')
  await page.goto('/settings/spaces/20')
  await expect(page.getByRole('heading', { name: 'Membros e acesso — Shared' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Criar convite', exact: true })).toHaveCount(0)
})

for (const role of ['EDITOR', 'VIEWER'] as Role[]) {
  test(role + ' has account and acceptance controls without space administration', async ({ page }) => {
    const administrationRequests: string[] = []
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('/members') || path.endsWith('/invitations')) administrationRequests.push(path)
      if (path === '/api/auth/me') return route.fulfill({ json: {
        user: { id: 2, display_name: 'Bob', identities: [
          { provider: 'GOOGLE', email: 'bob@example.com', email_verified: false },
        ] }, households: [{ id: 20, name: 'Shared', role }],
      } })
      if (path === '/api/households/20/members') return route.fulfill({ json: [
        { id: 1, user_id: 1, display_name: 'Alice', role: 'OWNER' },
        { id: 2, user_id: 2, display_name: 'Bob', role },
      ] })
      return route.fulfill({ json: [] })
    })
    await page.goto('/account/security')
    await expect(page.getByText('Google — Conectado — bob@example.com — Não verificado', { exact: true })).toBeVisible()
    await page.goto('/settings/spaces/20')
    await expect(page.getByText('Seu papel: ' + role)).toBeVisible()
    await expect(page.getByRole('row').filter({ hasText: 'Alice' }).getByRole('cell', { name: 'OWNER', exact: true })).toBeVisible()
    for (const name of ['Vincular Google', 'Renomear', 'Salvar papel', 'Remover', 'Criar convite', 'Revogar']) {
      await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
    }
    await expect(page.getByRole('button', { name: 'Criar espaço', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Conferir convite', exact: true })).toBeVisible()
    expect(administrationRequests.length).toBeGreaterThan(0)
    expect(administrationRequests.every(path => path === '/api/households/20/members')).toBeTruthy()
  })
}

test('expired session during account refresh returns to login', async ({ page }) => {
  let expired = false
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/auth/me') return expired
      ? route.fulfill({ status: 401, json: { detail: 'Authentication required.' } })
      : route.fulfill({ json: { user: { id: 1, display_name: 'Alice', identities: [] },
        households: [{ id: 10, name: 'Personal', role: 'OWNER' }] } })
    if (path === '/api/households/10' && route.request().method() === 'PUT') {
      expired = true
      return route.fulfill({ json: { id: 10, name: 'Renamed', role: 'OWNER' } })
    }
    if (path === '/api/households') return route.fulfill({ json: [{ id: 10, name: 'Personal', role: 'OWNER', ...counts }] })
    if (path === '/api/auth/config') return route.fulfill({ json: {
      google_client_id: null, google_nonce: null, dev_enabled: true,
    } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/#/settings')
  await page.getByLabel('Nome do espaço: Personal').fill('Renamed')
  await page.getByRole('button', { name: 'Renomear', exact: true }).click()
  await expect(page.getByLabel('Usuário local', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Conta e identidades' })).toHaveCount(0)
})

test('OWNER changes and removes members; self-demotion refreshes permissions', async ({ page }) => {
  let state: AuthState = { user: { id: 1, display_name: 'Alice', identities: [] },
    households: [{ id: 10, name: 'Family', role: 'OWNER', ...counts }] }
  let members: Member[] = [
    { id: 1, user_id: 1, display_name: 'Alice', role: 'OWNER' },
    { id: 2, user_id: 2, display_name: 'Bob', role: 'EDITOR' },
    { id: 3, user_id: 3, display_name: 'Carol', role: 'OWNER' },
  ]
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/auth/me') return route.fulfill({ json: state })
    if (path === '/api/households/10/members') return route.fulfill({ json: members })
    if (path.startsWith('/api/households/10/members/')) {
      const id = Number(path.split('/').at(-1))
      if (route.request().method() === 'DELETE') {
        members = members.filter(member => member.id !== id)
        return route.fulfill({ status: 204 })
      }
      const role = route.request().postDataJSON().role
      members = members.map(member => member.id === id ? { ...member, role } : member)
      if (id === 1) state = { ...state, households: [{ ...state.households[0], role }] }
      return route.fulfill({ json: { id, role } })
    }
    return route.fulfill({ json: [] })
  })
  await page.goto('/settings/spaces/10')
  const bob = page.getByRole('row').filter({ hasText: 'Bob' })
  await bob.getByLabel('Papel de Bob').selectOption('VIEWER')
  await bob.getByRole('button', { name: 'Salvar papel' }).click()
  await expect(bob.getByRole('cell', { name: 'VIEWER', exact: true })).toBeVisible()
  page.once('dialog', dialog => dialog.accept())
  await bob.getByRole('button', { name: 'Remover' }).click()
  await expect(bob).toHaveCount(0)
  await page.getByLabel('Papel de Alice').selectOption('EDITOR')
  await page.getByRole('row').filter({ hasText: 'Alice' }).getByRole('button', { name: 'Salvar papel' }).click()
  await expect(page.getByText('Seu papel: EDITOR')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Criar convite', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Renomear', exact: true })).toHaveCount(0)
})
