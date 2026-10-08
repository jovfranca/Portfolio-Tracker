export type Portfolio = { id: number; household_id: number; name: string; display_currency: string; dirty_from: string | null; history_built_through: string | null }
export type Role = 'OWNER' | 'EDITOR' | 'VIEWER'
export type Space = { id: number; name: string; role: Role; member_count: number; portfolio_count: number; status: 'ACTIVE' }
export type AuthState = { user: { id: number; display_name: string;
  identities: { provider: string; email: string | null; email_verified: boolean }[] }; households: Space[] }
export type AuthConfig = { google_client_id: string | null; google_nonce: string | null; dev_enabled: boolean }
export type Member = { id: number; user_id: number; display_name: string; role: Role }
export type Invitation = { id: number; email: string; role: Role; expires_at: string }
export type InvitationPreview = Invitation & { space: { id: number; name: string };
  inviter: { id: number; display_name: string } | null; created_at: string; resolved_at: string | null;
  status: 'PENDING' | 'ACCEPTED' | 'REJECTED' | 'REVOKED' | 'EXPIRED' }
export type Numeric = number | string
export type PeriodAnalytics = { return_pct: Numeric | null; net_contributions: Numeric | null;
  annualized_return_pct?: Numeric | null;
  return_series?: { date: string; return_pct: Numeric | null }[];
  benchmarks?: { code: string; status: string; return_pct: Numeric | null; annualized_return_pct: Numeric | null;
    series: { date: string; return_pct: Numeric | null }[] }[];
  monetary_result: Numeric | null; reporting_currency: string; status: string;
  start_date: string | null; end_date: string | null; coverage_start: string | null; coverage_end: string | null }
export type FxCoverage = { portfolio_id: number; reporting_currency: string; as_of: string;
  fallback_days: number; status: string; requirements_status: string; unknown_requirements: string[];
  last_successful_sync_at: string | null; sync_tracking: string;
  pairs: { currency: string; base_currency: string; status: string; required_rate_type: string;
    required_start: string; required_end: string; required_count: number; covered_count: number;
    missing_dates: string[]; available_start: string | null; available_end: string | null;
    sources: string[]; last_observation_retrieved_at: string | null;
    requirements: { date: string; reference_date: string | null; fallback_used: boolean; reasons: string[] }[];
    history: { reference_date: string; rate_type: string; side: string; rate: Numeric; source: string; retrieved_at: string | null }[] }[] }
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
  origin?: string; aliases?: string[];
  id: number; symbol: string; name: string; asset_type: string; exchange: string | null;
  currency: string | null; status: string; mappings: Array<{ provider: string; provider_symbol: string;
    quote_currency: string; is_primary: boolean; active: boolean }>
}
export type ImportPreviewRow = {
  raw?: Record<string, string>;
  row: number; valid: boolean; data?: Omit<Transaction, 'id' | 'portfolio_id' | 'instrument_id' | 'transaction_currency_locked'> & { instrument_id?: number | null };
  instrument_resolution?: 'resolved' | 'unresolved' | 'ambiguous' | 'not_requested';
  errors: { field: string; message: string }[]
}
export type ImportPreview = {
  digest: string; filename: string; valid: boolean; already_imported: boolean;
  rows: ImportPreviewRow[]
}
export type Position = {
  instrument_id: number;
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
    acquisition_cost: Numeric | null; total_gain: Numeric | null;
    total_value: number | null; missing_prices: string[]; missing_fx: string[]; missing_cost_fx: string[]; missing_actions?: string[]; display_currency: string; currencies: string[];
    totals_by_currency: Record<string, number>; income_by_currency: Record<string, Numeric>;
    history_status: string; dirty_from: string | null; history_built_through: string | null; gross_income: Numeric | null }; methodology: string }
export type FixedIncomeLot = {
  instrument_id: number; asset_id: number; day_count_basis: string; compounding: string;
  business_day_calendar: string; benchmark_lag_months: number; notes: string; status: string;
  id: number; instrument_symbol: string; instrument_name: string; product_type: string;
  issuer: string; broker: string; currency: string; start_date: string; maturity_date: string | null;
  yield_structure: 'FIXED_RATE' | 'BENCHMARK_MULTIPLE' | 'BENCHMARK_SPREAD';
  fixed_rate: string | null; benchmark_id: number | null; benchmark_code: string | null; benchmark_multiplier: string | null;
  benchmark_spread: string | null; opening_amount: string | null;
  current_value: string | null; profitability: null; valuation_status: string;
  valuation: { original_invested_amount: Numeric | null; outstanding_principal: Numeric | null;
    gross_accrued_value: Numeric | null; accrued_gain: Numeric | null;
    display_principal: Numeric | null; display_accrued_gain: Numeric | null; realized_gain: Numeric | null; display_realized_gain: Numeric | null;
    display_currency: string; display_value: Numeric | null; status: string;
    benchmark_start: string | null; benchmark_end: string | null;
    pending?: boolean; unbuilt?: boolean; consolidated_through?: string | null } | null;
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
  net_flow?: Numeric | null;
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
let householdId: number | null = null
export function selectHousehold(id: number | null) { householdId = id }
function requestHeaders(contentType?: string) {
  const headers: Record<string, string> = { 'X-Aurion-Request': '1' }
  if (contentType) headers['Content-Type'] = contentType
  if (householdId !== null) headers['X-Household-ID'] = String(householdId)
  return headers
}
export class AuthenticationRequired extends Error {}
function checkAuthentication(response: Response, path: string) {
  if (response.status === 401) {
    if (path === '/auth/me' || !path.startsWith('/auth/')) window.dispatchEvent(new Event('quintrion-session-expired'))
    throw new AuthenticationRequired('Sua sessão expirou. Entre novamente.')
  }
}
export async function api<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch('/api' + path, {
      method, credentials: 'include', headers: requestHeaders(body === undefined ? undefined : 'application/json'),
      body: body === undefined ? undefined : JSON.stringify(body), signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error('Não foi possível conectar à API. Verifique se o backend está em execução.')
  }
  if (!response.ok) {
    checkAuthentication(response, path)
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
      method: 'POST', credentials: 'include', headers: requestHeaders('application/octet-stream'), body: file,
    })
  } catch {
    throw new Error('Não foi possível conectar à API. Verifique se o backend está em execução.')
  }
  if (!response.ok) {
    checkAuthentication(response, path)
    const data = await response.json().catch(() => ({}))
    const message = Array.isArray(data.detail)
      ? data.detail.map((x: { loc: string[]; msg: string }) => x.loc.slice(1).join('.') + ': ' + x.msg).join('; ')
      : data.detail
    throw new Error(message || 'A operação não foi concluída.')
  }
  return response.json()
}
