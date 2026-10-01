Review of issue #38 — 2026-10-01

**Not ready for PR as a completed implementation of #38.** The corrective changes
below pass verification, but two acceptance gaps remain in the reporting model.

Compared `feat/38-consolidation-optimization` at
`f67b0067ffc7a1a62b74785950ab294b796ac310`, including the existing uncommitted
accounting-currency work, against `develop` at
`b48b4f4785798aeb567717b67697ab5958a693b4`. GitHub's develop SHA matches the local
branch. Read [issue #38](https://github.com/jovfranca/Portfolio-Tracker/issues/38)
and the attached accounting-currency follow-up. Initial GitHub access failed
because of the sandbox proxy; access succeeded outside the sandbox before edits.

Remaining blockers:

- **P1 — Fixed-income history is still reconstructed on reads, without canonical
  lot snapshots.** `src/consolidation.py:190` and `src/consolidation.py:299` call
  `daily_position_rows` for every reporting day. That calls the contractual
  valuation from the lot's inception. The consolidation loops explicitly skip
  fixed-income snapshot persistence (`src/consolidation.py:540`). A synthetic
  zero-rate, 30-day lot produced 30 full lot valuations on a single history GET,
  with zero persisted position snapshots after consolidation. Its overview also
  reads live movements (`src/position_reporting.py:303`): editing the opening
  amount from 1,000 to 1,500 immediately changed the displayed value to 1,500 while
  history was still pending. Thus explicit consolidation does not control the
  fixed-income state being displayed; checkpoint reuse and lightweight historical
  projection are absent for these positions. Completion requires persisted lot
  state in contractual currency, targeted rebuilding of affected ranges, and
  reporting from that state. Add regression tests prohibiting contractual replay
  on history GET and preserving displayed consolidated values through pending
  movement edits/deletions. The currency-resolver test for fixed income alone
  does not establish those properties.

- **P2 — Market positions without a saved snapshot still use live activity on
  overview GET.** The pending-state guard at `src/position_reporting.py:167` only
  handles an existing snapshot. Otherwise the read falls through to
  `position_now` at line 217. A synthetic position with `history_built_through =
  None` showed quantity 2, then quantity 3 after an edit, without any consolidation.
  This includes new positions and histories cleared by migrations. Completion
  requires an explicit unbuilt/pending response instead of reconstructing the
  position on reads, with matching first-consolidation and new-instrument tests.

These are implementation blockers, not unavailable PostgreSQL or dependencies.
They were reproduced but are not resolved by the fixes in this review.

Verified and fixed:

- **Pending market reads replayed edited activity before replacing its output
  with saved values.** A pending reverse split followed by a previously valid
  sale caused history/overview reads to raise an oversell error. Projection now
  stops applying activity at the dirty boundary; overview uses the saved
  checkpoint directly. Dated accounting amounts remain unknown when their saved
  currency differs from display currency, rather than using valuation-day FX.
- **Manual pricing-currency changes could leave canonical checkpoints in the
  old currency.** Invalidation now compares the resulting manual pricing currency
  with saved accounting currency and rebuilds from the first transaction when it
  changes. Ordinary price corrections/deletions that retain the accounting
  currency do not invalidate the ledger.
- **Ambiguous primary pricing mappings silently fell back to native currency.**
  Accounting-currency resolution now fails explicitly. Retired mappings sharing
  one quote currency still retain their readable historical prices.
- **An equity edit suppressed unrelated fixed-income portfolio values.** The
  fixed-income pending boundary now uses invalidations of fixed-income
  instruments, rather than the portfolio-wide dirty date. Known stale equity
  values remain flagged incomplete without erasing clean fixed-income values.
- **Legacy import failed against a seeded foreign-instrument catalog and still
  calculated an overview during writes.** Archived prices now retain their
  legacy currency and provenance without being validated as new manual quotes;
  they remain excluded from valuation and accounting-currency selection. Import
  performs quantity/oversell validation without constructing the overview.
- Corrected setup instructions that still described automatic consolidation on
  currency changes and canonical invalidation by ordinary price/FX corrections.

Regression tests were added before the behavioral fixes and demonstrated the
failures. Coverage also now exercises a provider-backed foreign listed asset,
alongside crypto, through canonical persistence and display-currency changes.

Verification completed:

- Full suite with `RUN_DB_TESTS=1`: **330 passed**, including relevant PostgreSQL
  tests; two existing FastAPI/Starlette deprecation warnings.
- Frontend `npm run build`: **passed**.
- Edge/Playwright `positions.spec.ts` and `instruments.spec.ts`: **7 passed**,
  including explicit update and currency switching without consolidation.
- Fresh migrations through `0024`: **passed** on a new PostgreSQL cluster on
  port 55438. A second synthetic database verified the populated
  `0022 -> 0023 -> 0024` path: derived snapshots were removed, the source
  transaction survived, and the earliest dirty date was retained for rebuilding.
- `alembic check`: **no schema drift**. `git diff --check`: **passed**.

The persistent development database was not used or modified. The isolated
databases were `review38` and `review38_upgrade` in `.local/pg-review38`.
Windows sandbox permissions initially blocked pytest temporary directories and
Playwright worker creation; rerunning those checks outside the sandbox resolved
the restrictions. No database-backed verification remains blocked.
