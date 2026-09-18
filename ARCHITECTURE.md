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
Search includes local aliases and provider identifiers. Provider results with
missing metadata remain selectable; the user confirms the canonical symbol and
quote currency explicitly. The same selector supports manual transaction entry
and unresolved import rows. Import resolution validates a row without saving a
transaction; confirmation saves the original identifier as an import alias.

`ProviderInstrument` owns the configured provider's symbol, quote currency,
provider exchange, and active flag. Multiple mappings may coexist for one
canonical instrument. Provider-backed prices are shared by this concrete mapping,
not merely by canonical instrument and currency.
Inactive mappings are excluded from network retrieval, while stored observations
and cached quotes remain readable in the instrument's currency. Historical values
from other currencies are never merged into that series.
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
Migration `0008` backfills transaction instrument foreign keys, aliases and the
existing provider-compatible mapping, then re-keys market prices, coverage and
latest quotes without copying observations. It also changes portfolio asset
uniqueness from ticker text to canonical instrument identity.
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
- Until quote-currency routing is implemented, transaction currency must match
  the instrument's quote currency. A mismatch is rejected rather than valued
  using a price denominated in a different currency.
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
