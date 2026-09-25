# Issue #12 implementation review

The committed branch `feat/12-positions-consolidation` was compared with `develop`, [issue #12](https://github.com/jovfranca/Portfolio-Tracker/issues/12), and the earlier review in this file. The five acceptance blockers from that review are implemented in the current working tree.

## Position and reporting model

- A position is identified by `(portfolio_id, instrument_id)`. Transactions retain their original currency and frozen transaction FX. A sale in another currency reduces the same broker's holding and the same lifetime instrument position. Missing conversion yields an incomplete result; it never creates a second position or mixes currencies.
- `src/domain.py` contains the shared pure ledger for current state and daily history. It uses broker-level weighted-average cost, includes buy fees in cost, subtracts sale fees from proceeds, preserves realized P&L after liquidation, and rejects oversells. Splits change quantity without changing cost; dividends and JCP add gross income without changing cost.
- Current and historical P&L are in the portfolio reporting currency. A trade uses its frozen FX to BRL and dated BRL-to-reporting FX where needed. Quotes and income use dated FX. The reporting view never edits transactions, prices, events, or rates.
- The API exposes reporting price, market value, cost, realized and unrealized P&L, gross income, and total P&L. Native fiat values are secondary only when the canonical instrument has a meaningful native currency different from the portfolio's display currency. Crypto has no artificial fiat secondary display.

## Daily return convention

Splits and income events precede trades on their effective date; all take effect before the daily close. The daily cash-flow-adjusted return uses the previous close as the opening value, purchases as positive external flows, and net sale proceeds as negative external flows. Gross income is internal investment return. For end value `V`, previous value `P`, net external flow `F`, gross purchases including fees `B`, and day's gross income `I`:

```text
r = (V + I - P - F) / (P + B)
```

Daily returns are chain-linked. This convention makes same-day contributions deterministic with daily-close data; intraday valuation is outside issue #12. A quote on its date is used directly. The prior close may carry over a weekend. A missing weekday close is explicitly incomplete; no market price is fabricated. Missing required FX also makes the affected result incomplete. A correction to the missing source data marks the history dirty for recomputation.

## Derived history and consolidation

Migration `0014` adds `dirty_from`, `history_built_through`, daily position snapshots, and daily portfolio snapshots. Snapshots retain quantity, cost, value, realized/unrealized P&L, gross income, total P&L, return and status. They are derived state. The source transactions, events, prices, and FX remain authoritative.

The `POST /api/portfolios/{id}/consolidate` action resolves a latest quote for each open position through the existing Market Price service. Fresh cached quotes honor the existing TTL. An unavailable asset is reported while the remaining assets continue. The action updates historical snapshots from `dirty_from` forward. It carries the prior ledger state from the previous snapshot and leaves earlier snapshot rows intact. Transaction, event, historical price, and relevant FX changes move `dirty_from` back to the earliest affected date. A latest-quote refresh updates current valuation without rebuilding previous snapshots.

Deleting or moving the first transaction removes snapshots before the new first transaction date. Native values are converted into the instrument's native currency when a provider quote uses a different currency. A later valid quote does not hide an earlier missing observation that still prevents a valid cumulative return.

`GET /api/portfolios/{id}/performance?asset_id=...` returns the canonical position's daily reporting series. `GET /api/portfolios/{id}/history` returns the daily portfolio series. The UI accepts three-letter reporting currencies with BRL/USD/EUR suggestions, and offers an explicit consolidation action and pending status. Its positions list hides closed holdings by default and omits the broker column; broker breakdown remains in the API result.

The stored Corporate Actions model provides gross amounts. It has no authoritative withholding or net-income fields, so the reporting result does not invent them. Investor-level tax calculations and intraday time weighting remain outside issue #12.

## Follow-up review fixes

Reviewed the working tree as well as committed changes against `develop` and the current issue #12 acceptance criteria. Regression cases reproduced these meaningful problems before the fixes:

- **High: same-day sales erased percentage gains.** A purchase for 100 followed by full sale for 120 returned 0% because net flow removed the entire denominator. Position and portfolio returns now use gross purchases in the denominator. Migration `0015` persists this input and invalidates existing derived histories for rebuilding.
- **High: weekend splits inflated historical value.** A 2:1 split could double quantity while carrying the pre-split close forward. Such prices now remain unavailable until a matching quote exists; the split boundary survives incremental snapshot replay.
- **High: FX corrections left income and manual valuations stale.** Invalidation now includes currencies used only by shared income events, private income events, or manual prices.
- **High: settlement FX corrections started recalculation too late.** When reporting FX is used at settlement but acquisition cost enters history on the earlier trade date, invalidation now rewinds to that trade date.
- **Medium: reporting-currency UI omitted EUR and other currencies.** The control now accepts the same three-letter codes as the API, with BRL, USD and EUR suggestions.

The daily convention remains an approximation based on closing prices and assumes gross purchases enter the day's capital base; exact intraday time weighting is not inferred from daily observations.

## Validation

Regression tests cover cross-currency position identity and sales, missing FX, current BRL quotes from USD, native values from a different quote currency, historical BRL versus USD P&L and return, dividend income, additional purchases, partial/full sales and reopening, splits, oversell rejection, source-record immutability, dirty-date invalidation, deletion of the first trade, preserved earlier snapshots, fresh quote reuse, partial consolidation, missing-observation status, and UI controls.

Final validation: standard pytest **185 passed, 40 skipped**; with `RUN_DB_TESTS=1` against the isolated, migrated PostgreSQL database **225 passed**; Playwright **10 passed**; `npm run build` passed; `alembic check` reported no new upgrade operations. Two existing FastAPI/Starlette deprecation warnings remain. Temporary-file and browser-process sandbox restrictions required running validation with normal filesystem/process access. Browser tests used the documented allowed origin and a seeded test catalog. No personal portfolio database was modified.

Apply migration `0015` before running the updated application against an existing database, then consolidate portfolios to rebuild affected derived returns.
