export type Portfolio = { id: number; name: string }
export type Transaction = {
  id: number; portfolio_id: number; date_time: string; type: 'Buy' | 'Sell';
  asset: string; broker: string; allocation_class: string; quantity: number;
  price: number; brokerage_fee: number; other_fees: number; notes: string
}
export type Position = {
  asset: string; broker: string; allocation_class: string; quantity: number;
  average_cost: number; current_price: number | null; total_value: number | null;
  current_total_gain: number | null; current_accumulated_profitability: number | null;
  price_date: string | null; gain_date: string | null; history_behind_transactions: boolean
}
export type Asset = { id: number; ticker: string; quantity: number; average_cost: number;
  current_price: number | null; total_value: number | null; price_date: string | null }
export type Overview = { positions: Position[]; assets: Asset[];
  summary: { transactions: number; positions: number; assets: number; priced_value: number;
    total_value: number | null; missing_prices: string[] }; methodology: string }
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
