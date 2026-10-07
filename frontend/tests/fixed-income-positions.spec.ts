import { test, expect } from './auth-fixture'

test('fixed-income pending lot shows the saved value and update instruction', async ({ page }) => {
  const valuation = { status: 'complete', pending: true, gross_accrued_value: '1000',
    outstanding_principal: '1000', accrued_gain: '0', display_currency: 'BRL', display_value: '1000' }
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.startsWith('/api/auth/')) return route.fallback()
    if (path.endsWith('/history')) return route.fulfill({ json: [] })
    if (path.endsWith('/analytics')) return route.fulfill({ json: { return_pct: null, net_contributions: null, status: 'incomplete' } })
    const body = path.endsWith('/portfolios') ? [{ id: 1, name: 'Pending lot', display_currency: 'BRL' }]
      : path.endsWith('/transactions') ? []
      : path.endsWith('/fixed-income/lots') ? [{ id: 1, instrument_symbol: 'PENDING-CDB',
        instrument_name: 'Pending CDB', issuer: 'Bank', broker: 'Broker', currency: 'BRL',
        start_date: '2024-01-02', maturity_date: null, opening_amount: '1500',
        yield_structure: 'FIXED_RATE', fixed_rate: '0', valuation, movements: [] }]
      : { positions: [], assets: [], fixed_income: { lot_count: 1, valuation_status: 'pending' },
        summary: { display_currency: 'BRL', total_value: 1000, assets: 1, positions: 1,
          transactions: 0, history_status: 'pending', missing_fx: [], missing_prices: [],
          missing_cost_fx: [], income_by_currency: {} } }
    return route.fulfill({ json: body })
  })
  await page.goto('/positions')
  const row = page.getByRole('row').filter({ has: page.getByText('PENDING-CDB', { exact: true }) })
  await expect(row.getByRole('cell').nth(5)).toContainText('1.000,00')
  await expect(row.getByRole('cell').nth(5)).toContainText('Atualização pendente · use Atualizar carteira')
})

test('fixed-income lots appear once while aggregates remain in portfolio totals', async ({ page }) => {
  const valuation = { status: 'complete', gross_accrued_value: '1100', outstanding_principal: '1000',
    accrued_gain: '100', display_currency: 'BRL', display_value: '1100' }
  const lot = { id: 1, instrument_symbol: 'CDB-TEST', instrument_name: 'Test CDB', issuer: 'Bank',
    broker: 'Broker', currency: 'BRL', start_date: '2024-01-02', maturity_date: null,
    opening_amount: '1000', yield_structure: 'BENCHMARK_MULTIPLE', benchmark_multiplier: '1',
    benchmark_code: 'CDI', valuation, movements: [] }
  const position = { asset_id: 1, asset: 'STOCK-TEST', position_type: 'MARKET', quantity: 1,
    allocation_class: 'Stocks', display_currency: 'BRL', display_value: 100, status: 'complete' }
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.startsWith('/api/auth/')) return route.fallback()
    if (path.endsWith('/history')) return route.fulfill({ json: [] })
    if (path.endsWith('/analytics')) return route.fulfill({ json: { return_pct: null, net_contributions: null, status: 'incomplete' } })
    const body = path.endsWith('/portfolios') ? [{ id: 1, name: 'Test', display_currency: 'BRL' }]
      : path.endsWith('/transactions') ? []
      : path.endsWith('/fixed-income/lots') ? [lot, { ...lot, id: 2, instrument_symbol: 'CLOSED-CDB',
        valuation: { ...valuation, gross_accrued_value: '0', display_value: '0' } }]
      : { positions: [position, { ...position, asset_id: 2, asset: 'CDB-TEST',
        position_type: 'FIXED_INCOME', quantity: null, display_value: 1100 }], assets: [],
        fixed_income: { lot_count: 2 }, methodology: 'Fixture',
        summary: { display_currency: 'BRL', total_value: 1200, assets: 2, positions: 2,
          transactions: 0, history_status: 'complete', dirty_from: null,
          missing_fx: [], missing_prices: [], missing_cost_fx: [], income_by_currency: {} } }
    return route.fulfill({ json: body })
  })
  await page.goto('/positions')
  await expect(page.getByText('CDB-TEST', { exact: true })).toHaveCount(1)
  await expect(page.getByText('STOCK-TEST', { exact: true })).toHaveCount(1)
  await page.goto('/overview')
  await expect(page.locator('.metric.featured')).toContainText('1.200,00')
  await page.goto('/positions')
  await expect(page.getByText('CLOSED-CDB', { exact: true })).toHaveCount(0)
  await page.getByLabel('Mostrar posições encerradas').check()
  await expect(page.getByText('CLOSED-CDB', { exact: true })).toHaveCount(1)
  await page.getByPlaceholder('Buscar ativo ou classe…').fill('CDB-TEST')
  await expect(page.getByText('STOCK-TEST', { exact: true })).toHaveCount(0)
  await expect(page.getByText('CDB-TEST', { exact: true })).toHaveCount(1)
  await expect(page.getByText('CLOSED-CDB', { exact: true })).toHaveCount(0)
  await page.locator('summary[aria-label="Ações de CDB-TEST"]').click()
  await page.getByRole('button', { name: 'Resgatar', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Lote', exact: true })).toHaveValue('1')
})
