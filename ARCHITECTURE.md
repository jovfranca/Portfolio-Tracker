# Architecture

## Runtime

The application is a small web monolith:

```text
React browser UI → FastAPI routes → SQLAlchemy → PostgreSQL
                                ↘ pure portfolio calculations
                                ↘ yfinance / Banco Central market-data adapters
Legacy import CLI → restricted pickle readers → SQLAlchemy
```

FastAPI serves the compiled React application when `frontend/dist` exists. In
development, Vite serves React and proxies `/api` to FastAPI.

## Responsibilities

- `src/main.py` assembles middleware, error handlers, routes, and static files.
- `src/api/routes.py` defines the HTTP contract and transaction boundaries.
- `src/services.py` contains shared database lookups and overview loading.
- `src/domain.py` contains pure position and performance calculations.
- `src/models/` contains SQLAlchemy persistence models.
- `src/database.py` owns the SQLAlchemy registry, engine, and sessions.
- `src/config.py` reads environment-backed configuration.
- `src/api/market_data.py` is the external quote-provider adapter.
- `src/market_prices.py` resolves private overrides, shared stored prices, and
  provider fallback without exposing providers to portfolio calculations.
- `src/instruments.py` resolves raw identifiers to canonical instruments and
  owns alias/provider-mapping orchestration. Provider discovery itself remains
  in `src/api/market_data.py`.
- `src/import_legacy.py` is the one-way compatibility path from original pickle data.
- `frontend/src/` contains the React interface and API client.

Keep these boundaries direct. Add a new layer only when repeated code or a tested
use case requires it.

## Data ownership

PostgreSQL is the active persistence layer. Transactions are authoritative.
Positions are read models rebuilt from ordered transactions and are never stored
as mutable balances. `Instrument.id` is the provider-independent holding identity;
transactions and portfolio assets reference it directly. `Asset.ticker` and
`Transaction.asset` remain compatibility/display and raw-input fields and are not
used for joins. Assets are unique per portfolio and canonical instrument.
Position responses expose `asset_id` so frontend performance lookup does not
reintroduce ticker equality. Once remaining display consumers use instrument
metadata, `Asset.ticker` can be removed in a later migration; the raw transaction
identifier can remain for import auditability.

`InstrumentAlias` stores normalized manual/import/provider identifiers. An alias
may point to more than one instrument, in which case resolution is explicitly
ambiguous. Unknown identifiers remain unresolved until the user selects a provider
search result or explicitly creates a manual instrument. Canonical symbols are not
assumed to be globally unique. Inactive and delisted instruments, their aliases,
transactions, and historical prices remain persisted.
Search includes local aliases and provider identifiers, with All/Stocks/ETFs/Crypto/
Other categories and visible type, market, currency and status metadata. Known
provider mappings reconcile to local identities. New crypto pairs suggest association
with the existing canonical base symbol and type; ambiguous identities require selection.
The confirmed crypto base symbol plus CRYPTO type is unique in the MVP, including
concurrent writes. Listed-security symbols remain non-unique across exchanges.
Provider results with missing currency remain explicitly unknown and never inherit
the transaction form currency. Before saving a mapping, the user enters/verifies
its quote currency and explicitly confirms it. Listed-security native and quote
currency conflicts are rejected. The same selector supports manual transaction entry
and unresolved import rows. Import resolution validates a row without saving a
transaction; confirmation saves the original identifier as an import alias.

`Instrument.currency` is nullable and means **native/listing currency**, not a
universal currency for owning or pricing the asset. Known stocks/ETFs have a fixed
native currency. New CRYPTO and manual OTHER instruments have no native currency.
`Transaction.asset_currency` is the currency of the entered transaction price;
historical prices and FX rates are never reconstructed from provider quotes.
One portfolio/instrument uses one transaction currency after its first transaction,
including edits and imports. This is an accounting restriction preserving the
existing formulas, not a component of canonical identity. Different portfolios
may account for the same crypto instrument in different currencies.

`ProviderInstrument.quote_currency` owns the configured provider's quote currency,
alongside its symbol,
provider exchange, and active flag. Multiple mappings may coexist for one
canonical instrument. Provider-backed prices are shared by this concrete mapping,
not merely by canonical instrument and currency.
Inactive mappings are excluded from network retrieval, while stored observations
and cached quotes remain readable in the portfolio's transaction currency. Historical values
from other currencies are never merged into that series.
Network retrieval requires an active mapping for the configured provider and the
requested accounting currency. Multiple matching mappings are explicitly ambiguous;
their cached/shared observations are not chosen arbitrarily either. A unique inactive
mapping remains readable when no active mapping is available. There is no primary
selection or provider failover. Without a compatible mapping,
automatic data is unavailable and stored/manual prices remain available. No path
falls back to fetching `Instrument.symbol`. A manual instrument needs no delisting
status to disable retrieval. Canonical BTC can own BTC-USD and BTC-EUR mappings;
neither quote is used directly in a BRL position. Cross-currency quote conversion
using the existing FX store is deferred.
Successful range queries are recorded separately so weekends and exchange holidays
are known gaps, not repeatedly downloaded missing data. Latest quotes are retained
once per provider mapping with a configurable TTL. Manual prices remain private
through their portfolio asset and override shared prices for the applicable date.
Migration `0006` preserves all pre-existing observations in the private price
table, including zero values and each original source. Older Yahoo history used
adjusted prices and may differ between portfolios; it is not deduplicated into
the new shared dataset. Missing original retrieval timestamps remain null, and
no provider range coverage is inferred from these observations. Downgrading
restores their original ownership and sources.
Migration `0007` stores the latest quote's exchange calendar date separately from
its timestamp, since PostgreSQL does not retain the timestamp's original timezone.
Older cache entries without this date are refreshed; offline fallback uses UTC.
Migration `0008` backfills transaction instrument foreign keys, aliases and legacy
provider mappings, then re-keys market prices, coverage and
latest quotes without copying observations. It also changes portfolio asset
uniqueness from ticker text to canonical instrument identity.
Its original legacy Yahoo mappings are retained for compatibility; these are not
proof that a provider currently supports an instrument. New unknown identifiers
require explicit selection. Existing legacy currency values are retained without
classifying unknown asset types. Manual prices, transactions and FX/PTAX observations
are preserved. Applied migration `0008` is immutable. Migration `0009` renames the
provider currency to `quote_currency`, permits null native currencies, and enforces
unique crypto base symbols. Existing installations must run `alembic upgrade head`.
Replacing an inactive mapping preserves its stored observations in the same quote
currency; the active mapping supplies new requests and wins overlapping daily bars.
Downgrade supports pre-upgrade data, but fails transactionally if new nullable
currencies or multiple quote mappings cannot satisfy the old schema; it does not
invent currency values or discard observations to force a downgrade.
Historical FX and PTAX rates are global, insert-only records keyed by currency,
rate type, and reference date, so every portfolio can reuse the same audited value.
Alembic migrations are the only supported way to change the database schema.

The files under `src/db/` are legacy migration sources, not active persistence.
The code under `src/archive/old_models/` is retained only for historical comparison
while legacy calculations and imported records are being reconciled.

## Current invariants and limits

- The application is intended for one trusted user on a local machine.
- API writes are protected against unexpected browser origins, but there is no login.
- Raw identifiers are normalized to uppercase at the API boundary and resolved
  locally before persistence; provider search is on demand and requires selection.
- A position is grouped by canonical instrument, broker, and allocation class.
- Known listed stock/ETF native currency fixes the transaction currency. Crypto
  and manual OTHER assets allow the initial transaction currency to be selected.
  Automatic quotes must match that accounting currency; otherwise use manual prices.
- Manual quotes take precedence over provider prices for the same asset and date.
- Currency rates express BRL per unit of the named currency. Exact cached dates are
  used first; weekends and provider holidays fall back to the latest rate within
  `RATE_FALLBACK_DAYS`. FX and PTAX histories remain separate. PTAX closing buy and
  sell observations are both stored; choosing which one applies is a tax or business
  rule and does not happen in the storage or provider layer.
- Financial formulas retain legacy behavior; changes require regression tests and a
  separate, clearly identified behavior change.
- Applying currency conversion to portfolio calculations, corporate-action
  processing, decimal accounting outside the rate store, short-sale
  rules, and tax calculations are outside the current implementation.
