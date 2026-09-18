export type Portfolio = { id: number; name: string }
export type Numeric = number | string
export type Transaction = {
  id: number; portfolio_id: number; trade_date: string; settlement_date: string;
  instrument_id: number;
  type: 'Buy' | 'Sell'; asset: string; broker: string; allocation_class: string;
  asset_currency: string; fx_rate: Numeric | null; quantity: Numeric;
  price: Numeric; brokerage_fee: Numeric; other_fees: Numeric; notes: string
}
export type InstrumentSearchResult = {
  instrument_id: number | null; symbol: string; name: string; asset_type: 'STOCK' | 'ETF' | 'CRYPTO' | 'OTHER';
  exchange: string | null; currency: string; status: 'ACTIVE' | 'INACTIVE' | 'DELISTED';
  provider: string | null; provider_symbol: string | null; provider_exchange?: string | null
}
export type ImportPreviewRow = {
  row: number; valid: boolean; data?: Omit<Transaction, 'id' | 'portfolio_id' | 'instrument_id'> & { instrument_id?: number | null };
  instrument_resolution?: 'resolved' | 'unresolved' | 'ambiguous' | 'not_requested';
  errors: { field: string; message: string }[]
}
export type ImportPreview = {
  digest: string; filename: string; valid: boolean; already_imported: boolean;
  rows: ImportPreviewRow[]
}
export type Position = {
  asset_id: number | null;
  asset: string; broker: string; allocation_class: string; asset_currency: string; quantity: number;
  average_cost: number; current_price: number | null; total_value: number | null;
  current_total_gain: number | null; current_accumulated_profitability: number | null;
  price_date: string | null; gain_date: string | null; history_behind_transactions: boolean
}
export type Asset = { id: number; ticker: string; asset_currency: string; quantity: number; average_cost: number;
  current_price: number | null; total_value: number | null; price_date: string | null }
export type Overview = { positions: Position[]; assets: Asset[];
  summary: { transactions: number; positions: number; assets: number; priced_value: number | null;
    total_value: number | null; missing_prices: string[]; currencies: string[];
    totals_by_currency: Record<string, number> }; methodology: string }
export type Performance = { date: string; total_gain: number; realized_gain: number;
  unrealized_gain: number; accumulated_profitability_pct: number | null; daily_profitability_pct: number }
export type Quote = { date: string; close: number; dividends: number; stock_splits: number; source: string }
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
