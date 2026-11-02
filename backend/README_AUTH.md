# NidhiGuard — Authentication & Authorization (Stage 6.6)

One login page, one authentication system, three roles. The same
username/password login decides the role. There is **no sign-up**: accounts
are created internally.

## Setup

```cmd
:: 1. (optional but recommended) a stable signing secret
python -c "import secrets; print(secrets.token_urlsafe(48))"
copy backend\.env.example backend\.env      &:: then paste the value after NIDHIGUARD_AUTH_SECRET=

:: 2. create the tables and the DEVELOPMENT/DEMO accounts (safe to re-run)
python -m backend.app.auth.seed

:: 3. run the API
python -m uvicorn backend.app.main:app --reload
```

Environment variables: `NIDHIGUARD_AUTH_SECRET`, `NIDHIGUARD_AUTH_TOKEN_MINUTES`
(default 480), optional `NIDHIGUARD_DEMO_*_PASSWORD`. See `backend/.env.example`.

## DEVELOPMENT / DEMO accounts — never use for anything real

| Username       | Role          | Demo password           |
|----------------|---------------|-------------------------|
| `admin`        | Administrator | `Admin@Demo2026`        |
| `investigator` | Investigator  | `Investigator@Demo2026` |
| `viewer`       | Viewer        | `Viewer@Demo2026`       |

They exist only in the local, git-ignored SQLite database, created by the
explicit seed command above (the server never seeds users on startup).

## Role permissions (enforced by the backend)

| Area                                              | Administrator | Investigator | Viewer |
|---------------------------------------------------|:---:|:---:|:---:|
| Dashboard (`/api/dashboard/summary`)              | ✔ | ✔ | ✔ |
| Projects list (`/api/projects`)                   | ✔ | ✔ | ✔ |
| Risk analysis (`/api/projects/{id}/risk`, `/api/risk-results`) | ✔ | ✔ | ✔ |
| Reports (frontend page, no API yet)               | ✔ | ✔ | ✔ |
| Project investigation (`/api/projects/{id}`, `/relationships`, `/geography`) | ✔ | ✔ | ✘ 403 |
| Investigation queue (`/api/investigation-queue`)  | ✔ | ✔ | ✘ 403 |
| Contractors (`/api/contractors…`)                 | ✔ | ✔ | ✘ 403 |
| Geographic intelligence (`/api/geography`)        | ✔ | ✔ | ✘ 403 |
| User management (`/api/users…`)                   | ✔ | ✘ 403 | ✘ 403 |
| V2.6 Investigation status + history, read (`GET /api/projects/{id}/investigation`, `GET /api/investigations`) | ✔ | ✔ | ✔ |
| V2.6 Change status / add note (`POST /api/projects/{id}/investigation/status`, `…/notes`) | ✔ | ✔ | ✘ 403 |

V2.6 investigation workflow state is recorded by human investigators and is separate from
risk. There is no PUT/PATCH/DELETE route: the audit history (`investigation_history`) is
append-only, and the ORM also refuses UPDATE/DELETE on it. The acting user always comes from
the token, never from the request body.

No token / bad token / expired / logged-out / deactivated user → **401**.
Valid user, wrong role → **403**. `/` and `/health` stay public.

## How it works

- Passwords: salted **scrypt** (stdlib `hashlib`), stored as `scrypt$N$r$p$salt$hash`.
- Login returns a signed **HS256 token** (stdlib `hmac`; claims `sub`, `jti`, `iat`, `exp`),
  sent as `Authorization: Bearer <token>`. No new dependencies.
- The role is read from the database on every request, so role changes and
  deactivation apply immediately to tokens already issued.
- **Logout** (`POST /api/auth/logout`) adds the token's `jti` to a server-side
  deny-list (`revoked_tokens`); the token stops working at once.
- Failed logins (unknown user, wrong password, inactive account) all return
  the same `401 Invalid username or password.`.

## Known limitations (prototype)

- No login rate-limiting / lockout, MFA, password reset, or refresh tokens.
- The frontend keeps the token in `sessionStorage` (cleared when the tab closes);
  like any browser-stored token it is exposed to XSS.
- Without `NIDHIGUARD_AUTH_SECRET`, a random per-process secret is used and
  sessions end when the server restarts. Single-process only.
- Serve over HTTPS outside local development.
