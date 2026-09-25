import { test, expect } from '@playwright/test'

test('reporting values are primary, native values conditional, and closed positions optional', async ({ page }) => {
  const position = {
    asset_id: 1, asset: 'OPEN', native_currency: 'USD', transaction_currency: 'USD',
    display_currency: 'BRL', quantity: 2, average_cost: 10, acquisition_cost: 20,
    current_price: 12, total_value: 24, display_average_cost: 50,
    display_acquisition_cost: 100, display_price: 60, display_value: 120,
    allocation_class: 'Stocks', broker: 'A',
    broker_breakdown: [{ broker: 'A', quantity: 2, acquisition_cost: 20, average_cost: 10 }],
    current_total_gain: 4, current_accumulated_profitability: 20,
    income_by_currency: {}, price_date: '2024-01-02', history_behind_transactions: false,
  }
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    const body = path.endsWith('/portfolios') ? [
      { id: 1, name: 'First', display_currency: 'BRL' },
      { id: 2, name: 'Second', display_currency: 'BRL' },
    ] : path.endsWith('/transactions') ? [] : {
      positions: [position, { ...position, asset_id: 2, asset: 'CLOSED', quantity: 0 },
        { ...position, asset_id: 3, asset: 'CRYPTO', native_currency: null },
        { ...position, asset_id: 4, asset: 'LOCAL', transaction_currency: 'BRL', native_currency: 'BRL' }],
      assets: [], methodology: 'Synthetic fixture',
      summary: { display_currency: 'BRL', total_value: 360, assets: 4, positions: 4,
        transactions: 5, missing_fx: [], missing_cost_fx: [], missing_prices: [], income_by_currency: {} },
    }
    return route.fulfill({ json: body })
  })
  await page.goto('/')
  const open = page.getByRole('row').filter({ has: page.getByText('OPEN', { exact: true }) })
  const value = open.getByRole('cell').nth(5)
  await expect(value).toHaveText('BRL 120,00USD 24,00')
  await expect(page.getByText('CLOSED', { exact: true })).toHaveCount(0)
  await page.getByLabel('Mostrar posições encerradas').check()
  await expect(page.getByText('CLOSED', { exact: true })).toBeVisible()
  for (const asset of ['CRYPTO', 'LOCAL']) {
    const row = page.getByRole('row').filter({ has: page.getByText(asset, { exact: true }) })
    await expect(row.getByRole('cell').nth(5)).toHaveText('BRL 120,00')
  }
  await page.getByLabel('Moeda de exibição').fill('EUR')
  await page.getByLabel('Carteira', { exact: true }).selectOption('2')
  await expect(page.getByLabel('Moeda de exibição')).toHaveValue('BRL')
})
