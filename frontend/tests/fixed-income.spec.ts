import { test, expect } from './auth-fixture'

test('waits for product defaults before allowing fixed-income selection', async ({ page, request }) => {
  const portfolioId = (await (await request.post('/api/portfolios', {
    data: { name: 'Fixed income defaults ' + Date.now() },
  })).json()).id
  let releaseProducts!: () => void
  const productRequest = new Promise<void>(resolve => { releaseProducts = resolve })
  await page.route('**/api/fixed-income/products', async route => {
    await productRequest
    const response = await route.fetch()
    const products = await response.json() as { symbol: string; day_count_basis: string }[]
    await route.fulfill({ response, json: products.map(product => product.symbol === 'CDB'
      ? { ...product, day_count_basis: 'ACT_365' } : product) })
  })

  await page.goto('/positions')
  await page.getByLabel('Carteira', { exact: true }).selectOption(String(portfolioId))
  await page.getByRole('button', { name: '+ Adicionar', exact: true }).click()
  await page.getByRole('button', { name: 'Nova aplicação em renda fixa', exact: true }).click()
  await expect(page.getByRole('listitem')).toHaveCount(0)
  await expect(page.getByText('Carregando produtos de renda fixa…')).toBeVisible()

  releaseProducts()
  await page.getByRole('listitem').filter({ hasText: 'CDB' }).click()
  await page.getByText('Configurações avançadas do contrato').click()
  await expect(page.getByLabel('Base de dias')).toHaveValue('ACT_365')
})

test('canonical fixed-income products prefill lots and appear in positions and operations', async ({ page, request }) => {
  const portfolioId = (await (await request.post('/api/portfolios', { data: { name: 'Fixed income UI ' + Date.now() } })).json()).id
  const benchmarks = await (await request.get('/api/benchmarks')).json() as { id: number; code: string }[]
  const products = await (await request.get('/api/fixed-income/products')).json() as { symbol: string; instrument_id: number }[]
  expect(products.map(row => row.symbol).sort()).toEqual(['CDB', 'LCA', 'LCI'])
  await page.goto('/positions')
  await page.getByLabel('Carteira', { exact: true }).selectOption(String(portfolioId))
  let lotPosts = 0
  let transactionPosts = 0
  page.on('request', outgoing => {
    if (outgoing.method() === 'POST' && outgoing.url().includes('/fixed-income/lots')) lotPosts++
    if (outgoing.method() === 'POST' && outgoing.url().endsWith('/transactions')) transactionPosts++
  })

  for (const [product, structure] of [['CDB', 'FIXED_RATE'], ['LCI', 'BENCHMARK_MULTIPLE'], ['LCA', 'BENCHMARK_SPREAD']] as const) {
    await page.getByRole('button', { name: '+ Adicionar', exact: true }).click()
    await page.getByRole('button', { name: 'Nova aplicação em renda fixa', exact: true }).click()
    await expect(page.getByLabel('Quantidade', { exact: true })).toHaveCount(0)
    await page.getByRole('listitem').filter({ hasText: product }).click()
    await page.getByText('Configurações avançadas do contrato').click()
    await expect(page.getByLabel('Moeda', { exact: true })).toHaveValue('BRL')
    await expect(page.getByLabel('Base de dias')).toHaveValue('BUS_252')
    await page.getByText('Configurações avançadas do contrato').click()
    await page.getByLabel('Emissor').fill('Banco Exemplo')
    await page.getByRole('dialog').getByLabel('Corretora', { exact: true }).fill('Corretora Exemplo')
    await page.getByLabel('Data da aplicação').fill('2024-01-02')
    await page.getByLabel('Vencimento').fill('2027-01-02')
    await page.getByLabel('Valor aplicado').fill('1000.25')
    await page.getByLabel('Estrutura de rendimento').selectOption(structure)
    if (structure === 'FIXED_RATE') {
      await page.getByLabel(/Taxa fixa anual/).fill('0.12')
    } else {
      await page.getByRole('combobox', { name: 'Indexador', exact: true }).selectOption(String(benchmarks.find(row => row.code === 'CDI')!.id))
      if (structure === 'BENCHMARK_MULTIPLE') await page.getByLabel(/Multiplicador/).fill('1.10')
      else await page.getByLabel(/Spread anual/).fill('0.06')
    }
    await page.getByRole('button', { name: 'Registrar lote' }).click()
    await expect(page.getByText('Lote de renda fixa registrado.')).toBeVisible()
  }
  expect(lotPosts).toBe(3)
  expect(transactionPosts).toBe(0)
  expect(await (await request.get(`/api/portfolios/${portfolioId}/transactions`)).json()).toEqual([])
  const lots = await (await request.get(`/api/portfolios/${portfolioId}/fixed-income/lots`)).json()
  expect(lots.map((lot: { product_type: string }) => lot.product_type)).toEqual(['CDB', 'LCI', 'LCA'])
  expect(lots.every((lot: { movements: { movement_type: string; amount: string }[] }) =>
    lot.movements.length === 1 && lot.movements[0].movement_type === 'INITIAL_INVESTMENT' && Number(lot.movements[0].amount) === 1000.25)).toBeTruthy()
  await page.goto('/fixed-income/' + lots[0].id)
  await expect(page.getByRole('heading', { name: 'Condições da aplicação' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Linha do tempo' })).toBeVisible()
  await expect(page.getByText('Principal atual · BRL', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Aportar', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Resgatar', exact: true })).toBeVisible()
  await page.goto('/positions')
  await expect(page.getByRole('heading', { name: 'Renda fixa' })).toBeVisible()
  await expect(page.locator('section.panel').filter({ has: page.getByRole('heading', { name: 'Renda fixa', exact: true }) }).getByRole('row')).toHaveCount(4)
  await page.getByRole('link', { name: 'Transações', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Movimentos de renda fixa' })).toBeVisible()
  await expect(page.getByRole('table').filter({ hasText: 'Aplicação inicial' }).getByRole('row')).toHaveCount(4)
})

test('redeems, edits and deletes a fixed-income movement through the shared form', async ({ page, request }) => {
  const portfolioId = (await (await request.post('/api/portfolios', {
    data: { name: 'Redemption UI ' + Date.now() },
  })).json()).id
  const products = await (await request.get('/api/fixed-income/products')).json() as { symbol: string; instrument_id: number }[]
  const cdb = products.find(row => row.symbol === 'CDB')!
  const localDay = (daysAgo: number) => {
    const day = new Date()
    day.setDate(day.getDate() - daysAgo)
    return new Date(day.getTime() - day.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
  }
  const lotResponse = await request.post(`/api/portfolios/${portfolioId}/fixed-income/lots`, { data: {
    instrument_id: cdb.instrument_id, product_type: 'CDB', issuer: 'Banco Teste', broker: 'Corretora Teste',
    currency: 'BRL', start_date: localDay(3), maturity_date: null, opening_amount: '1000',
    yield_structure: 'FIXED_RATE', fixed_rate: '0', day_count_basis: 'ACT_365',
    compounding: 'COMPOUND', business_day_calendar: 'NONE', benchmark_lag_months: 0,
  } })
  expect(lotResponse.ok()).toBeTruthy()
  const lot = await lotResponse.json() as { id: number }

  await page.goto('/positions')
  await page.getByLabel('Carteira', { exact: true }).selectOption(String(portfolioId))
  await page.getByRole('link', { name: 'Transações', exact: true }).click()
  await page.getByRole('button', { name: '+ Adicionar', exact: true }).click()
  await page.getByRole('button', { name: 'Nova aplicação em renda fixa', exact: true }).click()
  await page.getByRole('button', { name: 'Fechar formulário', exact: true }).click()
  await page.getByRole('button', { name: '+ Adicionar', exact: true }).click()
  await page.getByRole('button', { name: 'Resgate de renda fixa', exact: true }).click()
  await page.getByRole('combobox', { name: 'Lote' }).selectOption(String(lot.id))
  await page.getByLabel('Data do movimento').fill(localDay(2))
  await page.getByLabel('Valor bruto resgatado').fill('550')
  await page.getByRole('button', { name: 'Salvar movimento' }).click()
  const movements = page.getByRole('table').filter({ hasText: 'Aplicação inicial' })
  await expect(movements.getByText('Resgate parcial')).toBeVisible()
  await movements.getByRole('row').filter({ hasText: 'Resgate parcial' }).locator('summary').click()
  await movements.getByRole('row').filter({ hasText: 'Resgate parcial' }).getByRole('button', { name: 'Editar' }).click()
  await page.getByLabel('Valor bruto resgatado').fill('400')
  await page.getByRole('button', { name: 'Salvar movimento' }).click()
  await expect(movements.getByRole('row').filter({ hasText: 'Resgate parcial' })).toContainText('400,00')
  page.once('dialog', dialog => dialog.accept())
  await movements.getByRole('row').filter({ hasText: 'Resgate parcial' }).getByRole('button', { name: 'Excluir' }).click()
  await expect(movements.getByText('Resgate parcial')).toHaveCount(0)

  await page.goto('/data/benchmarks')
  await expect(page.getByRole('heading', { name: 'Dados dos indexadores' })).toBeVisible()
  await page.getByRole('combobox', { name: 'Indexador' }).selectOption('IPCA')
  await expect(page.getByText(/observações · de/)).toBeVisible()
})
