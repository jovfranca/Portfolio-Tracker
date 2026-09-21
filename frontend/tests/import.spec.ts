import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

test.beforeEach(async ({ page, request }) => {
  for (const [symbol, currency] of [['IMPORTTEST', 'USD'], ['FICTICIO-BR', 'BRL'], ['FICTICIO-US', 'USD']]) {
    const response = await request.post('/api/instruments', { data: { symbol, quote_currency: currency, provider_symbol: symbol, provider_currency_confirmed: true } })
    expect(response.ok()).toBeTruthy()
  }
  await page.goto('/')
  await page.getByRole('button', { name: '+ Carteira', exact: true }).click()
  await page.getByLabel('Nome da carteira', { exact: true }).fill('Import test ' + Date.now())
  await page.getByRole('button', { name: 'Criar carteira', exact: true }).click()
  await page.getByRole('button', { name: 'Transações', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Histórico de operações' })).toBeVisible()
  await expect(page.locator('input[type=file]')).toHaveCount(0)
  await page.getByRole('button', { name: 'Importar transações', exact: true }).click()
  await expect(page).toHaveURL(/#\/transactions\/import$/)
  await expect(page.getByRole('heading', { name: 'Importar transações', exact: true })).toBeVisible()
})

test('review import values, reject duplicates, and preserve manual decimals', async ({ page, request }) => {
  const file = {
    name: 'records.csv', mimeType: 'text/csv', buffer: Buffer.from(
      'ticker,broker,type,trade_date,settlement_date,quantity,unit_price,asset_currency,fx_rate\n' +
      'IMPORTTEST,Example,Buy,2024-01-02,2024-01-03,12345.123456789012,10.000000000001,USD,5.123456789012\n'),
  }
  await page.locator('input[type=file]').setInputFiles(file)
  const preview = page.getByRole('table', { name: 'Prévia da importação' })
  await expect(preview).toContainText('IMPORTTEST')
  await expect(preview).toContainText('12345.123456789012')
  await expect(preview).toContainText('5.123456789012')
  const portfolioId = await page.getByLabel('Carteira', { exact: true }).inputValue()
  expect(await (await request.get(`/api/portfolios/${portfolioId}/transactions`)).json()).toEqual([])
  await page.getByRole('button', { name: 'Confirmar importação', exact: true }).click()
  await expect(preview).not.toBeVisible()
  await page.locator('input[type=file]').setInputFiles(file)
  await expect(page.getByText('Este arquivo já foi importado para esta carteira.', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Confirmar importação', exact: true })).toBeDisabled()
  await page.getByRole('link', { name: 'Voltar para Transações' }).click()
  await expect(page).toHaveURL(/#\/transactions$/)
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  await page.getByLabel('Quantidade', { exact: true }).fill('98765.123456789012')
  await page.getByLabel('Taxa FX', { exact: true }).fill('5.987654321012')
  const saved = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().includes('/transactions/'))
  await page.getByRole('button', { name: 'Salvar transação', exact: true }).click()
  const response = await saved
  expect(response.status()).toBe(200)
  expect(await response.json()).toMatchObject({ quantity: '98765.123456789012', fx_rate: '5.987654321012', price: '10.000000000001' })
})

test('download and import the XLSX template, navigate back and render on mobile', async ({ page, request }) => {
  const spec = page.getByRole('table', { name: 'Colunas aceitas pelo importador' })
  await expect(spec.locator('tbody tr')).toHaveCount(13)
  await expect(spec).toContainText('Buy, Sell, Compra ou Venda')
  await expect(spec).toContainText('allocation_class')
  const portfolioId = await page.getByLabel('Carteira', { exact: true }).inputValue()
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Baixar planilha modelo' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('modelo-transacoes.xlsx')
  const path = await download.path()
  expect(path).not.toBeNull()
  await page.locator('input[type=file]').setInputFiles({ name: download.suggestedFilename(), mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: await readFile(path!) })
  await expect(page.getByRole('table', { name: 'Prévia da importação' }).locator('tbody tr')).toHaveCount(3)
  await page.getByRole('button', { name: 'Confirmar importação', exact: true }).click()
  await expect(page.getByText('3 transação(ões) importada(s).', { exact: true })).toBeVisible()
  const overview = await (await request.get(`/api/portfolios/${portfolioId}/overview`)).json()
  expect(overview.positions.find((p: { asset: string }) => p.asset === 'FICTICIO-BR').quantity).toBe(8)
  await page.getByRole('link', { name: 'Voltar para Transações' }).click()
  await expect(page.locator('tbody tr')).toHaveCount(3)
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Importar transações', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Importar transações', exact: true })).toBeVisible()
  await page.getByLabel('Carteira', { exact: true }).selectOption(portfolioId)
  await page.screenshot({ path: 'test-results/import-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/import-mobile.png', fullPage: true })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await expect(page.getByRole('link', { name: 'Baixar planilha modelo' })).toBeVisible()
})

test('show backend row errors and malformed file errors without saving', async ({ page, request }) => {
  await page.locator('input[type=file]').setInputFiles({ name: 'invalid.csv', mimeType: 'text/csv', buffer: Buffer.from(
    'ticker,type,trade_date,settlement_date,quantity,unit_price,asset_currency\n' +
    'FICTICIO,Dividend,31/12/2024,2024-01-04,abc,10,BRL\n'),
  })
  const errors = page.getByRole('table', { name: 'Erros de importação' })
  await expect(errors).toContainText('broker')
  await expect(errors).toContainText('Campo obrigatório ausente ou vazio.')
  await expect(errors).toContainText('type')
  await expect(errors).toContainText('trade_date')
  await expect(errors).toContainText('quantity')
  await expect(page.getByRole('button', { name: 'Confirmar importação', exact: true })).toBeDisabled()
  await page.locator('input[type=file]').setInputFiles({ name: 'broken.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.from('not a spreadsheet') })
  await expect(page.getByRole('alert').filter({ hasText: 'Não foi possível validar o arquivo.' })).toContainText('Não foi possível ler a planilha XLSX.')
  const portfolioId = await page.getByLabel('Carteira', { exact: true }).inputValue()
  expect(await (await request.get(`/api/portfolios/${portfolioId}/transactions`)).json()).toEqual([])
})
