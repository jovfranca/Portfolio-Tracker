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

`InstrumentAlias` stores normalized catalog/manual/import/provider identifiers. An alias
may point to more than one instrument, in which case resolution is explicitly
ambiguous. Unknown import identifiers remain unresolved until the user explicitly
selects a catalog instrument or creates a manual instrument. Canonical symbols are not
assumed to be globally unique. Inactive and delisted instruments, their aliases,
transactions, and historical prices remain persisted.
Ordinary transaction search only returns `CATALOG` instruments of supported MVP
types (STOCK, ETF, and CRYPTO). Provider search remains isolated in the provider
adapter for future catalog-maintenance tooling; its results are not promoted by
ordinary users. The selector sends `instrument_id`, and users never edit canonical
or provider metadata. A separate custom flow creates a `CUSTOM` instrument without
a provider mapping, so its prices are manual. In the current single-user MVP custom
instruments are global rows; user ownership must be introduced before multi-user use.
Import confirmation can save a raw identifier as an alias. Unknown imports never
create instruments or provider mappings implicitly.

`Instrument.currency` is nullable and means **native/listing currency**, not a
universal currency for owning or pricing the asset. Known stocks/ETFs have a fixed
native currency. CRYPTO has no native currency. For a CUSTOM/OTHER instrument the
field is the explicit manual-pricing default entered by the user, not an exchange fact.
`Transaction.transaction_currency` is the currency of the entered transaction price;
historical prices and FX rates are never reconstructed from provider quotes.
Stocks and ETFs use their canonical native currency, while crypto may use a
different transaction currency per operation. Values in different transaction
currencies remain separate; this is not a component of canonical identity.

`ProviderInstrument.quote_currency` owns the configured provider's quote currency,
alongside its symbol, provider exchange, active flag, and `is_primary` preference.
Multiple mappings may coexist for one
canonical instrument. Provider-backed prices are shared by this concrete mapping,
not merely by canonical instrument and currency.
Inactive mappings are excluded from network retrieval, while stored observations
and cached quotes remain attached to their original mapping and currency. Network
retrieval uses the single active primary mapping for the configured provider; it
never selects a mapping from `Transaction.transaction_currency`. A unique legacy mapping
is a compatibility fallback, while multiple mappings without a primary fail closed.
There is no provider failover. Without a mapping, automatic data is unavailable and
stored/manual prices remain available. No path
falls back to fetching `Instrument.symbol`. A manual instrument needs no delisting
status to disable retrieval. Canonical BTC owns BTC-USD (primary), BTC-BRL, and
BTC-EUR in the MVP catalog. A BRL BTC transaction is valid and retrieval still uses
BTC-USD, storing USD observations. `rates.convert_amount` provides a separate
quote/display conversion boundary through the FX store. Portfolio calculations do
not yet apply that conversion automatically, so they do not mix a USD provider price
into a BRL position.
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
Its original broad Yahoo backfill is corrected by migration `0010`; these guessed
mappings are not proof that a provider supports an instrument. Existing legacy currency values are retained without
classifying unknown asset types. Manual prices, transactions and FX/PTAX observations
are preserved. Applied migration `0008` is immutable. Migration `0009` renames the
provider currency to `quote_currency`, permits null native currencies, and enforces
unique crypto base symbols. Existing installations must run `alembic upgrade head`.
Migration `0010` adds catalog origin and primary mapping state. It deletes only
unreferenced speculative mappings created by the broad 0008 backfill, and retains
mapping rows that own prices, coverage, or cached quotes as inactive historical
owners. The catalog loader may reactivate a matching retained mapping after
validating ownership.
Replacing an inactive mapping preserves its stored observations in the same quote
currency; the active mapping supplies new requests and wins overlapping daily bars.
Downgrade supports pre-upgrade data, but fails transactionally if new nullable
currencies or multiple quote mappings cannot satisfy the old schema; it does not
invent currency values or discard observations to force a downgrade.
Historical FX and PTAX rates are global, insert-only records keyed by currency,
rate type, and reference date, so every portfolio can reuse the same audited value.
Alembic migrations are the only supported way to change the database schema.

## MVP instrument catalog

`data/instruments.csv` is the version-controlled source for trusted canonical
metadata, aliases, provider symbols, quote currencies, and primary selection.
`python -m src.instrument_catalog` validates the whole file before applying it,
updates migrated rows such as malformed legacy ARKX in place, is idempotent, and
fails if a provider identity already belongs to a different canonical instrument.
Loading uses a savepoint: conflicts roll back the entire seed, including metadata
and primary flags. Provider-symbol ownership is checked across quote currencies.
Known conflicting legacy listing metadata requires explicit review instead of
relabeling a holding by ticker alone. Replaced mappings are retired, not deleted,
so their observations remain readable.
Untouched migration placeholders (OTHER, empty name/exchange, migration-only
aliases) may have inherited transaction currency from the pre-canonical model;
the catalog supplies their native currency without changing transaction data.
A migrated crypto provider-market label may be cleared from canonical exchange
only when the matching provider mapping retains that same label.
The legacy `POST /api/instruments` endpoint returns 410; only the catalog loader
may register provider mappings. Custom creation is separate and repeat requests
reuse an identical custom identity. Transaction/import selections cannot attach
an alias already associated with another instrument.
The quote-history API displays the primary quote's original currency and keeps
manual overrides. Accounting/performance inputs remain currency-filtered; raw
foreign quotes are not silently treated as transaction-currency prices.
Local startup and Docker seed after migrations. The catalog page is read-only;
editable administration, authentication, audit history, and safe activation are
future work.

Currency roles are deliberately independent:

- transaction currency describes the recorded unit price and saved transaction FX;
- native/listing currency is canonical descriptive metadata;
- provider quote currency belongs to one provider mapping and its observations;
- portfolio display currency is a future preference and uses FX conversion.

Changing display currency must never rewrite `Transaction.transaction_currency` or
`Transaction.fx_rate`.

The files under `src/db/` are legacy migration sources, not active persistence.
The code under `src/archive/old_models/` is retained only for historical comparison
while legacy calculations and imported records are being reconciled.

## Current invariants and limits

- The application is intended for one trusted user on a local machine.
- API writes are protected against unexpected browser origins, but there is no login.
- Raw identifiers are normalized to uppercase at the API boundary and resolved
  locally against catalog aliases, canonical identities, and known mappings.
- A position is grouped by canonical instrument, broker, and allocation class.
- Transaction currency may differ from native currency and provider quote currency.
  One portfolio/instrument still uses one accounting currency after its first
  transaction because current formulas do not combine mixed transaction currencies.
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
