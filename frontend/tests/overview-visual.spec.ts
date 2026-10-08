import { test, expect, type Page } from '@playwright/test'

async function fixture(page: Page, currency = 'BRL', incomplete = false) {
  await page.clock.setFixedTime(new Date('2026-10-07T20:24:00-03:00'))
  const history = Array.from({ length: 180 }, (_, i) => {
    const day = new Date(Date.UTC(2026, 3, 10 + i)).toISOString().slice(0, 10)
    return { date: day, reporting_currency: currency, status: incomplete && i > 90 ? 'pending' : 'complete',
      market_value: 250000 + i * 170 + Math.sin(i / 9) * 2200, cumulative_return_pct: i * .07 }
  })
  const transactions = Array.from({ length: 7 }, (_, i) => ({ id: i + 1, instrument_id: i + 1,
    asset: ['AAPL', 'PETR4', 'IVVB11', 'BOVA11', 'MSFT', 'WEGE3', 'BTC'][i], type: i % 3 === 0 ? 'Sell' : 'Buy',
    trade_date: '2026-10-' + String(6 - Math.floor(i / 2)).padStart(2, '0'), settlement_date: '2026-10-06',
    transaction_currency: i === 0 ? 'USD' : 'BRL', quantity: '10', price: '94.02', broker: 'Corretora de teste' }))
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url()), path = url.pathname
    const start = url.searchParams.get('start_date') || '2026-04-10', end = url.searchParams.get('end_date') || '2026-10-06'
    const selected = history.filter(r => r.date >= start && r.date <= end)
    const series = selected.map((r, i) => ({ date: r.date, return_pct: incomplete && i > 90 ? null : i * .07 }))
    const body = path === '/api/auth/me' ? { user: { id: 1, display_name: 'Pessoa de teste', identities: [] }, households: [{ id: 10, name: 'Pessoal', role: 'OWNER' }] }
      : path === '/api/portfolios' ? [{ id: 1, household_id: 10, name: 'Minha carteira principal', display_currency: currency }]
      : path.endsWith('/overview') ? { positions: [
        { asset: 'Ações', asset_id: 1, allocation_class: 'Renda variável', native_currency: 'BRL', display_value: 142260 },
        { asset: 'CDB', asset_id: 2, allocation_class: 'Renda fixa', position_type: 'FIXED_INCOME', native_currency: 'BRL', display_value: 71130 },
        { asset: 'ETF', asset_id: 3, allocation_class: 'Fundos', native_currency: 'USD', display_value: 42678 },
        { asset: 'BTC', asset_id: 4, allocation_class: 'Alternativos', native_currency: 'USD', display_value: incomplete ? null : 28452.17 },
      ], assets: [], summary: { display_currency: currency, total_value: incomplete ? null : 284520.17, acquisition_cost: 250000,
        total_gain: 34520.17, gross_income: 362, positions: 4, history_status: incomplete ? 'pending' : 'complete',
        history_built_through: '2026-10-06', missing_prices: [], missing_fx: [], missing_cost_fx: [] } }
      : path.endsWith('/history') ? history : path.endsWith('/transactions') ? transactions
      : path.endsWith('/analytics') ? { status: incomplete ? 'incomplete' : 'complete', return_pct: incomplete ? null : 12.8,
        monetary_result: incomplete ? null : start === '2026-10-01' ? -450.2 : 31640.22,
        annualized_return_pct: incomplete ? null : 15.42, reporting_currency: currency, start_date: start, end_date: end,
        coverage_start: selected[0]?.date ?? start, coverage_end: selected.at(-1)?.date ?? end,
        return_series: series, benchmarks: url.searchParams.get('benchmark_codes') === 'CDI' ? [{ code: 'CDI', status: incomplete ? 'incomplete' : 'complete',
          return_pct: incomplete ? null : 9.6, annualized_return_pct: incomplete ? null : 11.5, series: series.map((r, i) => ({ ...r, return_pct: incomplete && i > 90 ? null : i * .05 })) }] : [] }
      : path.endsWith('/consolidate') ? { complete: true } : []
    return route.fulfill({ json: body })
  })
}

test('overview follows the composition, real-field currency format, five activities and card navigation', async ({ page }) => {
  await fixture(page)
  await page.setViewportSize({ width: 1672, height: 1050 })
  await page.goto('/overview')
  await expect(page.getByRole('heading', { name: 'Visão geral', exact: true })).toHaveCount(1)
  await expect(page.locator('.wealth-card>strong')).toHaveText(/R\$\s*284\.520,17/)
  await expect(page.locator('.month-result')).toContainText('↓')
  await expect(page.locator('.month-result')).toHaveClass(/negative/)
  await expect(page.locator('.return-card>strong')).toHaveText('+15,42%')
  await expect(page.getByLabel('Período do ganho patrimonial')).toHaveValue('1M')
  await expect(page.locator('.overview-activity li')).toHaveCount(5)
  await expect(page.locator('.overview-activity li').first()).toContainText('Compra de PETR4')
  await expect(page.locator('.overview-activity')).toContainText('US$ 940.20')
  await page.getByRole('button', { name: 'Por moeda', exact: true }).click()
  await expect(page.locator('.allocation-table')).toContainText('USD')
  await page.getByRole('button', { name: 'Por classe', exact: true }).click()
  const chart = await page.locator('.overview-chart-panel').boundingBox(), kpis = await page.locator('.overview-kpis').boundingBox()
  expect(chart!.x).toBeLessThan(kpis!.x)
  expect(Math.abs(chart!.y - kpis!.y)).toBeLessThan(3)
  await expect(page.locator('.overview-chart-panel canvas')).toBeVisible()
  await page.screenshot({ path: 'test-results/overview-visual-desktop.png', fullPage: true })
  for (const [name, url] of [['Patrimônio total — Ver posições', '/positions'], ['Rentabilidade — Ver desempenho', '/performance'], ['Atividade recente — Ver transações', '/transactions']]) {
    await page.getByRole('link', { name, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(url + '$'))
    await page.goto('/overview')
  }
})

test('chart hover, benchmark, toggles, navigator, modifier zoom and keyboard date controls work', async ({ page }) => {
  await fixture(page)
  await page.setViewportSize({ width: 1672, height: 1050 })
  await page.goto('/overview')
  await page.getByLabel('Comparar com', { exact: true }).selectOption('CDI')
  await expect(page.locator('.chart-legend')).toContainText('CDI')
  await expect(page.locator('.benchmark-context')).toContainText('11,50% a.a. do CDI')
  const chart = page.locator('.overview-chart-panel .financial-chart')
  await expect(chart.locator('canvas')).toBeVisible()
  const box = (await chart.boundingBox())!
  await page.mouse.move(box.x + box.width * .55, box.y + 110)
  await expect(chart).toContainText('Minha carteira')
  await expect(chart).toContainText('CDI')
  await page.screenshot({ path: 'test-results/overview-chart-hover.png', fullPage: true })
  const zoom = page.waitForRequest(r => r.url().includes('/analytics?') && new URL(r.url()).searchParams.get('start_date')?.startsWith('2026-') === true)
  await page.keyboard.down('Control'); await page.mouse.wheel(0, -350); await page.keyboard.up('Control')
  await zoom
  await expect(page.locator('.period-buttons [aria-pressed=true]')).toHaveCount(0)
  await page.keyboard.down('Control'); await page.keyboard.down('Shift'); await page.mouse.wheel(0, -200); await page.keyboard.up('Shift'); await page.keyboard.up('Control')
  await page.getByRole('button', { name: 'Restaurar período' }).click()
  await expect(page.getByRole('button', { name: '1A', exact: true })).toHaveAttribute('aria-pressed', 'true')
  const navigator = (await chart.boundingBox())!
  await page.mouse.move(navigator.x + 70, navigator.y + navigator.height - 33)
  await page.mouse.down(); await page.mouse.move(navigator.x + navigator.width * .35, navigator.y + navigator.height - 33, { steps: 10 }); await page.mouse.up()
  await expect(page.getByRole('button', { name: '1A', exact: true })).toHaveAttribute('aria-pressed', 'false')
  await page.getByRole('button', { name: 'Patrimônio', exact: true }).click()
  await expect(page.getByRole('img', { name: 'Evolução do patrimônio', exact: true })).toBeVisible()
  await page.getByText('Datas e valores do gráfico', { exact: true }).click()
  await page.getByLabel('Data inicial', { exact: true }).fill('2026-09-01')
  await expect(page.getByLabel('Data inicial', { exact: true })).toHaveValue('2026-09-01')
  await expect(page.locator('.chart-caption')).toContainText('01/09/2026')
  await page.getByLabel('Período do ganho patrimonial').selectOption('YTD')
  await expect(page.locator('.gain-card')).toContainText('10/04/2026')
})

test('shell chevron, selectors, timestamp and laptop/mobile fit remain usable', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message))
  await fixture(page)
  await page.goto('/overview')
  await expect(page.locator('.topbar h1')).toHaveCount(0)
  await expect(page.locator('.data-status')).toHaveText('Histórico até 06/10/2026')
  await page.getByRole('button', { name: 'Recolher navegação' }).click()
  await expect(page.locator('.sidebar')).toHaveClass(/collapsed/)
  await page.getByRole('button', { name: 'Expandir navegação' }).click()
  await page.getByRole('button', { name: 'Atualizar carteira', exact: true }).click()
  await expect(page.locator('.data-status')).toHaveText(/Atualizado hoje, 07 de outubro de 2026 às/)
  for (const width of [1280, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'width ' + width).toBeTruthy()
    await expect(page.getByLabel('Carteira', { exact: true })).toBeVisible()
    await expect(page.locator('.overview-chart-panel canvas')).toBeVisible()
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/overview-visual-mobile.png', fullPage: true })
  await page.evaluate(() => { document.documentElement.dataset.theme = 'dark' })
  await page.screenshot({ path: 'test-results/overview-visual-dark.png', fullPage: true })
  expect(errors).toEqual([])
})

test('USD, unknown totals, unavailable benchmarks and missing allocation never fabricate values', async ({ page }) => {
  await fixture(page, 'USD')
  await page.goto('/overview')
  await expect(page.locator('.wealth-card>strong')).toHaveText('US$ 284,520.17')
  await expect(page.getByLabel('Comparar com').locator('option').filter({ hasText: 'SPX' })).toHaveAttribute('disabled', '')
  await page.unroute('**/api/**')
  await fixture(page, 'BRL', true)
  await page.reload()
  await expect(page.locator('.wealth-card>strong')).toHaveText('—')
  await expect(page.locator('.gain-card>strong')).toHaveText('—')
  await expect(page.locator('.donut-total')).toContainText('Dados incompletos')
  await expect(page.locator('.overview-allocation canvas')).toHaveCount(0)
  await page.getByLabel('Comparar com').selectOption('CDI')
  await expect(page.getByText('CDI: cobertura incompleta para o período selecionado.', { exact: false })).toBeVisible()
})

test('restoring a custom chart period restores its dates and backend metric window after zoom', async ({ page }) => {
  await fixture(page)
  await page.setViewportSize({ width: 1672, height: 1050 })
  await page.goto('/overview')
  await page.getByText('Datas e valores do gráfico', { exact: true }).click()
  await page.getByLabel('Data inicial', { exact: true }).fill('2026-09-01')
  await page.getByLabel('Data final', { exact: true }).fill('2026-09-30')
  await expect(page.locator('.return-card')).toContainText('01/09/2026 a 30/09/2026')
  const chart = page.locator('.overview-chart-panel .financial-chart')
  await expect(chart.locator('canvas')).toBeVisible()
  const box = (await chart.boundingBox())!
  await page.mouse.move(box.x + box.width * .55, box.y + 110)
  await page.keyboard.down('Control'); await page.mouse.wheel(0, -350); await page.keyboard.up('Control')
  await expect(page.getByLabel('Data inicial', { exact: true })).not.toHaveValue('2026-09-01')
  await page.getByRole('button', { name: 'Restaurar período' }).click()
  await expect(page.getByLabel('Data inicial', { exact: true })).toHaveValue('2026-09-01')
  await expect(page.getByLabel('Data final', { exact: true })).toHaveValue('2026-09-30')
  await expect(page.locator('.return-card')).toContainText('01/09/2026 a 30/09/2026')

  // Editing a date after pointer zoom must retain the other displayed boundary
  // in both the chart and its backend metric window.
  await page.mouse.move(box.x + box.width * .55, box.y + 110)
  await page.keyboard.down('Control'); await page.mouse.wheel(0, -350); await page.keyboard.up('Control')
  await expect(page.getByLabel('Data final', { exact: true })).not.toHaveValue('2026-09-30')
  const end = await page.getByLabel('Data final', { exact: true }).inputValue()
  await page.getByLabel('Data inicial', { exact: true }).fill('2026-09-10')
  await expect(page.locator('.chart-accessible tbody tr').last().locator('td').first()).toHaveText(end.split('-').reverse().join('/'))
})

test('Overview retains the five largest positions with reporting-currency values and detail links', async ({ page }) => {
  await fixture(page)
  await page.route('**/api/portfolios/1/overview', route => route.fulfill({ json: {
    positions: ['AAPL', 'MSFT', 'CDB', 'WEGE3', 'ETF', 'BTC', 'SEM_COTACAO'].map((asset, i) => ({
      asset, asset_id: i + 1, position_type: asset === 'CDB' ? 'FIXED_INCOME' : 'MARKET',
      native_currency: 'BRL', display_value: [10, 60, 20, 30, 40, 50, null][i],
    })), assets: [], summary: { display_currency: 'BRL', total_value: null,
      positions: 7, history_status: 'incomplete', missing_prices: ['SEM_COTACAO'], missing_fx: [], missing_cost_fx: [] },
  } }))
  await page.goto('/overview')
  await page.getByText('Mais sobre a carteira', { exact: true }).click()
  const largest = page.getByRole('region', { name: 'Maiores posições', exact: true })
  await expect(largest).toBeVisible()
  await expect(largest.locator('tbody tr')).toHaveCount(5)
  await expect(largest.locator('tbody tr td:first-child')).toHaveText(['MSFT', 'BTC', 'ETF', 'WEGE3', 'CDB'])
  await expect(largest.locator('tbody tr').first()).toContainText(/R\$\s*60,00/)
  await expect(largest).toContainText('há posições com valor desconhecido')
  await expect(largest.getByRole('link', { name: 'CDB', exact: true })).toHaveAttribute('href', '/positions?type=fixed')
  await largest.screenshot({ path: 'test-results/overview-largest-desktop.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await largest.screenshot({ path: 'test-results/overview-largest-mobile.png' })
  await largest.getByRole('link', { name: 'MSFT', exact: true }).click()
  await expect(page).toHaveURL(/\/positions\/2$/)
})
