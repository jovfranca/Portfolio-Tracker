# Issue #12 review

Reviewed the working tree on `feat/12-positions-consolidation` against local
`develop` and [issue #12](https://github.com/jovfranca/Portfolio-Tracker/issues/12).
At review time HEAD had no commits ahead of develop; the implementation was in
uncommitted changes. This is still a partial implementation of the issue.

## Verified defects fixed

- Purchase fees were omitted from remaining cost, including converted cost;
  sale fees were omitted from realized gains. Both now participate in current,
  historical and corporate-event cost calculations. For a purchase of 10 at 20
  with 10 in fees, followed by selling 4 at 30 with 4 in fees, remaining cost is
  126, realized gain is 32, and unrealized gain at 30 is 54.
- Current gains used only activity before the last quote. Selling after that
  quote left realized gains stale, and liquidations without quotes lost their
  results. Current gains now use all transactions; a closed holding needs no
  quote to preserve realized gain and zero unrealized gain.
- Every overview rebuilt complete historical gain series for every broker.
  Current valuation now calculates directly from transaction/event state.
- A future settlement with explicit transaction FX could break overview when
  reporting in a third currency. Missing future reporting FX now leaves cost
  conversion incomplete instead of raising a date error.
- The holdings table made native values primary, duplicated same-currency
  values, and exposed fiat secondary values for crypto. Available converted
  price/cost/value are now primary with conditional native secondary values.
- Closed positions were always visible. They are now hidden by default with a
  toggle, while remaining available in the data and performance selector.
- An unsaved currency draft could follow the user to another portfolio sharing
  the same saved currency. Switching portfolios now resets the draft.
- The new database test compared differently scaled decimal strings returned
  before and after persistence. It now compares the complete persisted
  transaction list before and after changing reporting currency.

## Outstanding acceptance blockers

These requirements are not implemented by the reviewed branch or the fixes above.
Do not close issue #12 based on this change.

1. **P1 — Position identity still includes transaction currency.**
   `overview` groups by `(instrument_id, transaction_currency)` and `/performance`
   requires a transaction currency. A BTC purchase in BRL and sale in USD are
   accounted in separate holdings instead of reducing one lifetime position.
   This needs conversion of transaction cost/proceeds into a shared accounting
   basis while retaining original currencies and explicit missing-FX status.
2. **P1 — Performance is not time weighted.**
   `historical_profitability` and `consolidated_profitability` divide gain by
   cumulative purchases and compare gains between dates. Buying 10 at 10, marking
   at 11, then buying another 10 at 11 while the quote stays 11 drops cumulative
   performance from 10% to about 4.76%, despite no investment loss. Daily
   cash-flow-adjusted returns and linking across liquidation/reopening are absent.
3. **P1 — Reporting currency does not cover P&L, income or historical series.**
   `get_overview` converts acquisition cost and current valuation only;
   `/performance` does not use portfolio reporting currency at all. Changing BRL
   to EUR leaves gains and return percentages unchanged. Historical transaction,
   event and valuation FX must be applied on their relevant dates, with incomplete
   status when unavailable, rather than converting accumulated P&L at one rate.
4. **P1 — Total investment P&L excludes gross income.**
   Income is retained in `income_by_currency`, but total gain remains realized
   plus unrealized trading gain. Ten units receiving a dividend of 1 with no price
   change still show zero total gain. Gross income must enter investment P&L and
   daily return after appropriate dated conversion; tax/net fields must remain
   distinct and unknown values must not be invented.
5. **P1 — Daily position/portfolio history and incremental consolidation are absent.**
   The performance endpoint returns rows only for available quote dates and
   lacks quantity, remaining cost, market value, reporting currency and calculation
   status. There is no portfolio series, `dirty_from`, consolidation endpoint/action,
   or invalidation for edited transactions, events, historical prices and FX.
   Current repricing is cheaper after this review, but that does not implement the
   required historical lifecycle.

Legacy oversell behavior also remains inconsistent between current and historical
calculations (current holdings clamp at zero while history permits negatives).
It is already characterized in `test_oversell_behavior_is_characterized`; a shared
position ledger must address this when implementing canonical consolidation.

Regression coverage added for fees, stale/missing quotes after liquidation,
current valuation without history reconstruction, future settlement FX, primary
currency rendering, crypto secondary values, closed positions, and currency drafts.

## Validation

- Default pytest run: 173 passed, 28 database tests skipped.
- Full pytest run against a newly created, migrated, isolated PostgreSQL test
  database: 201 passed. Two pre-existing dependency deprecation warnings remain.
- `alembic check`: no new upgrade operations detected.
- `npm run build`: passed.
- Full Playwright suite against the isolated test server: 10 passed.
- `git diff --check`: passed.

The full database/browser runs required execution outside the Windows sandbox
because it prevented PostgreSQL/browser process creation and pytest temporary-file
access. No production or personal portfolio database was migrated or reset.
