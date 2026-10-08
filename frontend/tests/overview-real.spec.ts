import { test, expect } from './auth-fixture'

test('Overview renders persisted portfolio valuations and movements through the real backend', async ({ page, request }) => {
  const portfolio = await (await request.post('/api/portfolios', { data: { name: 'Overview visual review ' + Date.now() } })).json()
  const products = await (await request.get('/api/fixed-income/products')).json() as { symbol: string; instrument_id: number }[]
  const now = new Date()
  const day = (offset: number) => new Date(now.getFullYear(), now.getMonth(), now.getDate() - offset).toLocaleDateString('sv-SE')
  const lots: number[] = []
  for (const [i, product] of products.entries()) {
    const response = await request.post(`/api/portfolios/${portfolio.id}/fixed-income/lots`, { data: {
      instrument_id: product.instrument_id, product_type: product.symbol, issuer: 'Emissor de teste', broker: 'Corretora de teste',
      start_date: day(180 - i * 15), opening_amount: [142000, 71000, 43000][i], currency: 'BRL',
      yield_structure: 'FIXED_RATE', fixed_rate: [.12, .10, .09][i], day_count_basis: 'ACT_365', business_day_calendar: 'NONE', compounding: 'COMPOUND',
    } })
    expect(response.ok(), await response.text()).toBeTruthy()
    lots.push((await response.json()).id)
  }
  for (const [i, lot] of lots.slice(0, 2).entries()) {
    const response = await request.post(`/api/portfolios/${portfolio.id}/fixed-income/lots/${lot}/movements`, {
      data: { movement_type: 'ADDITIONAL_INVESTMENT', effective_date: day(3 - i), amount: 5000 + i * 2500, currency: 'BRL' },
    })
    expect(response.ok(), await response.text()).toBeTruthy()
  }
  const consolidated = await request.post(`/api/portfolios/${portfolio.id}/consolidate`)
  expect(consolidated.ok(), await consolidated.text()).toBeTruthy()
  const analytics = await (await request.get(`/api/portfolios/${portfolio.id}/analytics?include_series=true`)).json()
  expect(analytics.status).toBe('complete')
  expect(analytics.monetary_result).toBeGreaterThan(0)
  await page.goto('/overview')
  await page.getByLabel('Carteira', { exact: true }).selectOption(String(portfolio.id))
  await expect(page.locator('.wealth-card>strong')).toContainText('R$')
  await expect(page.locator('.return-card>strong')).not.toHaveText('—')
  await expect(page.locator('.gain-card>strong')).toContainText('R$')
  await expect(page.locator('.month-result')).toContainText('R$')
  for (const metric of await page.locator('.return-submetrics b').all()) {
    await expect(metric).toContainText('%')
  }
  await expect(page.locator('.overview-activity li')).toHaveCount(5)
  await expect(page.locator('.overview-chart-panel canvas')).toBeVisible()
  await expect(page.locator('.allocation-donut canvas')).toBeVisible()
  await page.setViewportSize({ width: 1672, height: 1050 })
  await page.screenshot({ path: 'test-results/overview-real-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/overview-real-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
})
