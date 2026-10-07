// Product navigation and action vocabulary. API/domain enum values stay unchanged.
export const navigation = [
  ['/overview', 'Visão geral', 'overview'], ['/positions', 'Posições', 'positions'],
  ['/transactions', 'Transações', 'transactions'], ['/performance', 'Desempenho', 'performance'],
  ['/data/status', 'Dados de mercado', 'data'], ['/instruments', 'Instrumentos', 'instruments'],
] as const
export const addActions = [
  ['transaction', 'Nova transação'], ['lot', 'Nova aplicação em renda fixa'],
  ['contribution', 'Aporte em renda fixa'], ['redemption', 'Resgate de renda fixa'], ['import', 'Importar transações'],
] as const
export type AddAction = typeof addActions[number][0]
export const movementLabels: Record<string, string> = {
  INITIAL_INVESTMENT: 'Aplicação inicial', ADDITIONAL_INVESTMENT: 'Aporte adicional',
  PARTIAL_REDEMPTION: 'Resgate parcial', FULL_REDEMPTION: 'Resgate total', MATURITY: 'Vencimento', AMORTIZATION: 'Amortização',
}
export const typeLabels: Record<string, string> = { STOCK: 'Ação', ETF: 'ETF', CRYPTO: 'Cripto', FIXED_INCOME: 'Renda fixa', OTHER: 'Personalizado', CATALOG: 'Mercado', CUSTOM: 'Privado', MIGRATED: 'Migrado' }
