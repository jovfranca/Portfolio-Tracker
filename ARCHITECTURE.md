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
- `src/import_legacy.py` is the one-way compatibility path from original pickle data.
- `frontend/src/` contains the React interface and API client.

Keep these boundaries direct. Add a new layer only when repeated code or a tested
use case requires it.

## Data ownership

PostgreSQL is the active persistence layer. Transactions are authoritative.
Positions are read models rebuilt from ordered transactions and are never stored
as mutable balances. Asset quotes are stored separately and keyed by asset and date.
Historical FX and PTAX rates are global, insert-only records keyed by currency,
rate type, and reference date, so every portfolio can reuse the same audited value.
Alembic migrations are the only supported way to change the database schema.

The files under `src/db/` are legacy migration sources, not active persistence.
The code under `src/archive/old_models/` is retained only for historical comparison
while legacy calculations and imported records are being reconciled.

## Current invariants and limits

- The application is intended for one trusted user on a local machine.
- API writes are protected against unexpected browser origins, but there is no login.
- Tickers are normalized to uppercase at the API boundary.
- A position is grouped by ticker, broker, and allocation class.
- Manual quotes take precedence over provider refreshes for the same date.
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
