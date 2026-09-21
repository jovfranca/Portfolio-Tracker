import { test, expect } from '@playwright/test'

test('resolve an unknown imported identifier explicitly and reuse its alias', async ({ page, request }) => {
  const raw = 'UNKNOWN' + Date.now()
  const result = await request.post('/api/portfolios', { data: { name: 'Resolution browser test' } })
  const portfolio = await result.json()
  await page.goto('/#/transactions/import')
  await page.getByLabel('Carteira', { exact: true }).selectOption(String(portfolio.id))
  const file = { name: 'resolve.csv', mimeType: 'text/csv', buffer: Buffer.from(
    'ticker,broker,type,trade_date,settlement_date,quantity,unit_price,asset_currency\n' +
    `${raw},Example,Buy,2024-01-02,2024-01-03,1,10,BRL\n`) }
  await page.locator('input[type=file]').setInputFiles(file)
  await expect(page.getByRole('button', { name: 'Confirmar importação', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Cadastrar instrumento manual', exact: true }).click()
  await page.getByLabel('Símbolo canônico', { exact: true }).fill('CANONICAL' + Date.now())
  await page.getByRole('button', { name: 'Confirmar instrumento', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Confirmar importação', exact: true })).toBeEnabled()
  expect(await (await request.get(`/api/portfolios/${portfolio.id}/transactions`)).json()).toEqual([])
  await page.getByRole('button', { name: 'Confirmar importação', exact: true }).click()
  await expect(page.getByText('1 transação(ões) importada(s).', { exact: true })).toBeVisible()
  await page.locator('input[type=file]').setInputFiles({ ...file, buffer: Buffer.concat([file.buffer, Buffer.from('\n')]) })
  await expect(page.getByRole('button', { name: 'Confirmar importação', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Cadastrar instrumento manual', exact: true })).toHaveCount(0)
})

test('provider selection confirms canonical metadata instead of saving the search term', async ({ page, request }) => {
  const portfolio = await (await request.post('/api/portfolios', { data: { name: 'Search browser test' } })).json()
  await page.route('**/api/instruments/search?*', route => route.fulfill({ json: [{
    instrument_id: null, symbol: 'PETR4.SA', name: 'Petrobras', asset_type: 'STOCK',
    currency: '', exchange: 'SAO', status: 'ACTIVE', provider: 'yfinance',
    provider_symbol: 'PETR4.SA',
  }] }))
  await page.goto('/')
  await page.getByLabel('Carteira', { exact: true }).selectOption(String(portfolio.id))
  await page.getByRole('button', { name: '+ Nova transação', exact: true }).click()
  await page.getByLabel('Instrumento', { exact: true }).fill('Petrobras')
  await page.getByRole('button', { name: 'Pesquisar', exact: true }).click()
  await page.getByRole('button', { name: /PETR4.SA · Petrobras/ }).click()
  await expect(page.getByLabel('Moeda da cotação do provedor', { exact: true })).toHaveValue('')
  await expect(page.getByRole('button', { name: 'Confirmar instrumento', exact: true })).toBeDisabled()
  await page.getByLabel('Moeda da cotação do provedor', { exact: true }).fill('BRL')
  await page.getByRole('checkbox').check()
  await page.getByLabel('Símbolo canônico', { exact: true }).fill('PETR4')
  await page.getByRole('button', { name: 'Confirmar instrumento', exact: true }).click()
  await expect(page.getByLabel('Instrumento', { exact: true })).toHaveValue('PETR4')
  await expect(page.getByLabel('Moeda da transação', { exact: true })).toHaveValue('BRL')
  await expect(page.getByLabel('Moeda da transação', { exact: true })).toBeDisabled()
  await page.getByLabel('Corretora', { exact: true }).fill('Example')
  await page.getByLabel('Classe de alocação', { exact: true }).fill('Stocks')
  await page.getByRole('button', { name: 'Salvar transação', exact: true }).click()
  await expect(page.getByText('Transação salva. Posições recalculadas.', { exact: true })).toBeVisible()
  const transactions = await (await request.get(`/api/portfolios/${portfolio.id}/transactions`)).json()
  expect(transactions[0].asset).toBe('PETR4')
  expect(transactions[0].instrument_id).toBeGreaterThan(0)
})

test('performance uses the selected instrument when symbols are identical', async ({ page, request }) => {
  const portfolio = await (await request.post('/api/portfolios', { data: { name: 'Duplicate symbol test' } })).json()
  for (const exchange of ['FIRST', 'SECOND']) {
    const instrument = await (await request.post('/api/instruments', { data: { symbol: 'SAME', currency: 'BRL', exchange } })).json()
    const saved = await request.post(`/api/portfolios/${portfolio.id}/transactions`, { data: {
      instrument_id: instrument.id, asset: 'SAME', asset_currency: 'BRL', broker: 'Example', allocation_class: 'Stocks',
      type: 'Buy', quantity: 1, price: 10, trade_date: '2024-01-02', settlement_date: '2024-01-03',
    } })
    expect(saved.ok()).toBeTruthy()
  }
  const overview = await (await request.get(`/api/portfolios/${portfolio.id}/overview`)).json()
  await page.goto('/#/performance')
  await page.getByLabel('Carteira', { exact: true }).selectOption(String(portfolio.id))
  await expect(page.getByRole('combobox', { name: 'Posição', exact: true }).locator('option')).toHaveCount(2)
  const response = page.waitForResponse(r => r.url().includes('/performance?') && r.url().includes('asset_id=' + overview.positions[1].asset_id))
  await page.getByRole('combobox', { name: 'Posição', exact: true }).selectOption('1')
  expect((await response).ok()).toBeTruthy()
})

test('crypto quote variants keep one identity and preserve BRL transaction currency', async ({ page, request }) => {
  const portfolio = await (await request.post('/api/portfolios', { data: { name: 'Crypto currency browser test' } })).json()
  await page.route('**/api/instruments/search?*', route => {
    const category = new URL(route.request().url()).searchParams.get('category')
    const results = [
      { instrument_id: null, symbol: 'BTC', name: 'Bitcoin', asset_type: 'CRYPTO', currency: null, quote_currency: 'USD', exchange: 'CCC', status: 'ACTIVE', provider: 'yfinance', provider_symbol: 'BTC-USD' },
      { instrument_id: null, symbol: 'BTC', name: 'Bitcoin Euro', asset_type: 'CRYPTO', currency: null, quote_currency: 'EUR', exchange: 'CCC', status: 'ACTIVE', provider: 'yfinance', provider_symbol: 'BTC-EUR' },
      { instrument_id: null, symbol: 'GBTC', name: 'Bitcoin Trust', asset_type: 'ETF', currency: 'USD', quote_currency: 'USD', exchange: 'PCX', status: 'ACTIVE', provider: 'yfinance', provider_symbol: 'GBTC' },
    ]
    return route.fulfill({ json: results.filter(item => category === 'ALL' || category === item.asset_type) })
  })
  await page.goto('/')
  await page.getByLabel('Carteira', { exact: true }).selectOption(String(portfolio.id))
  await page.getByRole('button', { name: '+ Nova transa\u00e7\u00e3o', exact: true }).click()
  await page.getByLabel('Instrumento', { exact: true }).fill('Bitcoin')
  await page.getByRole('button', { name: 'Pesquisar', exact: true }).click()
  await expect(page.getByRole('button', { name: /GBTC.*\[ETF\].*USD.*PCX/ })).toBeVisible()
  await page.getByRole('combobox', { name: 'Categoria', exact: true }).selectOption('CRYPTO')
  await page.getByRole('button', { name: 'Pesquisar', exact: true }).click()
  await expect(page.getByRole('button', { name: /GBTC/ })).toHaveCount(0)
  await page.getByRole('button', { name: /BTC .*Bitcoin .*\[CRYPTO\].*USD/ }).click()
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Confirmar instrumento', exact: true }).click()
  await expect(page.getByLabel('Moeda da transa\u00e7\u00e3o', { exact: true })).toHaveValue('BRL')
  await expect(page.getByLabel('Moeda da transa\u00e7\u00e3o', { exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Pesquisar', exact: true }).click()
  await page.getByRole('button', { name: /BTC .*Bitcoin Euro .*\[CRYPTO\].*EUR/ }).click()
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Confirmar instrumento', exact: true }).click()
  await expect(page.getByLabel('Moeda da transa\u00e7\u00e3o', { exact: true })).toHaveValue('BRL')
  await page.getByLabel('Corretora', { exact: true }).fill('Example')
  await page.getByLabel('Classe de aloca\u00e7\u00e3o', { exact: true }).fill('Crypto')
  await page.getByRole('button', { name: 'Salvar transa\u00e7\u00e3o', exact: true }).click()
  await expect(page.getByText('Transa\u00e7\u00e3o salva. Posi\u00e7\u00f5es recalculadas.', { exact: true })).toBeVisible()
  const usd = await (await request.post('/api/instruments', { data: { symbol: 'BTC', asset_type: 'CRYPTO', provider_symbol: 'BTC-USD', quote_currency: 'USD', provider_currency_confirmed: true } })).json()
  const eur = await (await request.post('/api/instruments', { data: { symbol: 'BTC', asset_type: 'CRYPTO', provider_symbol: 'BTC-EUR', quote_currency: 'EUR', provider_currency_confirmed: true } })).json()
  expect(usd.id).toBe(eur.id)
  const transactions = await (await request.get(`/api/portfolios/${portfolio.id}/transactions`)).json()
  expect(transactions[0].instrument_id).toBe(usd.id)
  expect(transactions[0].asset_currency).toBe('BRL')
})
