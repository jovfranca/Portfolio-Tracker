# Authentication and financial spaces

Issue #34 introduces backend-validated sessions and financial spaces (`Household`).
Portfolios belong to a space. Memberships grant application access; they do not
represent legal or economic ownership of investments.

## Local development

Apply `python -m alembic upgrade head`, install the updated `requirements.txt`, and
rebuild the frontend. Migration `0026` creates the initial user, personal space
and OWNER membership, and assigns existing portfolios and non-catalog instruments
to that space. It preserves transactions, manual prices/events, imports, contracts,
snapshots and shared market/reference data. No financial history is recalculated.

`scripts/start-local.ps1` starts an interactive HTTP server bound to `127.0.0.1`.
When neither Google nor development login is configured, it prompts for a hidden
development key and enables local login for that server process. Use username
**local** and the key you entered. The key is never printed or saved in `.env`;
you choose a key again on the next unconfigured startup. Configured Google or
development credentials are preserved. The launcher sets HTTP-compatible cookies
only in its own process; direct Uvicorn startup keeps the secure defaults.
Noninteractive startup requires configured credentials instead of an echoed prompt.

For a persistent development key, or direct Uvicorn HTTP development on loopback,
configure these values in your private `.env`:

```dotenv
DEV_AUTH_ENABLED=1
DEV_AUTH_TOKEN=<a random development key you choose>
SESSION_COOKIE_SECURE=0
```

On the login screen, use username **local** and your development key to access the
migrated records. Other local usernames create separate users with personal spaces.
This is a development bootstrap credential, not a production password system.
It is disabled unless explicitly enabled with a nonempty key and a loopback host.
All development sessions use the same memberships and role checks as Google.

Sessions use random HTTP-only, SameSite=Lax cookies. Only SHA-256 token hashes are
stored in PostgreSQL. Sessions expire after seven days; login rotates the current
session, logout deletes it, and disabled users are rejected on the next request.
Membership changes/removal take effect on subsequent requests.

## Google and production

Create an OAuth **Web application** client in Google Cloud, configure the exact
authorized JavaScript origins (including scheme and port), and set
`GOOGLE_CLIENT_ID` to its client ID. The UI loads Google Identity Services and the
backend verifies the signed ID token's audience, issuer, expiration and a single-use
10-minute nonce. Identity resolution uses `(provider, provider_subject)`, never email.
See [Google's server verification guide](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token).

To retain the initial user's records with Google login, first log in locally as
**local**, then use **Vincular Google**. This explicitly links the verified Google
identity to the current user; matching emails never automatically merge users.
An identity already attached to another user cannot be linked. A new Google login
without linking creates its own personal space.

For deployment, use HTTPS, `SESSION_COOKIE_SECURE=1` (the default), disable
`DEV_AUTH_ENABLED`, remove the development key, and configure `ALLOWED_ORIGINS`
with your trusted frontend origins. The built frontend works on the same origin;
Vite forwards `/api` during local development. Cookies have no frontend-readable
session token and are scoped to `/api`. Provider credentials and invitation tokens
are not logged or stored in plaintext.

All API mutations require `X-Aurion-Request: 1`, including login and logout. This
non-simple header plus the trusted-origin/CORS checks blocks cross-site form requests.
API responses disable caching. Non-browser API clients must retain the session
cookie and send the header as well. A submitted user ID cannot select a session user.

The provider-independent identity model allows additional providers such as Apple.
Apple integration and automatic invitation email delivery remain out of scope.

## Spaces, roles and invitations

The shell displays the current user and financial space. Switching spaces resets
the portfolio UI and changes the `X-Household-ID` selection. The remembered space
ID is a UI preference; the server always checks its membership. Without a selected
space, `GET /api/portfolios` lists all accessible portfolios; creation requires
explicit selection when the user has multiple memberships.

OWNER can administer the space and edit financial records; EDITOR can edit records;
VIEWER has read access. The last owner cannot be removed or demoted. Inaccessible
spaces/portfolios/nested resources return 404. Custom and migrated instruments are
private to their financial space; catalog instruments and provider prices, FX,
PTAX and benchmarks remain shared. Ordinary user imports cannot redefine shared
catalog aliases. Private fixed-income instruments retain their portfolio boundary.

Space creation is available in the shell. Membership administration and invitations
are available through authenticated APIs (`/docs` lists the schemas):

| Endpoint | Purpose |
| --- | --- |
| `GET /api/households` | Accessible spaces and current roles |
| `POST /api/households` | Create `{ "name": "Family" }` with creator as OWNER |
| `PUT /api/households/{id}` | OWNER renames space |
| `GET /api/households/{id}/members` | OWNER lists members |
| `PUT /api/households/{id}/members/{member_id}` | OWNER sets `{ "role": "VIEWER" }` |
| `DELETE /api/households/{id}/members/{member_id}` | OWNER removes membership |
| `POST /api/households/{id}/invitations` | OWNER creates `{ "email": "person@gmail.com", "role": "EDITOR" }` |
| `DELETE /api/households/{id}/invitations/{invitation_id}` | OWNER revokes invitation |
| `POST /api/invitations/accept` | Invited user submits `{ "token": "..." }` |

Creation returns the invitation token once; share it privately with the recipient.
It is stored hashed, expires after seven days, and is consumed on acceptance.
Acceptance requires an authenticated verified identity matching the invited email.
Google is authoritative for Gmail/Workspace email; a third-party Google email is
not sufficient for invitation acceptance without another verification mechanism.
Local usernames do not claim verified emails. Existing memberships are preserved
on acceptance rather than silently changing their role. No portfolios are copied.

The legacy CLI must receive `--household-id` when creating a new portfolio, or
`--portfolio-id` for an existing portfolio. It is an operator tool with database
access; it is not an HTTP authentication bypass. Migration rollback is refused
once multiple users/spaces exist, to avoid removing privacy boundaries.

## Verification

Run the backend suite and frontend build from `AGENTS.md`. Set `RUN_DB_TESTS=1`
only for a separately migrated test database. Run `python -m alembic check` there.
The identity migration regression uses synthetic rows and verifies source/derived
and shared records remain unchanged.

`scripts/start-browser-test.ps1` enables local bootstrap authentication only for
its dedicated synthetic browser database. `npm test` authenticates existing
financial workflows with the test-only key. The authentication browser case covers
invalid login, login, protected startup, restoration, space switching and logout.
`PLAYWRIGHT_BASE_URL` can select another dedicated API URL.

Manually verify your real Google client/origin configuration and explicitly link
the initial user before switching away from local development authentication.
