import { test, expect } from './auth-fixture'

test('unbuilt positions remain visible with unknown values until explicit update', async ({ page }) => {
  let consolidated = false
  let updates = 0
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.startsWith('/api/auth/')) return route.fallback()
    if (path.endsWith('/consolidate')) {
      consolidated = true
      updates++
      return route.fulfill({ json: { complete: true } })
    }
    if (path.endsWith('/portfolios')) return route.fulfill({ json: [
      { id: 1, name: 'Unbuilt', display_currency: 'BRL' },
    ] })
    if (path.endsWith('/transactions') || path.endsWith('/fixed-income/lots')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {
      positions: [{ asset_id: 1, asset: 'NEW', allocation_class: '', display_currency: 'BRL',
        quantity: consolidated ? 2 : null, display_value: consolidated ? 20 : null,
        status: consolidated ? 'complete' : 'pending', current_accumulated_profitability: null }],
      assets: [], methodology: 'Synthetic fixture',
      summary: { display_currency: 'BRL', total_value: consolidated ? 20 : null,
        transactions: 1, assets: 1, positions: 1, missing_fx: [], missing_prices: [],
        missing_cost_fx: [], income_by_currency: {},
        history_status: consolidated ? 'complete' : 'pending', history_built_through: null },
    } })
  })
  await page.goto('/')
  const row = page.getByRole('row').filter({ has: page.getByText('NEW', { exact: true }) })
  await expect(row).toBeVisible()
  await expect(row.getByRole('cell').nth(1)).toHaveText('—')
  await expect(row.getByRole('cell').nth(4)).toHaveText('BRL —')
  await expect(row).toContainText('atualização pendente: use Atualizar posições')
  expect(updates).toBe(0)
  await page.getByRole('button', { name: 'Atualizar posições' }).click()
  await expect(row.getByRole('cell').nth(1)).toHaveText('2,000000')
  await expect(row.getByRole('cell').nth(4)).toHaveText('BRL 20,00')
  expect(updates).toBe(1)
})

test('reporting values are primary, native values conditional, and closed positions optional', async ({ page }) => {
  let currencyUpdates = 0
  let savedCurrency = ''
  let consolidations = 0
  const position = {
    asset_id: 1, asset: 'OPEN', native_currency: 'USD', quote_currency: 'USD', transaction_currency: 'USD',
    display_currency: 'BRL', quantity: 2, average_cost: 10, acquisition_cost: 20,
    current_price: 12, total_value: 24, display_average_cost: 50,
    display_acquisition_cost: 100, display_price: 60, display_value: 120,
    native_average_cost: 10, native_acquisition_cost: 20,
    allocation_class: 'Stocks', broker: 'A',
    broker_breakdown: [{ broker: 'A', quantity: 2, acquisition_cost: 20, average_cost: 10 }],
    current_total_gain: 4, current_accumulated_profitability: 20,
    gross_income: 30, native_gross_income: 6, status: 'complete',
    income_by_currency: {}, price_date: '2024-01-02', history_behind_transactions: false,
  }
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.startsWith('/api/auth/')) return route.fallback()
    if (route.request().method() === 'PUT' && path.endsWith('/portfolios/1')) {
      currencyUpdates++
      savedCurrency = route.request().postDataJSON().display_currency
      return route.fulfill({ json: { id: 1, name: 'First', display_currency: savedCurrency } })
    }
    if (route.request().method() === 'POST' && path.endsWith('/consolidate')) {
      consolidations++
      return route.fulfill({ json: { complete: true, history_status: 'complete', incomplete_assets: [] } })
    }
    const body = path.endsWith('/portfolios') ? [
      { id: 1, name: 'First', display_currency: savedCurrency || 'BRL' },
      { id: 2, name: 'Second', display_currency: 'BRL' },
    ] : path.endsWith('/transactions') || path.endsWith('/performance') ? [] : {
      positions: [position, { ...position, asset_id: 2, asset: 'CLOSED', quantity: 0 },
        { ...position, asset_id: 3, asset: 'CRYPTO', native_currency: null },
        { ...position, asset_id: 4, asset: 'LOCAL', transaction_currency: 'BRL', native_currency: 'BRL' }]
        .map(p => ({ ...p, display_currency: savedCurrency || 'BRL' })),
      assets: [], methodology: 'Synthetic fixture',
      summary: { display_currency: savedCurrency || 'BRL', total_value: 360, assets: 4, positions: 4,
        history_status: 'complete', dirty_from: null, history_built_through: '2024-01-02',
        transactions: 5, missing_fx: [], missing_cost_fx: [], missing_prices: [], income_by_currency: {} },
    }
    return route.fulfill({ json: body })
  })
  await page.goto('/')
  const open = page.getByRole('row').filter({ has: page.getByText('OPEN', { exact: true }) })
  const value = open.getByRole('cell').nth(4)
  await expect(value).toHaveText('BRL 120,00USD 24,00')
  await expect(open.getByRole('cell').nth(2)).toContainText('USD 10,0000')
  await expect(open.getByRole('cell').nth(5)).toHaveText('BRL 30,00USD 6,00')
  await expect(page.getByText('CLOSED', { exact: true })).toHaveCount(0)
  await page.getByLabel('Mostrar posições encerradas').check()
  await expect(page.getByText('CLOSED', { exact: true })).toBeVisible()
  for (const asset of ['CRYPTO', 'LOCAL']) {
    const row = page.getByRole('row').filter({ has: page.getByText(asset, { exact: true }) })
    await expect(row.getByRole('cell').nth(4)).toHaveText('BRL 120,00')
    await expect(row.getByRole('cell').nth(5)).toHaveText('BRL 30,00')
  }
  await expect(page.getByRole('button', { name: 'Aplicar moeda' })).toBeDisabled()
  await page.getByLabel('Moeda de exibição').selectOption('BRL')
  expect(currencyUpdates).toBe(0)
  await page.getByRole('button', { name: 'Atualizar posições' }).click()
  await expect.poll(() => consolidations).toBe(1)
  await page.getByLabel('Moeda de exibição').selectOption('EUR')
  await expect(page.getByRole('button', { name: 'Aplicar moeda' })).toBeEnabled()
  await page.getByRole('button', { name: 'Aplicar moeda' }).click()
  await expect.poll(() => currencyUpdates).toBe(1)
  expect(savedCurrency).toBe('EUR')
  await expect.poll(() => consolidations).toBe(1)
  await expect(value).toHaveText('EUR 120,00USD 24,00')
  await expect(page.getByText('Moeda de exibição atualizada.')).toBeVisible()
  await page.getByLabel('Moeda de exibição').selectOption('OTHER')
  await page.getByLabel('Código da moeda').fill('GBP')
  await expect(page.getByRole('button', { name: 'Aplicar moeda' })).toBeEnabled()
  await page.getByLabel('Carteira', { exact: true }).selectOption('2')
  await expect(page.getByLabel('Moeda de exibição')).toHaveValue('BRL')
  await page.getByRole('button', { name: 'Desempenho', exact: true }).click()
  await expect(page.getByLabel('Posição').getByRole('option', { name: 'OPEN', exact: true })).toBeAttached()
})

test('partial history is shown as data gaps with visible performance dates', async ({ page }) => {
  let consolidated = false
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.startsWith('/api/auth/')) return route.fallback()
    if (path.endsWith('/portfolios')) return route.fulfill({ json: [
      { id: 1, name: 'Test', display_currency: 'USD', dirty_from: consolidated ? null : '2024-05-06', history_built_through: consolidated ? '2024-05-07' : null },
    ] })
    if (path.endsWith('/consolidate')) {
      consolidated = true
      return route.fulfill({ json: { complete: false, message: 'Consolidação parcial: GLD. Confira as cotações, o câmbio e o histórico dos ativos indicados.' } })
    }
    if (path.endsWith('/performance')) return route.fulfill({ json: [
      { date: '2024-05-06', quantity: 1, remaining_acquisition_cost: 100, market_value: 100, realized_gain: 0, unrealized_gain: 0, gross_income: 0, total_gain: 0, cumulative_return_pct: 0, status: 'complete' },
      { date: '2024-05-07', quantity: 1, remaining_acquisition_cost: 100, market_value: null, realized_gain: 0, unrealized_gain: null, gross_income: 0, total_gain: null, cumulative_return_pct: null, status: 'missing_fx' },
      { date: '2024-05-08', quote_date: '2024-05-06', quantity: 1, remaining_acquisition_cost: 100, market_value: 105, realized_gain: 0, unrealized_gain: 5, gross_income: 0, total_gain: 5, cumulative_return_pct: null, status: 'incomplete_history' },
    ] })
    if (path.endsWith('/transactions')) return route.fulfill({ json: [] })
    return route.fulfill({ json: {
      positions: [{ asset_id: 1, asset: 'GLD', quantity: 1, allocation_class: 'ETF',
        display_currency: 'USD', native_currency: 'USD', quote_currency: 'USD',
        display_average_cost: 100, display_acquisition_cost: 100, display_price: 105,
        display_value: 105, current_total_gain: 5, current_accumulated_profitability: null,
        gross_income: 0, native_gross_income: 0, status: 'complete', price_date: '2024-05-08',
        history_behind_transactions: false }],
      assets: [], methodology: 'Synthetic fixture', summary: { display_currency: 'USD',
        history_status: consolidated ? 'incomplete' : 'pending', dirty_from: consolidated ? null : '2024-05-06',
        history_built_through: consolidated ? '2024-05-07' : null,
        total_value: 105, assets: 1, positions: 1, transactions: 1,
        missing_fx: [], missing_cost_fx: [], missing_prices: [], gross_income: 0, income_by_currency: { USD: 0 } },
    } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Atualizar posições' }).click()
  await expect(page.getByText(/Consolidação parcial: GLD/)).toBeVisible()
  await expect(page.getByText(/Histórico: dados incompletos/)).toBeVisible()
  await expect(page.getByText(/Retorno histórico indisponível/)).toBeVisible()
  await page.getByRole('button', { name: 'Desempenho', exact: true }).click()
  await expect(page.getByText(/Histórico com dados incompletos/)).toBeVisible()
  const missingDay = page.getByRole('row').filter({ has: page.getByText('07/05/2024') })
  await expect(missingDay).toContainText('Incompleto')
  await expect(missingDay.getByRole('cell').nth(3)).toHaveText('—')
  await expect(page.getByText('Ganho total · USD', { exact: true })).toBeVisible()
  await expect(page.getByText('Última disponível', { exact: true })).toBeVisible()
  const chartPath = await page.getByRole('img', { name: 'Evolução histórica do ganho total' }).locator('path').getAttribute('d')
  expect(chartPath?.match(/M/g)).toHaveLength(2)
  await page.screenshot({ path: 'test-results/performance-review-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/performance-review-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})
