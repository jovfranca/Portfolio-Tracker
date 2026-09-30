export type Portfolio = { id: number; name: string; display_currency: string; dirty_from: string | null; history_built_through: string | null }
export type Numeric = number | string
export type Transaction = {
  id: number; portfolio_id: number; trade_date: string; settlement_date: string;
  instrument_id: number;
  type: 'Buy' | 'Sell'; asset: string; broker: string; allocation_class: string;
  transaction_currency: string; fx_rate: Numeric | null; quantity: Numeric;
  price: Numeric; brokerage_fee: Numeric; other_fees: Numeric; notes: string;
  transaction_currency_locked: boolean
}
export type InstrumentSearchResult = {
  instrument_id: number | null; symbol: string; name: string; asset_type: 'STOCK' | 'ETF' | 'CRYPTO' | 'FIXED_INCOME' | 'OTHER';
  exchange: string | null; currency: string | null; status: 'ACTIVE' | 'INACTIVE' | 'DELISTED';
  quote_currency?: string | null;
  quote_currencies?: string[];
  provider: string | null; provider_symbol: string | null; provider_exchange?: string | null
  is_custom?: boolean
}
export type CatalogInstrument = {
  id: number; symbol: string; name: string; asset_type: string; exchange: string | null;
  currency: string | null; status: string; mappings: Array<{ provider: string; provider_symbol: string;
    quote_currency: string; is_primary: boolean; active: boolean }>
}
export type ImportPreviewRow = {
  row: number; valid: boolean; data?: Omit<Transaction, 'id' | 'portfolio_id' | 'instrument_id' | 'transaction_currency_locked'> & { instrument_id?: number | null };
  instrument_resolution?: 'resolved' | 'unresolved' | 'ambiguous' | 'not_requested';
  errors: { field: string; message: string }[]
}
export type ImportPreview = {
  digest: string; filename: string; valid: boolean; already_imported: boolean;
  rows: ImportPreviewRow[]
}
export type Position = {
  position_type?: 'FIXED_INCOME';
  native_currency: string | null;
  quote_currency: string | null; status: string; gross_income: Numeric | null;
  asset_id: number | null;
  asset: string; broker: string; allocation_class: string; transaction_currency: string | null; quantity: Numeric | null;
  average_cost: Numeric | null; acquisition_cost: Numeric | null; current_price: Numeric | null; total_value: Numeric | null;
  display_average_cost: Numeric | null; display_acquisition_cost: Numeric | null;
  native_average_cost: Numeric | null; native_acquisition_cost: Numeric | null;
  display_currency: string; display_price: Numeric | null; display_value: Numeric | null;
  broker_breakdown: { broker: string; quantity: Numeric; average_cost: Numeric | null; acquisition_cost: Numeric | null }[];
  current_total_gain: Numeric | null; current_accumulated_profitability: Numeric | null; return_date?: string | null;
  valuation_date?: string; action_coverage_through?: string;
  native_gross_income: Numeric | null;
  price_date: string | null; gain_date: string | null; history_behind_transactions: boolean; quote_refresh_required?: boolean;
  income_by_currency: Record<string, Numeric>; corporate_action_count: number
}
export type Asset = { id: number; ticker: string; transaction_currency: string | null; quantity: Numeric; average_cost: Numeric | null;
  current_price: Numeric | null; total_value: Numeric | null; price_date: string | null;
  income_by_currency: Record<string, Numeric>; corporate_action_count: number }
export type Overview = { positions: Position[]; assets: Asset[];
  fixed_income?: { lot_count: number; valuation_status: 'none' | 'pending' | 'complete' | 'incomplete';
    lots: { id: number; asset_id: number; instrument_id: number; currency: string;
      gross_accrued_value: Numeric | null; status: string }[]; positions?: Position[] };
  summary: { transactions: number; positions: number; assets: number; priced_value: number | null;
    total_value: number | null; missing_prices: string[]; missing_fx: string[]; missing_cost_fx: string[]; missing_actions?: string[]; display_currency: string; currencies: string[];
    totals_by_currency: Record<string, number>; income_by_currency: Record<string, Numeric>;
    history_status: string; dirty_from: string | null; gross_income: Numeric | null }; methodology: string }
export type FixedIncomeLot = {
  id: number; instrument_symbol: string; instrument_name: string; product_type: string;
  issuer: string; broker: string; currency: string; start_date: string; maturity_date: string | null;
  yield_structure: 'FIXED_RATE' | 'BENCHMARK_MULTIPLE' | 'BENCHMARK_SPREAD';
  fixed_rate: string | null; benchmark_id: number | null; benchmark_code: string | null; benchmark_multiplier: string | null;
  benchmark_spread: string | null; opening_amount: string | null;
  current_value: string | null; profitability: null; valuation_status: string;
  valuation: { original_invested_amount: Numeric | null; outstanding_principal: Numeric | null;
    gross_accrued_value: Numeric | null; accrued_gain: Numeric | null;
    display_currency: string; display_value: Numeric | null; status: string;
    benchmark_start: string | null; benchmark_end: string | null } | null;
  movements: FixedIncomeMovement[]
}
export type FixedIncomeMovement = {
  id: number; lot_id: number; movement_type: string; amount: string;
  effective_date: string; currency: string; notes: string
}
export type BenchmarkObservations = {
  code: string; name: string; unit: string; frequency: string; count: number;
  earliest: string | null; latest: string | null;
  observations: { reference_date: string; value: string; unit: string; source: string }[]
}
export type FixedIncomeProduct = {
  instrument_id: number; symbol: string; name: string; default_currency: string;
  day_count_basis: string; compounding: string; business_day_calendar: string;
  benchmark_lag_months: number
}
export type Performance = { date: string; quote_date?: string | null; reporting_currency: string; status: string;
  quantity: Numeric | null; remaining_acquisition_cost: Numeric | null; average_cost: Numeric | null;
  market_value: Numeric | null; total_gain: Numeric | null; realized_gain: Numeric | null;
  unrealized_gain: Numeric | null; gross_income: Numeric | null;
  cumulative_return_pct: Numeric | null; daily_return_pct: Numeric | null }
export type Quote = { date: string; close: number; currency: string; dividends: number; stock_splits: number; source: string }
export type CorporateEvent = {
  id: number; event_type: 'STOCK_SPLIT' | 'REVERSE_SPLIT' | 'DIVIDEND' | 'JCP' | 'AMORTIZATION';
  effective_date: string; payment_date: string | null; amount_per_unit: Numeric | null;
  conversion_factor: Numeric | null; currency: string | null; source: string;
  origin: 'provider' | 'manual'; notes: string; eligible_quantity: Numeric;
  gross_amount: Numeric | null; net_amount: Numeric | null
}
export type Activity = ({ kind: 'TRANSACTION'; id: number; date: string; type: 'Buy' | 'Sell';
  quantity: Numeric; price: Numeric; currency: string; broker: string; allocation_class: string }
  | (CorporateEvent & { kind: 'CORPORATE_ACTION'; date: string }))
export async function api<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch('/api' + path, {
      method, headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body), signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error('Não foi possível conectar à API. Verifique se o backend está em execução.')
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    const message = Array.isArray(data.detail)
      ? data.detail.map((x: { loc: string[]; msg: string }) => x.loc.slice(1).join('.') + ': ' + x.msg).join('; ')
      : data.detail
    throw new Error(message || 'A operação não foi conclu?da.')
  }
  return response.status === 204 ? undefined as T : response.json()
}

export async function apiFile<T>(path: string, file: File): Promise<T> {
  let response: Response
  try {
    response = await fetch('/api' + path, {
      method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
    })
  } catch {
    throw new Error('Não foi possível conectar à API. Verifique se o backend está em execução.')
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    const message = Array.isArray(data.detail)
      ? data.detail.map((x: { loc: string[]; msg: string }) => x.loc.slice(1).join('.') + ': ' + x.msg).join('; ')
      : data.detail
    throw new Error(message || 'A operação não foi concluída.')
  }
  return response.json()
}
