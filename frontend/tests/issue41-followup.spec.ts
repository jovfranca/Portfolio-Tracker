import { test, expect, type Page } from '@playwright/test'

const personal = { id: 10, name: 'Pessoal', role: 'OWNER', member_count: 1, portfolio_count: 1, status: 'ACTIVE' }
const shared = { id: 20, name: 'Família de teste', role: 'VIEWER', member_count: 3, portfolio_count: 2, status: 'ACTIVE' }
const auth = { user: { id: 41, display_name: 'Pessoa de teste', identities: [{ provider: 'GOOGLE', email: 'guest@example.com', email_verified: true }] }, households: [personal] }
const portfolio = { id: 1, household_id: 10, name: 'Carteira sintética', display_currency: 'BRL' }
const overview = { positions: [], assets: [], fixed_income: { valuation_status: 'none' }, methodology: 'Dados sintéticos',
  summary: { display_currency: 'BRL', total_value: 0, acquisition_cost: '0', total_gain: '0', positions: 0,
    history_status: 'complete', gross_income: '0', history_built_through: '2024-03-30',
    missing_prices: [], missing_fx: [], missing_cost_fx: [], currencies: [] } }
const preview = { id: 1, space: { id: 20, name: 'Família de teste' }, inviter: { id: 9, display_name: 'Remetente de teste' },
  email: 'guest@example.com', role: 'VIEWER', status: 'PENDING', created_at: '2024-03-24T12:00:00Z', expires_at: '2024-04-01T12:00:00Z', resolved_at: null }

async function shell(page: Page, state = auth) {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    return route.fulfill({ json: path === '/api/auth/me' ? state : path === '/api/households' ? state.households
      : path === '/api/portfolios' ? [portfolio] : path.endsWith('/overview') ? overview : [] })
  })
}

test('invitation preview has both decisions; rejection survives reload and adds no space', async ({ page }) => {
  await shell(page)
  let status = 'PENDING', acceptCalls = 0
  await page.route('**/api/invitations/*', route => {
    expect(route.request().postDataJSON()).toEqual({ token: 'synthetic-token' })
    if (route.request().url().endsWith('/reject')) status = 'REJECTED'
    if (route.request().url().endsWith('/accept')) acceptCalls++
    return route.fulfill({ json: { ...preview, status } })
  })
  await page.goto('/invite/synthetic-token')
  for (const text of ['Família de teste', 'Remetente de teste', 'guest@example.com', 'VIEWER', 'Expiração']) await expect(page.getByText(text, { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Aceitar convite', exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/issue41-invitation-preview.png', fullPage: true })
  await page.getByRole('button', { name: 'Rejeitar convite', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Convite rejeitado')
  await page.reload()
  await expect(page.getByRole('status')).toContainText('Convite rejeitado')
  await expect(page.getByRole('button', { name: 'Aceitar convite', exact: true })).toHaveCount(0)
  await expect(page.getByLabel('Espaço financeiro', { exact: true })).toHaveCount(0)
  expect(status).toBe('REJECTED'); expect(acceptCalls).toBe(0)
})

test('acceptance refreshes membership and navigates to the joined space', async ({ page }) => {
  await shell(page)
  let accepted = false
  await page.route('**/api/auth/me', route => route.fulfill({ json: { ...auth, households: accepted ? [personal, shared] : [personal] } }))
  await page.route('**/api/invitations/preview', route => route.fulfill({ json: { ...preview, status: accepted ? 'ACCEPTED' : 'PENDING' } }))
  await page.route('**/api/invitations/accept', route => { accepted = true; return route.fulfill({ json: shared }) })
  await page.goto('/invite/synthetic-token')
  await page.getByRole('button', { name: 'Aceitar convite', exact: true }).click()
  await expect(page).toHaveURL(/\/settings\/spaces\/20$/)
  await expect(page.getByLabel('Espaço financeiro', { exact: true })).toHaveValue('20')
  await expect(page.getByText('Seu papel: VIEWER')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Criar convite', exact: true })).toHaveCount(0)
  await page.goto('/invite/synthetic-token')
  await expect(page.getByRole('status')).toContainText('Convite aceito')
  await expect(page.getByRole('button', { name: 'Rejeitar convite', exact: true })).toHaveCount(0)
})

for (const [status, label] of [['EXPIRED', 'expirado'], ['REVOKED', 'revogado']]) {
  test('invitation terminal state ' + status + ' hides decisions', async ({ page }) => {
    await shell(page)
    await page.route('**/api/invitations/preview', route => route.fulfill({ json: { ...preview, status } }))
    await page.goto('/invite/synthetic-token')
    await expect(page.getByRole('status')).toContainText('Convite ' + label)
    await expect(page.getByRole('button', { name: /Aceitar convite|Rejeitar convite/ })).toHaveCount(0)
  })
}

test('invalid invitation and unmatched identity expose an error without decisions', async ({ page }) => {
  await shell(page)
  for (const status of [404, 403]) {
    await page.route('**/api/invitations/preview', route => route.fulfill({ status, json: { detail: status === 404 ? 'Invitation not found.' : 'Sign in with a verified identity matching the invited email.' } }))
    await page.goto('/invite/synthetic-token')
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByRole('button', { name: /Aceitar convite|Rejeitar convite/ })).toHaveCount(0)
    await page.unroute('**/api/invitations/preview')
  }
})

test('malformed invitation URL displays an invalid invitation instead of crashing the shell', async ({ page }) => {
  await shell(page)
  const crashes: string[] = []
  page.on('pageerror', error => crashes.push(error.message))
  await page.route('**/api/invitations/preview', route => route.fulfill({ status: 404, json: { detail: 'Invitation not found.' } }))
  await page.goto('/invite/%')
  await expect(page.getByRole('heading', { name: 'Convite para espaço financeiro' })).toBeVisible()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByRole('button', { name: /Aceitar convite|Rejeitar convite/ })).toHaveCount(0)
  expect(crashes).toEqual([])
})

test('space list renders server counts, role and active status without member requests', async ({ page }) => {
  await shell(page, { ...auth, households: [personal, shared] })
  const rosterRequests: string[] = []
  page.on('request', request => { if (request.url().includes('/members')) rosterRequests.push(request.url()) })
  await page.goto('/settings/spaces')
  const row = page.getByRole('row').filter({ hasText: 'Família de teste' })
  await expect(row.getByRole('cell', { name: 'VIEWER', exact: true })).toBeVisible()
  await expect(row.getByRole('cell', { name: '3', exact: true })).toBeVisible()
  await expect(row.getByRole('cell', { name: '2', exact: true })).toBeVisible()
  await expect(row.getByRole('cell', { name: 'Ativo', exact: true })).toBeVisible()
  await expect(page.getByLabel('Espaço financeiro', { exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/issue41-space-list.png', fullPage: true })
  expect(rosterRequests).toEqual([])
})

test('overview selects monetary result periods and displays incomplete values as unknown', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2024-03-31T12:00:00'))
  await shell(page)
  await page.route('**/api/portfolios/1/analytics?*', route => {
    const start = new URL(route.request().url()).searchParams.get('start_date')
    return route.fulfill({ json: { monetary_result: start === '2024-02-29' ? '64' : start === '2024-03-02' ? null : '90',
      reporting_currency: 'BRL', start_date: start ?? '2024-01-01', end_date: '2024-03-30',
      status: start === '2024-03-02' ? 'incomplete' : 'complete' } })
  })
  await page.goto('/overview')
  const result = page.getByRole('region', { name: 'Ganho patrimonial', exact: true })
  await expect(result.locator('strong')).toHaveText(/R\$\s*64,00/)
  await page.getByLabel('Período do ganho patrimonial').selectOption('Max')
  await expect(result.locator('strong')).toHaveText(/R\$\s*90,00/)
  await page.getByLabel('Período do ganho patrimonial').selectOption('1M')
  await expect(result.locator('strong')).toHaveText(/R\$\s*64,00/)
  await expect(result).toContainText('29/02/2024 a 30/03/2024')
  await page.screenshot({ path: 'test-results/issue41-overview-period.png', fullPage: true })
  await page.getByText('Datas e valores do gráfico', { exact: true }).click()
  await page.getByLabel('Data inicial', { exact: true }).fill('2024-03-02')
  await page.route('**/api/portfolios/1/analytics?*', route => route.fulfill({ json: {
    monetary_result: null, reporting_currency: 'BRL', start_date: '2024-03-02', end_date: '2024-03-30', status: 'incomplete',
  } }))
  await page.getByLabel('Período do ganho patrimonial').selectOption('1D')
  await expect(result.locator('strong')).toHaveText('—')
  await expect(result).toContainText('Dados incompletos ou atualização pendente')
})

test('FX coverage exposes pairs, dated history, missing requirements and truthful sync status', async ({ page }) => {
  await shell(page)
  const pair = (currency: string) => ({ currency, base_currency: 'BRL', status: 'incomplete',
    required_start: '2024-01-01', required_end: '2024-01-03', required_count: 3, covered_count: 2,
    missing_dates: ['2024-01-03'], sources: ['Synthetic provider'], available_start: '2024-01-01', available_end: '2024-01-01',
    last_observation_retrieved_at: '2026-01-01T12:00:00Z',
    requirements: [{ date: '2024-01-03', reference_date: null, fallback_used: false, reasons: ['valuation'] }],
    history: [{ reference_date: '2024-01-01', rate_type: 'FX', side: 'MARKET', rate: currency === 'USD' ? '5' : '6', source: 'Synthetic provider', retrieved_at: '2026-01-01T12:00:00Z' }] })
  await page.route('**/api/portfolios/1/fx-coverage', route => route.fulfill({ json: {
    portfolio_id: 1, reporting_currency: 'BRL', as_of: '2024-01-03', fallback_days: 1,
    status: 'incomplete', requirements_status: 'complete', last_successful_sync_at: null,
    sync_tracking: 'not_recorded', pairs: [pair('USD'), pair('EUR')],
  } }))
  await page.goto('/data/fx')
  await expect(page.getByText('Última sincronização bem-sucedida: Não registrado.', { exact: false })).toBeVisible()
  await expect(page.getByRole('cell', { name: 'USD/BRL', exact: true })).toBeVisible()
  await page.getByLabel('Par cambial').selectOption('EUR')
  await expect(page.getByRole('heading', { name: 'Histórico de câmbio e PTAX · EUR/BRL' })).toBeVisible()
  await expect(page.getByRole('cell', { name: '6,000000', exact: true })).toBeVisible()
  await page.getByText('Datas necessárias e observações usadas (3)', { exact: true }).click()
  await expect(page.getByRole('cell', { name: 'FX ausente', exact: true })).toBeVisible()
  await page.evaluate(() => { (document.activeElement as HTMLElement)?.blur(); window.scrollTo(0, 0) })
  await page.screenshot({ path: 'test-results/issue41-fx-coverage.png', fullPage: true })
  await page.goto('/data/status')
  await expect(page.getByRole('link', { name: 'USD/BRL: 1 datas sem FX utilizável' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'EUR/BRL: 1 datas sem FX utilizável' })).toBeVisible()
  await page.screenshot({ path: 'test-results/issue41-data-status.png', fullPage: true })
})
