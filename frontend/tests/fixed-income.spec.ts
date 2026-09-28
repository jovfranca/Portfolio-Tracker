import { test, expect } from '@playwright/test'

test('creates fixed-income lots with one opening movement and yield-specific terms', async ({ page, request }) => {
  const portfolioId = (await (await request.post('/api/portfolios', { data: { name: 'Fixed income UI ' + Date.now() } })).json()).id
  const benchmarks = await (await request.get('/api/benchmarks')).json() as { id: number; code: string }[]
  expect(benchmarks.some(row => row.code === 'CDI')).toBeTruthy()
  await page.goto('/')
  await page.getByLabel('Carteira', { exact: true }).selectOption(String(portfolioId))
  const symbol = 'UICDB' + Date.now()
  let lotPosts = 0
  let transactionPosts = 0
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().includes('/fixed-income/lots')) lotPosts++
    if (request.method() === 'POST' && request.url().endsWith('/transactions')) transactionPosts++
  })

  for (const [product, structure] of [['CDB', 'FIXED_RATE'], ['LCI', 'BENCHMARK_MULTIPLE'], ['LCA', 'BENCHMARK_SPREAD']] as const) {
    await page.getByRole('button', { name: '+ Nova transação', exact: true }).click()
    await expect(page.getByLabel('Instrumento', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Renda fixa', exact: true }).click()
    await expect(page.getByLabel('Quantidade', { exact: true })).toHaveCount(0)
    await page.getByLabel('Instrumento', { exact: true }).fill(symbol)
    if (product === 'CDB') {
      await page.getByRole('button', { name: 'Criar instrumento de renda fixa' }).click()
      await page.getByLabel('Nome do ativo', { exact: true }).fill('CDB UI test')
      await page.getByLabel('Símbolo', { exact: true }).fill(symbol)
      await page.getByRole('button', { name: 'Criar ativo personalizado' }).click()
    } else {
      await page.getByRole('button', { name: 'Pesquisar no catálogo' }).click()
      await page.getByRole('listitem').filter({ hasText: symbol }).click()
    }
    await page.getByLabel('Produto').selectOption(product)
    await page.getByLabel('Emissor').fill('Banco Exemplo')
    await page.getByLabel('Corretora').fill('Corretora Exemplo')
    await page.getByLabel('Data da aplicação').fill('2024-01-02')
    await page.getByLabel('Vencimento').fill('2027-01-02')
    await page.getByLabel('Valor aplicado').fill('1000.25')
    await page.getByLabel('Estrutura de rendimento').selectOption(structure)
    if (structure === 'FIXED_RATE') {
      await expect(page.getByRole('combobox', { name: 'Indexador', exact: true })).toHaveCount(0)
      await page.getByLabel(/Taxa fixa anual/).fill('0.12')
    } else {
      await expect(page.getByLabel(/Taxa fixa anual/)).toHaveCount(0)
      await page.getByRole('combobox', { name: 'Indexador', exact: true }).selectOption(String(benchmarks.find(row => row.code === 'CDI')!.id))
      if (structure === 'BENCHMARK_MULTIPLE') await page.getByLabel(/Multiplicador/).fill('1.10')
      else await page.getByLabel(/Spread anual/).fill('0.06')
    }
    await page.getByRole('button', { name: 'Registrar lote' }).click()
    await expect(page.getByText('Lote de renda fixa registrado. Avaliação pendente.')).toBeVisible()
  }
  expect(lotPosts).toBe(3)
  expect(transactionPosts).toBe(0)
  expect(await (await request.get(`/api/portfolios/${portfolioId}/transactions`)).json()).toEqual([])
  const lots = await (await request.get(`/api/portfolios/${portfolioId}/fixed-income/lots`)).json()
  expect(lots.map((lot: { product_type: string }) => lot.product_type)).toEqual(['CDB', 'LCI', 'LCA'])
  expect(lots.every((lot: { movements: { movement_type: string; amount: string }[] }) =>
    lot.movements.length === 1 && lot.movements[0].movement_type === 'INITIAL_INVESTMENT' && Number(lot.movements[0].amount) === 1000.25)).toBeTruthy()
  expect(lots.every((lot: { current_value: null; valuation_status: string }) => lot.current_value === null && lot.valuation_status === 'pending')).toBeTruthy()
})
