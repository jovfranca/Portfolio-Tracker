export type Portfolio = { id: number; name: string; display_currency: string }
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
  instrument_id: number | null; symbol: string; name: string; asset_type: 'STOCK' | 'ETF' | 'CRYPTO' | 'OTHER';
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
  native_currency: string | null;
  asset_id: number | null;
  asset: string; broker: string; allocation_class: string; transaction_currency: string; quantity: number;
  average_cost: number; acquisition_cost: number; current_price: number | null; total_value: number | null;
  display_average_cost: number | null; display_acquisition_cost: number | null;
  display_currency: string; display_price: number | null; display_value: number | null;
  broker_breakdown: { broker: string; quantity: number; average_cost: number; acquisition_cost: number }[];
  current_total_gain: number | null; current_accumulated_profitability: number | null;
  price_date: string | null; gain_date: string | null; history_behind_transactions: boolean;
  income_by_currency: Record<string, Numeric>; corporate_action_count: number
}
export type Asset = { id: number; ticker: string; transaction_currency: string; quantity: number; average_cost: number;
  current_price: number | null; total_value: number | null; price_date: string | null;
  income_by_currency: Record<string, Numeric>; corporate_action_count: number }
export type Overview = { positions: Position[]; assets: Asset[];
  summary: { transactions: number; positions: number; assets: number; priced_value: number | null;
    total_value: number | null; missing_prices: string[]; missing_fx: string[]; missing_cost_fx: string[]; display_currency: string; currencies: string[];
    totals_by_currency: Record<string, number>; income_by_currency: Record<string, Numeric> }; methodology: string }
export type Performance = { date: string; total_gain: number; realized_gain: number;
  unrealized_gain: number; accumulated_profitability_pct: number | null; daily_profitability_pct: number }
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
