# Portfolio Tracker

Local portfolio tracking application with a React interface, FastAPI backend,
and PostgreSQL database. Transactions are the source of truth; positions and
performance views are calculated from them.

## Current features

- Create and rename portfolios.
- Create, edit, and delete buy/sell transactions.
- Rebuild positions by asset, broker, and allocation class.
- Reuse shared daily Yahoo Finance history, cache latest quotes for 15 minutes,
  and keep manual portfolio prices private.
- View the legacy gain calculation as a table and chart.
- Import the original transaction and quote pickle files through a local CLI.

## Run locally

Follow [docs/setup.md](docs/setup.md) for a fresh installation. On the prepared
Windows development environment:

```powershell
.\scripts\start-local.ps1 -SkipBuild
```

Open <http://127.0.0.1:8000>. FastAPI documentation is available at
<http://127.0.0.1:8000/docs>.

Docker is also supported:

```powershell
docker compose up --build
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run build
```

Database integration and browser-test commands are documented in
[docs/setup.md](docs/setup.md).

## Calculation limits

The current release intentionally preserves the original formulas:

- Fees, dividends, and stock splits are stored but do not affect calculations.
- Values from different currencies are not converted before aggregation.
- “Daily profitability” is the percentage change in gain, not a time-weighted return.
- Values use floating-point arithmetic.
- Short sales and overselling do not have a defined business rule yet.

Use the application as a personal local tracker, not as tax or investment advice.
See [ARCHITECTURE.md](ARCHITECTURE.md) for code boundaries and
[docs/requisitos-arquitetura-roadmap.md](docs/requisitos-arquitetura-roadmap.md)
for proposed future product scope.
