import { test, expect, type APIRequestContext, type Page } from '@playwright/test'

async function portfolio(request: APIRequestContext, name: string) {
  return (await (await request.post('/api/portfolios', { data: { name } })).json()).id as number
}

async function openTransaction(page: Page, portfolioId: number) {
  await page.goto('/')
  await page.getByLabel('Carteira', { exact: true }).selectOption(String(portfolioId))
  await page.getByRole('button', { name: '+ Nova transação', exact: true }).click()
}

test('selects trusted ARKX without exposing canonical or provider metadata', async ({ page, request }) => {
  const portfolioId = await portfolio(request, 'ARKX catalog browser test')
  await openTransaction(page, portfolioId)
  await page.getByLabel('Instrumento', { exact: true }).fill('ARKX')
  await page.getByRole('button', { name: 'Pesquisar no catálogo', exact: true }).click()
  const result = page.getByRole('listitem').filter({ hasText: 'ARK Space & Defense Innovation ETF' })
  await expect(result).toHaveCount(1)
  await result.click()
  await expect(page.getByLabel('Instrumento', { exact: true })).toHaveValue('ARKX')
  await expect(page.getByLabel('Instrumento', { exact: true })).toHaveAttribute('readonly', '')
  await expect(page.getByLabel('Moeda da transação', { exact: true })).toHaveValue('USD')
  await expect(page.getByLabel('Moeda da transação', { exact: true })).toBeDisabled()
  await expect(page.getByText(/Símbolo no provedor|Moeda da cotação do provedor|Símbolo canônico/)).toHaveCount(0)
  await page.getByLabel('Corretora', { exact: true }).fill('Example')
  await page.getByLabel('Classe de alocação', { exact: true }).fill('ETF')
  await page.getByLabel('Taxa FX', { exact: true }).fill('5')
  await page.getByRole('button', { name: 'Salvar transação', exact: true }).click()
  await expect(page.getByText('Transação salva. Posições recalculadas.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Transações', exact: true }).click()
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  await expect(page.getByLabel('Moeda da transação', { exact: true })).toBeDisabled()
})

test('selects Bitcoin and saves a BRL transaction without mapping configuration', async ({ page, request }) => {
  const portfolioId = await portfolio(request, 'BTC BRL browser test')
  await openTransaction(page, portfolioId)
  await page.getByRole('button', { name: 'Cripto', exact: true }).click()
  await page.getByLabel('Instrumento', { exact: true }).fill('Bitcoin')
  await page.getByRole('button', { name: 'Pesquisar no catálogo', exact: true }).click()
  await page.getByRole('listitem').filter({ hasText: 'Bitcoin' }).click()
  await expect(page.getByLabel('Moeda da transação', { exact: true })).toHaveValue('BRL')
  await expect(page.getByLabel('Moeda da transação', { exact: true })).toBeEnabled()
  await page.getByLabel('Corretora', { exact: true }).fill('Example')
  await page.getByLabel('Classe de alocação', { exact: true }).fill('Cripto')
  await page.getByLabel('Quantidade', { exact: true }).fill('0.01')
  await page.getByLabel('Preço unitário', { exact: true }).fill('398000')
  await page.getByRole('button', { name: 'Salvar transação', exact: true }).click()
  await expect(page.getByText('Transação salva. Posições recalculadas.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Transações', exact: true }).click()
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  await expect(page.getByLabel('Moeda da transação', { exact: true })).toBeEnabled()
  const transactions = await (await request.get(`/api/portfolios/${portfolioId}/transactions`)).json()
  expect(transactions[0].asset).toBe('BTC')
  expect(transactions[0].transaction_currency).toBe('BRL')
})

test('creates an explicitly manual custom asset', async ({ page, request }) => {
  const portfolioId = await portfolio(request, 'Custom asset browser test')
  const symbol = 'PRIVATE' + Date.now()
  await openTransaction(page, portfolioId)
  await page.getByLabel('Instrumento', { exact: true }).fill(symbol)
  await page.getByRole('button', { name: 'Personalizado', exact: true }).click()
  await page.getByLabel('Nome do ativo', { exact: true }).fill('Private company')
  await page.getByRole('button', { name: 'Criar ativo personalizado', exact: true }).click()
  await expect(page.getByText(/Instrumento selecionado:/)).toContainText(symbol)
  await page.getByLabel('Corretora', { exact: true }).fill('Direct')
  await page.getByLabel('Classe de alocação', { exact: true }).fill('Privado')
  await page.getByRole('button', { name: 'Salvar transação', exact: true }).click()
  await expect(page.getByText('Transação salva. Posições recalculadas.', { exact: true })).toBeVisible()
})

test('resolves an unknown import only through explicit custom creation', async ({ page, request }) => {
  const raw = 'UNKNOWN' + Date.now()
  const portfolioId = await portfolio(request, 'Import resolution browser test')
  await page.goto('/#/transactions/import')
  await page.getByLabel('Carteira', { exact: true }).selectOption(String(portfolioId))
  const file = { name: 'resolve.csv', mimeType: 'text/csv', buffer: Buffer.from(
    'ticker,broker,type,trade_date,settlement_date,quantity,unit_price,transaction_currency\n' +
    `${raw},Example,Buy,2024-01-02,2024-01-03,1,10,BRL\n`) }
  await page.locator('input[type=file]').setInputFiles(file)
  await expect(page.getByRole('button', { name: 'Confirmar importação', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Personalizado', exact: true }).click()
  await page.getByLabel('Nome do ativo', { exact: true }).fill('Imported custom asset')
  await page.getByRole('button', { name: 'Criar ativo personalizado', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Confirmar importação', exact: true })).toBeEnabled()
  expect(await (await request.get(`/api/portfolios/${portfolioId}/transactions`)).json()).toEqual([])
})

test('catalog inspection is read-only and shows primary mappings', async ({ page }) => {
  await page.goto('/#/catalog')
  await expect(page.getByRole('heading', { name: 'Catálogo de instrumentos' })).toBeVisible()
  await expect(page.getByText(/BTC-USD · USD · PRINCIPAL/)).toBeVisible()
  await expect(page.getByText(/ARKX · USD · PRINCIPAL/)).toBeVisible()
  await expect(page.getByRole('button', { name: /Editar|Salvar catálogo/ })).toHaveCount(0)
})
