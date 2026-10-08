import { test, expect } from '@playwright/test'

const auth = { user: { id: 41, display_name: 'Pessoa de teste', identities: [] }, households: [{ id: 10, name: 'Pessoal', role: 'OWNER' }] }
const position = { asset_id: 5, instrument_id: 9, asset: 'TEST', position_type: 'MARKET', quantity: '2', native_currency: 'USD', quote_currency: 'USD', display_currency: 'BRL', transaction_currency: 'USD', allocation_class: 'Ações', broker: 'Exemplo', display_value: '120', display_average_cost: '50', display_acquisition_cost: '100', native_average_cost: '10', native_acquisition_cost: '20', current_price: '12', total_value: '24', display_price: '60', current_total_gain: '20', current_accumulated_profitability: '20', gross_income: '0', native_gross_income: '0', status: 'complete', broker_breakdown: [{ broker: 'Exemplo', quantity: '2', acquisition_cost: '20', average_cost: '10' }] }
const overview = { positions: [position], assets: [{ id: 5, ticker: 'TEST', transaction_currency: 'USD' }], methodology: 'Dados de teste', summary: { display_currency: 'BRL', total_value: 120, positions: 1, history_status: 'complete', currencies: ['USD'], gross_income: '0', history_built_through: '2024-01-03', missing_prices: [], missing_fx: [], missing_cost_fx: [], income_by_currency: {} } }
const transaction = { id: 8, instrument_id: 9, portfolio_id: 1, asset: 'TEST', type: 'Buy', broker: 'Exemplo', allocation_class: 'Ações', trade_date: '2024-01-02', settlement_date: '2024-01-03', transaction_currency: 'USD', fx_rate: '5', quantity: '2', price: '10', brokerage_fee: '0', other_fees: '0', notes: '', transaction_currency_locked: true }
const instrument = { id: 9, symbol: 'TEST', name: 'Instrumento de teste', asset_type: 'STOCK', currency: 'USD', exchange: 'TEST', status: 'ACTIVE', origin: 'CATALOG', aliases: ['ALIAS'], mappings: [] }
const history = [{ date: '2024-01-02', reporting_currency: 'BRL', market_value: '100', remaining_acquisition_cost: '100', total_gain: '0', realized_gain: '0', unrealized_gain: '0', cumulative_return_pct: '0', status: 'complete' }, { date: '2024-01-03', reporting_currency: 'BRL', market_value: '120', remaining_acquisition_cost: '100', total_gain: '20', realized_gain: '0', unrealized_gain: '20', cumulative_return_pct: '20', status: 'complete' }]

async function mock(page: import('@playwright/test').Page, state = auth) {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    const body = path === '/api/auth/me' ? state : path === '/api/portfolios' ? [{ id: 1, household_id: 10, name: 'Carteira de teste', display_currency: 'BRL' }]
      : path.endsWith('/overview') ? overview : path.endsWith('/transactions') ? [transaction]
      : path.endsWith('/fixed-income/lots') || path.endsWith('/fixed-income/products') ? []
      : path.endsWith('/analytics') ? { return_pct: '20', net_contributions: '100', status: 'complete' }
      : path.endsWith('/history') || path.endsWith('/performance') ? history
      : path === '/api/instruments' ? [instrument] : path === '/api/instruments/9' ? instrument : []
    return route.fulfill({ json: body })
  })
}

test('shell has canonical brand, route links and portfolio-wide performance', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  await mock(page)
  await page.goto('/overview')
  await expect(page).toHaveTitle('Quintrion')
  await expect(page.getByLabel('Espaço financeiro', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('img', { name: 'Quintrion', exact: true })).toHaveAttribute('src', '/brand/quintrion_horizontal_master_dark.svg')
  for (const name of ['Visão geral', 'Posições', 'Transações', 'Desempenho', 'Dados de mercado', 'Instrumentos']) await expect(page.getByRole('navigation', { name: 'Navegação principal' }).getByRole('link', { name, exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Desempenho', exact: true }).click()
  await expect(page.getByText('Retorno do período', { exact: true })).toBeVisible()
  await expect(page.getByText('20,00%').first()).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Desempenho', exact: true })).toBeVisible()
  await page.goto('/positions/5?tab=transactions')
  await expect(page.getByRole('link', { name: 'TEST', exact: true })).toHaveAttribute('href', '/transactions/8')
  await page.goto('/transactions/8')
  await expect(page.getByRole('heading', { name: 'Transação · TEST' })).toBeVisible()
  await page.goto('/instruments/9')
  await expect(page.getByText('ALIAS', { exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('global actions open their forms and import in the current portfolio', async ({ page }) => {
  await mock(page); await page.goto('/overview')
  for (const name of ['Nova transação', 'Nova aplicação em renda fixa', 'Aporte em renda fixa', 'Resgate de renda fixa']) {
    await page.getByRole('button', { name: '+ Adicionar', exact: true }).click()
    await page.getByRole('button', { name, exact: true }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByLabel('Fechar formulário').click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
  }
  await page.getByRole('button', { name: '+ Adicionar', exact: true }).click()
  await page.getByRole('button', { name: 'Importar transações', exact: true }).click()
  await expect(page).toHaveURL(/\/transactions\/import$/)
  await expect(page.getByText('Carteira de teste', { exact: true }).last()).toBeVisible()
})

test('viewer has no mutations and forbidden space links never load administration', async ({ page }) => {
  await mock(page, { ...auth, households: [{ id: 10, name: 'Pessoal', role: 'VIEWER' }] })
  await page.goto('/positions/5?tab=transactions')
  await expect(page.getByRole('heading', { name: 'TEST', exact: true })).toBeVisible()
  for (const name of ['+ Adicionar', 'Atualizar carteira', 'Editar', 'Excluir']) await expect(page.getByRole('button', { name, exact: true })).toHaveCount(0)
  await page.goto('/transactions/import')
  await expect(page.locator('input[type=file]')).toHaveCount(0)
  await page.goto('/settings/spaces/999')
  await expect(page.getByRole('alert')).toHaveText('Espaço financeiro não encontrado ou sem acesso.')
  await expect(page.getByRole('button', { name: 'Renomear', exact: true })).toHaveCount(0)
})

test('overview and mobile navigation fit the viewport; theme is persisted', async ({ page }) => {
  await mock(page); await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto('/overview')
  await expect(page.locator('.metric.featured')).toContainText('120,00')
  await page.screenshot({ path: 'test-results/quintrion-overview-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('navigation', { name: 'Navegação móvel' })).toBeVisible()
  await expect(page.getByRole('button', { name: '+ Adicionar', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.screenshot({ path: 'test-results/quintrion-overview-mobile.png', fullPage: true })
  await page.getByRole('button', { name: 'Mais', exact: true }).click()
  await page.getByRole('button', { name: 'Conta', exact: true }).click()
  await page.getByRole('link', { name: 'Preferências', exact: true }).click()
  await page.getByLabel('Tema', { exact: true }).selectOption('dark')
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.reload(); await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.goto('/overview')
  await page.screenshot({ path: 'test-results/quintrion-overview-dark.png', fullPage: true })
})

test('switching contexts from settings follows the selected space and portfolio', async ({ page }) => {
  await mock(page, { ...auth, households: [...auth.households, { id: 20, name: 'Família', role: 'EDITOR' }] })
  await page.route('**/api/portfolios', route => route.fulfill({ json: route.request().headers()['x-household-id'] === '20'
    ? [{ id: 3, household_id: 20, name: 'Compartilhada', display_currency: 'USD' }]
    : [{ id: 1, household_id: 10, name: 'Primeira', display_currency: 'BRL' }, { id: 2, household_id: 10, name: 'Segunda', display_currency: 'EUR' }] }))
  await page.goto('/portfolios/1/settings')
  await expect(page.getByLabel('Moeda de exibição', { exact: true })).toHaveValue('BRL')
  await page.getByLabel('Carteira', { exact: true }).selectOption('2')
  await expect(page).toHaveURL(/\/portfolios\/2\/settings$/)
  await expect(page.getByLabel('Moeda de exibição', { exact: true })).toHaveValue('EUR')
  await page.goto('/settings/spaces/10/members')
  await page.getByLabel('Espaço financeiro', { exact: true }).selectOption('20')
  await expect(page).toHaveURL(/\/settings\/spaces\/20\/members$/)
  await expect(page.getByLabel('Carteira', { exact: true })).toContainText('Compartilhada')
  await expect(page.getByLabel('Carteira', { exact: true })).not.toContainText('Primeira')
  await expect(page.getByRole('heading', { name: 'Membros e acesso — Família' })).toBeVisible()
})

test('position filters, market tabs and instrument categories are reachable', async ({ page }) => {
  await mock(page); await page.goto('/positions')
  await page.getByLabel('Buscar posições', { exact: true }).fill('absent')
  await expect(page.getByRole('link', { name: 'TEST', exact: true })).toHaveCount(0)
  await page.getByLabel('Buscar posições', { exact: true }).fill('test')
  await page.getByRole('link', { name: 'TEST', exact: true }).click()
  await expect(page).toHaveURL(/\/positions\/5$/)
  await page.goto('/data/status')
  for (const name of ['Cotações', 'Câmbio', 'Eventos corporativos', 'Status']) {
    await page.getByRole('navigation', { name: 'Seções da página' }).getByRole('link', { name, exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Dados de mercado', exact: true })).toBeVisible()
  }
  await page.goto('/instruments')
  await page.getByRole('button', { name: 'Meus instrumentos', exact: true }).click()
  await expect(page.getByText('Nenhum instrumento corresponde à busca.')).toBeVisible()
  await page.getByRole('button', { name: 'Mercado', exact: true }).click()
  await page.getByRole('link', { name: 'TEST', exact: true }).click()
  await expect(page.getByText('ALIAS', { exact: true })).toBeVisible()
})

test('position and instrument details associate alias transactions by canonical identity', async ({ page }) => {
  await mock(page)
  await page.route('**/api/portfolios/1/overview', route => route.fulfill({ json: {
    ...overview, positions: [{ ...position, instrument_id: 9 }],
  } }))
  await page.route('**/api/portfolios/1/transactions', route => route.fulfill({ json: [
    { ...transaction, asset: 'ALIAS' },
  ] }))
  await page.goto('/positions/5?tab=transactions')
  await expect(page.getByRole('link', { name: 'ALIAS', exact: true })).toHaveAttribute('href', '/transactions/8')
  await expect(page.getByRole('button', { name: '+ Transação neste ativo', exact: true })).toBeVisible()
  await page.goto('/instruments/9')
  await expect(page.getByRole('link', { name: 'TEST →', exact: true })).toHaveAttribute('href', '/positions/5')
})

test('overview uses current reporting totals and dates historical return', async ({ page }) => {
  await mock(page)
  await page.route('**/api/portfolios/1/overview', route => route.fulfill({ json: {
    ...overview, summary: { ...overview.summary, acquisition_cost: '110', total_gain: '10' },
  } }))
  await page.goto('/overview')
  await page.getByText('Mais sobre a carteira', { exact: true }).click()
  await expect(page.locator('.overview-secondary div').filter({ hasText: 'Custo de aquisição' }).locator('dd')).toHaveText(/R\$\s*110,00/)
  await expect(page.locator('.overview-secondary div').filter({ hasText: 'Resultado acumulado' }).locator('dd')).toHaveText(/R\$\s*10,00/)
  await expect(page.locator('.overview-secondary div').filter({ hasText: 'Retorno acumulado' })).toContainText('03/01/2024')
})

test('month and year performance periods clamp to the last valid calendar day', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2024-03-31T12:00:00'))
  await mock(page)
  await page.goto('/performance')
  const monthRequest = page.waitForRequest(request => request.url().includes('/analytics?start_date='))
  await page.getByRole('button', { name: '1M', exact: true }).click()
  expect(new URL((await monthRequest).url()).searchParams.get('start_date')).toBe('2024-02-29')
  await page.clock.setFixedTime(new Date('2024-02-29T12:00:00'))
  const yearRequest = page.waitForRequest(request => request.url().includes('start_date=2023'))
  await page.getByRole('button', { name: '1A', exact: true }).click()
  expect(new URL((await yearRequest).url()).searchParams.get('start_date')).toBe('2023-02-28')
})

test('performance includes fixed-income holdings in the asset breakdown', async ({ page }) => {
  await mock(page)
  await page.route('**/api/portfolios/1/fixed-income/lots', route => route.fulfill({ json: [{
    id: 4, instrument_symbol: 'CDB', instrument_name: 'Aplicação de teste', issuer: 'Emissor',
    broker: 'Exemplo', currency: 'BRL', yield_structure: 'FIXED_RATE', fixed_rate: '0.1',
    start_date: '2024-01-02', maturity_date: '2025-01-02', opening_amount: '100',
    valuation_status: 'complete', valuation: { display_currency: 'BRL', display_value: '110',
      outstanding_principal: '100', gross_accrued_value: '110', accrued_gain: '10' }, movements: [],
  }] }))
  await page.goto('/performance')
  await expect(page.getByRole('link', { name: 'CDB', exact: true })).toHaveAttribute('href', '/fixed-income/4')
})

test('creating a portfolio cannot replace its overview with the previous portfolio response', async ({ page }) => {
  await mock(page)
  const first = { id: 1, household_id: 10, name: 'Original', display_currency: 'BRL' }
  const second = { id: 2, household_id: 10, name: 'Nova', display_currency: 'BRL' }
  let created = false
  let releaseOldResponse: (() => void) | undefined
  const oldResponse = new Promise<void>(resolve => { releaseOldResponse = resolve })
  await page.route('**/api/portfolios', async route => {
    if (route.request().method() === 'POST') { created = true; return route.fulfill({ json: second }) }
    return route.fulfill({ json: created ? [first, second] : [first] })
  })
  await page.route('**/api/portfolios/1/overview', async route => {
    if (created) await Promise.race([oldResponse, new Promise(resolve => setTimeout(resolve, 500))])
    return route.fulfill({ json: overview })
  })
  await page.route('**/api/portfolios/2/**', async route => {
    if (route.request().url().endsWith('/overview')) {
      // Release the previous portfolio only after the new overview has arrived.
      await route.fulfill({ json: { ...overview, positions: [], summary: { ...overview.summary, total_value: 0, positions: 0 } } })
      releaseOldResponse!()
    } else await route.fulfill({ json: [] })
  })
  await page.goto('/portfolios/new')
  await expect(page.getByLabel('Carteira', { exact: true })).toHaveValue('1')
  await page.getByLabel('Nome da carteira', { exact: true }).fill('Nova')
  await page.getByRole('button', { name: 'Continuar', exact: true }).click()
  await page.getByRole('button', { name: 'Criar carteira', exact: true }).click()
  await expect(page).toHaveURL(/\/overview$/)
  await expect(page.getByLabel('Carteira', { exact: true })).toHaveValue('2')
  await expect(page.locator('.metric.featured strong')).toHaveText(/R\$\s*0,00/)
})
