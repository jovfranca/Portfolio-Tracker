# Issue #41 branch review — 2026-10-06

The confirmed defects below are fixed and covered by regressions. The branch is
not ready for a PR claiming the complete scope of issue #41: the acceptance gaps
listed below remain. A draft PR can make the delivered scope and those gaps explicit.

## Scope and requirements

Reviewed `feat/41-ui-refactor`, including its existing uncommitted changes, against
`develop` and freshly fetched `origin/develop`. All three commit references point
to `1b01e2d63045713e528c40a5051b9cb88bd62800`; the refactor and review fixes are
working-tree changes, not branch commits.

Read [issue #41](https://github.com/jovfranca/Portfolio-Tracker/issues/41) completely
before inspecting implementation code. GitHub returned no follow-up comments.
The initial CLI failure was a refused connection to the sandbox proxy
`127.0.0.1:9`. Removing that proxy for an approved process restored CLI access;
the stored authentication worked on that connection.

Used the supplied handoff architecture for navigation and reviewed the brand and
mockup references. The attachment is reference material, not a separate request
to implement every mockup feature. Financial semantics remain governed by the
existing backend and tests. Canonical assets, typography and palette are checked
by the existing brand regression tests. The review adds no migration and changes
no financial calculation or persistence rule.

## Verified findings and fixes

| Priority | Finding | Fix and evidence |
| --- | --- | --- |
| P1 | Creating a portfolio could select the new portfolio while the mutation still reloaded the old context. A later old response overwrote the displayed overview: the new empty portfolio showed the previous portfolio's value. | `PortfoliosPage` completes the mutation reload before selecting the newly created portfolio. A browser regression delayed the old response and reproduced `120,00` under the new selection instead of `0,00`; it passes after the fix. |
| P2 | Position detail filtered transactions by displayed ticker. Transactions entered/imported under an alias did not match the canonical symbol, so transactions, instrument metadata and the scoped creation action could disappear. Instrument detail used the same text comparison for related positions. | Market position projections now include `instrument_id` in unbuilt, pending and consolidated states. Both detail pages use that identity. An authenticated API test verifies an `ALIAS` transaction with a `CANONICAL` position; the browser regression verifies transaction, creation-action and related-position links. Both failed before the fix. |
| P2 | Overview combined current portfolio value with acquisition cost and result from the last historical closing snapshot. Changes since that snapshot made the cards describe different valuation dates without saying so. | Cost and result now use the existing current reporting-currency summary. The historical accumulated return explicitly shows its date. The browser regression reproduced a historical cost of `100,00` instead of the current `110,00`. No calculation was added to the frontend. |
| P2 | Rolling month/year periods used `Date.setMonth` with the original day of month. Invalid target dates overflowed into the following month. | Period boundaries clamp to the last valid target-month day. Browser coverage verifies March 31 → February 29 and February 29 → February 28 of the previous year. Before the fix the first case started on March 2. |
| P2 | Performance's asset breakdown explicitly excluded fixed income and provided no lot breakdown or links, despite including fixed income in portfolio totals. | Performance reuses the existing lot table alongside market positions. Its values keep their supplied currency labels and gross-value semantics. A browser regression verifies navigation to `/fixed-income/:lotId`; it failed before the fix. |

The app/import browser fixtures also now wait for creation to finish and for the new
portfolio to be selected before doing a full browser navigation. Previously it
could interrupt that asynchronous flow and import into the previously selected
test portfolio. All records involved were synthetic and in the review database.

## Remaining acceptance gaps

These are implementation gaps, not failures to obtain GitHub or PostgreSQL access.
Documenting a limitation does not itself satisfy the corresponding acceptance criterion.

| Requirement | Current implementation and blocker |
| --- | --- |
| §14: invitation acceptance shows the financial space, inviter and role, with Accept/Reject | `InvitationPage.tsx` asks the recipient to check these details with the sender and offers acceptance or navigation away. There is no invitation-preview or rejection API. `HouseholdInvitation` does not persist an inviter and its status constraint only permits PENDING/ACCEPTED/REVOKED. Completing this needs an authenticated preview contract and a defined rejection/audit lifecycle; navigating away must not be described as rejection. |
| §11: FX history, used pairs and missing dates; detailed market-data status | `FxPanel` only queries one currency/type/date at a time. The current HTTP contract exposes single-date lookup and backfill, not the required history/coverage projection. Status links identify categories, but do not provide complete date/pair coverage diagnostics or the last successful synchronization time. Supporting projections are still needed; a historical closing date is not an update timestamp. |
| §13: financial-space list includes member count, portfolio count and status | The list currently shows name, role and actions. The underlying records exist, but the space/session projection does not supply these counts/status and the UI does not render them. This is a remaining page-completeness item, not a need for a new financial rule. |
| §3: Overview includes a period result | The page shows current accumulated monetary result and a dated accumulated historical return. It has no selected-period result experience. The period analytics API currently returns return percentage and net contributions, not a monetary period-result projection. Its definition must respect existing flows and valuation semantics. |

Other limits are documented in `docs/quintrion-ui.md`: production local-password
signup/recovery, Apple, account/profile lifecycle, portfolio/space archival,
manual-price deletion, manual FX correction, corporate-event approval states,
transaction origin/audit metadata and benchmark comparison. Requirements expressly
conditional on existing support should not be treated as implemented; nor should
the UI simulate successful unsupported operations. Invitation metadata/rejection
and the coverage views above are explicit gaps in the requested full experience.

## Verification

- Default repository command: **351 passed, 58 skipped**. Skips are the opt-in database tests.
- Full suite with `RUN_DB_TESTS=1`: **409 passed** against the isolated migrated PostgreSQL database.
- `npm run build`: passed.
- Final Playwright suite: **36 passed**, including five new browser regressions.
- Inspected desktop, mobile and dark-theme screenshots; core navigation and layout fit the viewport.
- `alembic current`: `0026 (head)`; `alembic check`: no new upgrade operations.
- `git diff --check`: passed.

Initialized a separate PostgreSQL cluster at `.local/review41-pgdata`, bound to
`127.0.0.1:55441`, and created `review41_test` and `review41_browser`. Applied
`alembic upgrade head` to both empty databases. Browser tests used the isolated
API at port 8041. The review services were stopped after verification. No persistent
development database was modified.

Sandbox restricted-token/process-spawn errors initially prevented PostgreSQL and
Playwright startup; approved execution resolved them. Pytest temporary-directory
ACL errors were likewise resolved with approved execution. These are resolved
environment restrictions, not outstanding verification blockers.

Browser and financial-provider regressions use synthetic data and controlled
provider responses. Live Google sign-in and real provider availability were not
verified by this review. Two existing FastAPI/Starlette deprecation warnings remain.

The final legacy-brand search found only documented compatibility references:
repository links, existing database/volume identifiers, authentication cookies,
the `X-Aurion-Request` protocol header and migration from `aurion-household` local
storage. These are intentionally retained; no product branding regression was found.

No commit, push or PR was created.
